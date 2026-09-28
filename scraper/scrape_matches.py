#!/usr/bin/env python3
"""
Match-Scraper für Anstoss App.

Läuft unbeaufsichtigt auf GitHub Actions (kein eigener PC).
Quellen, die von Runner-IPs JSON liefern — kein Cloudflare/Akamai-HTML.
"""

import csv
import io
import json
import os
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

HEADERS = {
    'User-Agent': (
        'AnstossScraper/1.0 (+https://github.com/florianschommers/AnstossScraper) '
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json,text/plain;q=0.9,*/*;q=0.8',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
}

FINISHED_EPS = {
    'FT', 'AET', 'FT_PEN', 'AP', 'AWARDED', 'AFTER ET', 'PEN', 'WO', 'AOT',
}
UPCOMING_EPS = {'NS', 'POSTP', 'POSTPONED', 'CANC', 'ABD', 'SUSP', 'INT', 'TBD'}


def log(msg: str) -> None:
    print(msg, flush=True)


def get_openligadb_season() -> str:
    """OpenLigaDB nutzt das Startjahr: 2026 = Saison 2026/27."""
    now = datetime.now()
    if now.month >= 7:
        return str(now.year)
    return str(now.year - 1)


def get_display_season() -> str:
    """Endjahr wie bisher in der JSON (2027 = 2026/27)."""
    return str(int(get_openligadb_season()) + 1)


def pick(d: dict, *keys):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def to_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.replace(microsecond=0).isoformat() + 'Z'
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def europe_naive_to_utc(dt_naive: datetime, zone_name: str) -> datetime:
    """Lokale Anstoßzeit (IT/FR) nach UTC. Fallback ohne tzdata: CET/CEST grob."""
    try:
        from zoneinfo import ZoneInfo
        return dt_naive.replace(tzinfo=ZoneInfo(zone_name)).astimezone(timezone.utc)
    except Exception:
        month = dt_naive.month
        offset = 2 if 3 < month < 11 else 1
        return (dt_naive - timedelta(hours=offset)).replace(tzinfo=timezone.utc)


def http_get(url: str, accept: str = 'application/json,text/html;q=0.9') -> Tuple[int, str, str]:
    log(f"  🌐 GET {url}")
    try:
        headers = dict(HEADERS)
        headers['Accept'] = accept
        response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)
        body = response.text or ''
        extra = f" | redirect→ {response.url}" if response.url != url else ''
        log(f"     HTTP {response.status_code} | {len(response.content or b'')} Bytes{extra}")
        if response.status_code not in (200, 201):
            snippet = re.sub(r'\s+', ' ', body[:160]).strip()
            if snippet:
                log(f"     Body: {snippet}")
        if 'Just a moment' in body or 'cf-chl' in body.lower():
            log("     ⚠️ Cloudflare-Challenge — Quelle für GitHub-Runner unbrauchbar")
        if response.status_code == 202 and len(response.content or b'') < 5000:
            log("     ⚠️ HTTP 202 mit Mini-Seite — Bot-Schutz, Quelle überspringen")
        return response.status_code, body, response.url
    except Exception as e:
        log(f"     ❌ Request-Fehler: {e}")
        return 0, '', url


def end_score_from_results(results) -> Optional[str]:
    if not isinstance(results, list):
        return None
    end = None
    for r in results:
        kind = str(pick(r, 'resultTypeKind', 'ResultTypeKind') or '')
        name = str(pick(r, 'resultName', 'ResultName') or '')
        type_id = pick(r, 'resultTypeID', 'ResultTypeID')
        if type_id == 2 or kind in ('After90Minutes', 'AfterExtraTime', 'AfterPenalties') or name in (
            'Endergebnis',
            'nach Verlängerung',
            'n.V.',
            'n.E.',
        ):
            end = r
    if end is None and results:
        end = results[-1]
    if not end:
        return None
    p1 = pick(end, 'pointsTeam1', 'PointsTeam1')
    p2 = pick(end, 'pointsTeam2', 'PointsTeam2')
    if p1 is None or p2 is None:
        return None
    return f'{int(p1)}:{int(p2)}'


def phase_from_group_name(name: str) -> str:
    n = (name or '').lower()
    if 'play' in n:
        return 'play-offs'
    if 'achtel' in n or 'round of 16' in n or 'r16' in n:
        return 'achtelfinale'
    if 'viertel' in n or 'quarter' in n:
        return 'viertelfinale'
    if 'halb' in n or 'semi' in n:
        return 'halbfinale'
    if 'finale' in n or n.strip() == 'final':
        return 'finale'
    return 'gruppenphase'


def convert_oldb_match(raw: dict, international: bool) -> Optional[Dict]:
    team1 = pick(raw, 'team1', 'Team1') or {}
    team2 = pick(raw, 'team2', 'Team2') or {}
    if not isinstance(team1, dict) or not isinstance(team2, dict):
        return None
    home = pick(team1, 'teamName', 'TeamName') or ''
    away = pick(team2, 'teamName', 'TeamName') or ''
    if not home or not away:
        return None

    group = pick(raw, 'group', 'Group') or {}
    matchday = pick(group, 'groupOrderID', 'GroupOrderID') or 1
    try:
        matchday = int(matchday)
    except (TypeError, ValueError):
        matchday = 1

    finished = bool(pick(raw, 'matchIsFinished', 'MatchIsFinished'))
    utc = pick(raw, 'matchDateTimeUTC', 'MatchDateTimeUTC')
    local = pick(raw, 'matchDateTime', 'MatchDateTime')
    date_time = utc or (f'{local}Z' if local and not str(local).endswith('Z') else local)
    if not date_time:
        return None
    date_time = str(date_time).replace('+00:00', 'Z')
    if date_time.endswith('Z') and '.' in date_time:
        date_time = date_time.split('.')[0] + 'Z'

    kickoff = None
    try:
        kickoff = datetime.fromisoformat(date_time.replace('Z', '+00:00'))
    except ValueError:
        pass

    now = datetime.now(timezone.utc)
    is_live = False
    if kickoff and not finished:
        is_live = kickoff <= now <= kickoff + timedelta(hours=3)

    results = pick(raw, 'matchResults', 'MatchResults')
    score = end_score_from_results(results) if finished else None
    live_score = end_score_from_results(results) if is_live else None

    rec = {
        'matchday': matchday,
        'homeTeam': home,
        'awayTeam': away,
        'dateTime': date_time,
        'score': score,
        'isFinished': finished,
        'isLive': is_live,
        'liveScore': live_score,
    }
    if international:
        rec['phase'] = phase_from_group_name(str(pick(group, 'groupName', 'GroupName') or ''))
    return rec


def scrape_openligadb(league: str, shortcuts: List[str], international: bool) -> List[Dict]:
    season = get_openligadb_season()
    log(f"   Quelle: OpenLigaDB API | Saison-Startjahr {season}")
    log("   Spiel = JSON-Objekt mit team1/team2; fertig = matchIsFinished; "
        "Ergebnis = matchResults Endergebnis; Datum = matchDateTimeUTC")

    for shortcut in shortcuts:
        url = f'https://api.openligadb.de/getmatchdata/{shortcut}/{season}'
        status, body, _final = http_get(url, accept='application/json')
        if status != 200:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            log("     ⚠️ Antwort ist kein JSON")
            continue
        if not isinstance(data, list) or not data:
            log(f"     Shortcut {shortcut}: 0 Spiele")
            continue

        matches: List[Dict] = []
        skipped = 0
        for i, raw in enumerate(data, 1):
            rec = convert_oldb_match(raw, international)
            if rec is None:
                skipped += 1
                continue
            status_lbl = 'LIVE' if rec['isLive'] else ('BEENDET' if rec['isFinished'] else 'ZUKUNFT')
            score_txt = rec['liveScore'] or rec['score'] or '-'
            if i <= 6 or i % 50 == 0:
                log(
                    f"     ✓ {status_lbl}: {rec['homeTeam']} vs {rec['awayTeam']} | "
                    f"{rec['dateTime']} | {score_txt} | festgemacht an "
                    f"matchIsFinished={rec['isFinished']} groupOrderID={rec['matchday']} | {shortcut}"
                )
            matches.append(rec)
        log(f"  ✅ {league} via {shortcut}: {len(matches)} Spiele (übersprungen {skipped})")
        return matches

    log(f"  ⛔ Kein OpenLigaDB-Shortcut lieferte Spiele für {league}: {shortcuts}")
    return []


def livescore_team_name(side) -> str:
    if isinstance(side, list) and side:
        side = side[0]
    if not isinstance(side, dict):
        return ''
    return str(side.get('Nm') or '').strip()


def parse_livescore_esd(esd) -> Optional[datetime]:
    raw = str(esd or '').split('.')[0]
    digits = re.sub(r'\D', '', raw)
    if len(digits) < 12:
        return None
    digits = digits[:14].ljust(14, '0')
    try:
        return datetime.strptime(digits, '%Y%m%d%H%M%S')
    except ValueError:
        return None


def fill_missing_matchdays(rows: List[Dict]) -> None:
    """Livescore markiert manche Ligue-1-Spiele als 'Regular Season' statt Spieltag-Nummer."""
    anchors = []
    for r in rows:
        md = r.get('matchday')
        if not md:
            continue
        try:
            dt = datetime.fromisoformat(str(r['dateTime']).replace('Z', '+00:00'))
        except ValueError:
            continue
        anchors.append((dt, int(md)))
    if not anchors:
        for r in rows:
            if not r.get('matchday'):
                r['matchday'] = 1
        return
    for r in rows:
        if r.get('matchday'):
            continue
        try:
            dt = datetime.fromisoformat(str(r['dateTime']).replace('Z', '+00:00'))
        except ValueError:
            r['matchday'] = 1
            continue
        nearest = min(anchors, key=lambda a: abs((a[0] - dt).total_seconds()))
        r['matchday'] = nearest[1]


def scrape_livescore(league: str, country: str, slug: str, tz_name: str) -> List[Dict]:
    url = f'https://prod-cdn-public-api.livescore.com/v1/api/app/stage/soccer/{country}/{slug}/1'
    log(f"   Quelle: Livescore JSON | {country}/{slug}")
    log("   Spiel = Events[]; Teams = T1[0].Nm / T2[0].Nm; Ergebnis = Tr1:Tr2 wenn Eps=FT; "
        "Datum = Esd (YYYYMMDDHHmmss, lokale Zeit); Spieltag = ErnInf Ziffer")

    status, body, _final = http_get(url, accept='application/json')
    if status != 200:
        log(f"  ⛔ Livescore HTTP {status} für {league}")
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        log("  ⛔ Livescore lieferte kein JSON")
        return []

    stages = data.get('Stages') or []
    events = []
    for st in stages:
        events.extend(st.get('Events') or [])
    if not events:
        log(f"  ⛔ Livescore ohne Events für {league}")
        return []

    matches: List[Dict] = []
    skipped = 0
    now = datetime.now(timezone.utc)
    for i, ev in enumerate(events, 1):
        home = livescore_team_name(ev.get('T1'))
        away = livescore_team_name(ev.get('T2'))
        local_dt = parse_livescore_esd(ev.get('Esd'))
        if not home or not away or local_dt is None:
            skipped += 1
            continue
        kickoff = europe_naive_to_utc(local_dt, tz_name)
        date_time = to_iso_z(kickoff)
        eps = str(ev.get('Eps') or 'NS').strip().upper()
        tr1, tr2 = ev.get('Tr1'), ev.get('Tr2')
        score = None
        if tr1 is not None and tr2 is not None and str(tr1) != '' and str(tr2) != '':
            try:
                score = f'{int(tr1)}:{int(tr2)}'
            except (TypeError, ValueError):
                score = None
        finished = eps in FINISHED_EPS
        upcoming = eps in UPCOMING_EPS
        is_live = (not finished) and (
            (not upcoming) or (kickoff <= now <= kickoff + timedelta(hours=3) and eps == 'NS')
        )
        ern = str(ev.get('ErnInf') or '').strip()
        matchday = int(ern) if ern.isdigit() else None
        rec = {
            'matchday': matchday,
            'homeTeam': home,
            'awayTeam': away,
            'dateTime': date_time,
            'score': score if finished and not is_live else None,
            'isFinished': finished and not is_live,
            'isLive': is_live,
            'liveScore': score if is_live else None,
        }
        matches.append(rec)
        status_lbl = 'LIVE' if rec['isLive'] else ('BEENDET' if rec['isFinished'] else 'ZUKUNFT')
        if i <= 6 or i % 50 == 0:
            log(
                f"     ✓ {status_lbl}: {home} vs {away} | {date_time} | {score or '-'} | "
                f"festgemacht an Esd={ev.get('Esd')} Eps={eps} ErnInf={ern} Tr={tr1}:{tr2}"
            )

    fill_missing_matchdays(matches)
    log(f"  ✅ {league} via Livescore: {len(matches)} Spiele (übersprungen {skipped})")
    return matches


def scrape_football_data_csv(league: str, code: str, per_round: int, tz_name: str) -> List[Dict]:
    """Nur bereits gespielte Partien — Notnagel, falls Livescore von GitHub blockt."""
    yy = int(get_openligadb_season()) % 100
    season_code = f'{yy:02d}{yy + 1:02d}'
    url = f'https://www.football-data.co.uk/mmz4281/{season_code}/{code}.csv'
    log(f"   Fallback: football-data.co.uk CSV {code} | Saison {season_code}")
    log("   Spiel = CSV-Zeile; Teams = HomeTeam/AwayTeam; Ergebnis = FTHG:FTAG; "
        f"Datum/Zeit = Date+Time; Spieltag = Reihenfolge je {per_round} Spiele")

    status, body, _final = http_get(url, accept='text/csv,text/plain;q=0.9')
    text = (body or '').lstrip('\ufeff')
    if status != 200 or not text or ('Div,' not in text[:120] and 'Date,' not in text[:120]):
        log(f"  ⛔ CSV unbrauchbar für {league}")
        return []

    reader = csv.DictReader(io.StringIO(text))
    raw_rows = []
    for row in reader:
        home = (row.get('HomeTeam') or '').strip()
        away = (row.get('AwayTeam') or '').strip()
        date_s = (row.get('Date') or '').strip()
        time_s = (row.get('Time') or '15:00').strip()
        if not home or not away or not date_s:
            continue
        try:
            local_dt = datetime.strptime(f'{date_s} {time_s}', '%d/%m/%Y %H:%M')
        except ValueError:
            try:
                local_dt = datetime.strptime(date_s, '%d/%m/%Y')
            except ValueError:
                continue
        fthg, ftag = row.get('FTHG'), row.get('FTAG')
        score = None
        finished = False
        if fthg not in (None, '') and ftag not in (None, ''):
            try:
                score = f'{int(fthg)}:{int(ftag)}'
                finished = True
            except (TypeError, ValueError):
                pass
        raw_rows.append((local_dt, home, away, score, finished))

    raw_rows.sort(key=lambda x: x[0])
    matches: List[Dict] = []
    for i, (local_dt, home, away, score, finished) in enumerate(raw_rows):
        rec = {
            'matchday': (i // per_round) + 1,
            'homeTeam': home,
            'awayTeam': away,
            'dateTime': to_iso_z(europe_naive_to_utc(local_dt, tz_name)),
            'score': score if finished else None,
            'isFinished': finished,
            'isLive': False,
            'liveScore': None,
        }
        matches.append(rec)
        if i < 6 or (i + 1) % 50 == 0:
            log(
                f"     ✓ BEENDET: {home} vs {away} | {rec['dateTime']} | {score or '-'} | "
                f"festgemacht an CSV-Zeile Spieltag {rec['matchday']}"
            )
    log(f"  ✅ {league} via football-data.co.uk: {len(matches)} Spiele (nur Ergebnisse, keine Zukunft)")
    return matches


def uefa_team_name(team: dict) -> str:
    if not isinstance(team, dict):
        return ''
    trans = team.get('translations') or {}
    for bag_key in ('displayName', 'officialName', 'name', 'teamName'):
        bag = trans.get(bag_key)
        if isinstance(bag, dict):
            for lang in ('DE', 'de', 'EN', 'en'):
                val = bag.get(lang)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return str(team.get('internationalName') or team.get('teamCode') or '').strip()


def uefa_score(score_obj) -> Optional[str]:
    if not isinstance(score_obj, dict):
        return None
    for key in ('regular', 'total', 'aggregate'):
        part = score_obj.get(key)
        if not isinstance(part, dict):
            continue
        h, a = part.get('home'), part.get('away')
        if h is None or a is None:
            continue
        try:
            return f'{int(h)}:{int(a)}'
        except (TypeError, ValueError):
            continue
    return None


def scrape_uefa_conference(league: str) -> List[Dict]:
    season_year = get_display_season()
    log(f"   Quelle: UEFA Match API | competitionId=2019 seasonYear={season_year}")
    log("   Spiel = JSON-Match; Teams = internationalName/translations.DE; fertig = status FINISHED; "
        "Ergebnis = score.regular; Datum = kickOffTime.dateTime UTC; "
        "Ligaphase = round.phase!=QUALIFYING; Spieltag = matchday.sequenceNumber")

    matches: List[Dict] = []
    skipped = 0
    offset = 0
    now = datetime.now(timezone.utc)
    while offset < 800:
        url = (
            f'https://match.uefa.com/v5/matches?competitionId=2019'
            f'&seasonYear={season_year}&limit=100&offset={offset}'
        )
        status, body, _final = http_get(url, accept='application/json')
        if status != 200:
            break
        try:
            chunk = json.loads(body)
        except json.JSONDecodeError:
            log("     ⚠️ UEFA-Antwort ist kein JSON")
            break
        if not isinstance(chunk, list) or not chunk:
            break

        for raw in chunk:
            rnd = raw.get('round') or {}
            if str(rnd.get('phase') or '').upper() == 'QUALIFYING':
                skipped += 1
                continue
            if (raw.get('homeTeam') or {}).get('isPlaceHolder') or (raw.get('awayTeam') or {}).get('isPlaceHolder'):
                skipped += 1
                continue
            home = uefa_team_name(raw.get('homeTeam') or {})
            away = uefa_team_name(raw.get('awayTeam') or {})
            kick = (raw.get('kickOffTime') or {}).get('dateTime') or ''
            if not home or not away or not kick:
                skipped += 1
                continue
            date_time = str(kick).replace('+00:00', 'Z')
            if date_time.endswith('Z') and '.' in date_time:
                date_time = date_time.split('.')[0] + 'Z'
            try:
                kickoff = datetime.fromisoformat(date_time.replace('Z', '+00:00'))
            except ValueError:
                skipped += 1
                continue

            md_obj = raw.get('matchday') or {}
            matchday = md_obj.get('sequenceNumber') or 1
            try:
                matchday = int(matchday)
            except (TypeError, ValueError):
                matchday = 1

            st = str(raw.get('status') or '').upper()
            finished = st in ('FINISHED', 'OFFICIAL')
            is_live = st in ('LIVE', 'ONGOING') or (
                (not finished) and kickoff <= now <= kickoff + timedelta(hours=3) and st != 'UPCOMING'
            )
            score = uefa_score(raw.get('score')) if (finished or is_live) else None
            rec = {
                'matchday': matchday,
                'homeTeam': home,
                'awayTeam': away,
                'dateTime': date_time,
                'score': score if finished and not is_live else None,
                'isFinished': finished and not is_live,
                'isLive': is_live,
                'liveScore': score if is_live else None,
                'phase': phase_from_group_name(str((rnd.get('metaData') or {}).get('name') or '')),
            }
            matches.append(rec)
            n = len(matches)
            if n <= 6 or n % 50 == 0:
                status_lbl = 'LIVE' if rec['isLive'] else ('BEENDET' if rec['isFinished'] else 'ZUKUNFT')
                log(
                    f"     ✓ {status_lbl}: {home} vs {away} | {date_time} | {score or '-'} | "
                    f"festgemacht an UEFA status={st} matchday={matchday} "
                    f"round={(rnd.get('metaData') or {}).get('name')}"
                )

        if len(chunk) < 100:
            break
        offset += 100

    log(f"  ✅ {league} via UEFA: {len(matches)} Ligaphasen-Spiele (Quali übersprungen {skipped})")
    return matches


def scrape_league(league: str) -> List[Dict]:
    """
    england/spain/CL/EL: OpenLigaDB.
    italy/france: Livescore JSON, Fallback football-data.co.uk.
    conferenceleague: UEFA Match API (nur Ligaphase/K.o., ohne Quali).
    """
    configs = {
        'england': {'oldb': ['pl', 'epl', 'pl1']},
        'spain': {'oldb': ['la1']},
        'italy': {
            'livescore': ('italy', 'serie-a', 'Europe/Rome'),
            'csv': ('I1', 10, 'Europe/Rome'),
        },
        'france': {
            'livescore': ('france', 'ligue-1', 'Europe/Paris'),
            'csv': ('F1', 9, 'Europe/Paris'),
        },
        'championsleague': {
            'oldb': ['ucl', f'ucl{get_openligadb_season()}'],
            'international': True,
        },
        'europaleague': {
            'oldb': [f'uel{get_openligadb_season()}', 'uel'],
            'international': True,
        },
        'conferenceleague': {'uefa': True, 'international': True},
    }
    cfg = configs[league]
    international = bool(cfg.get('international'))
    if 'oldb' in cfg:
        return scrape_openligadb(league, cfg['oldb'], international)
    if 'livescore' in cfg:
        country, slug, tz_name = cfg['livescore']
        matches = scrape_livescore(league, country, slug, tz_name)
        if matches:
            return matches
        csv_cfg = cfg.get('csv')
        if csv_cfg:
            code, per_round, tz_name = csv_cfg
            log(f"  ↪️ Livescore leer — Fallback CSV für {league}")
            return scrape_football_data_csv(league, code, per_round, tz_name)
        return []
    if cfg.get('uefa'):
        return scrape_uefa_conference(league)
    return []


def save_matches_json(league: str, season: str, matches: List[Dict], output_dir: str = 'data/matches'):
    os.makedirs(output_dir, exist_ok=True)
    output_data = {
        'league': league,
        'season': season,
        'lastUpdated': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'matches': matches,
        'source': 'openligadb-or-livescore-or-uefa',
    }
    filename = f'{output_dir}/matches_{league}.json'
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    log(f"💾 Gespeichert: {filename} ({len(matches)} Matches)")


def save_matches_json_array(league: str, season: str, matches: List[Dict], output_dir: str = 'data/matches'):
    os.makedirs(output_dir, exist_ok=True)
    filename = f'{output_dir}/matches_{league}.json'
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(matches, f, indent=2, ensure_ascii=False)
    log(f"💾 Gespeichert (Array-Format): {filename} ({len(matches)} Matches)")


def fetch_openligadb_matches(league_shortcut: str, season: str) -> List[Dict]:
    """Rohdaten OpenLigaDB (Original-Format), für andere Uploader."""
    all_matches: List[Dict] = []
    try:
        api_url = f'https://api.openligadb.de/getmatchdata/{league_shortcut}/{season}'
        log(f"🔍 Lade von OpenLigaDB API: {api_url}")
        response = requests.get(api_url, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            log(f"❌ HTTP {response.status_code} für {api_url}")
            return all_matches
        data = response.json()
        if not isinstance(data, list):
            log("⚠️ Unerwartetes Datenformat von API")
            return all_matches
        for match_data in data:
            team1 = pick(match_data, 'team1', 'Team1') or {}
            team2 = pick(match_data, 'team2', 'Team2') or {}
            if not isinstance(team1, dict) or not isinstance(team2, dict):
                continue
            if not pick(team1, 'teamName', 'TeamName') or not pick(team2, 'teamName', 'TeamName'):
                continue
            all_matches.append(match_data)
        log(f"✅ {len(all_matches)} Matches von OpenLigaDB API geladen (Original-Format)")
    except Exception as e:
        log(f"❌ Fehler beim Laden von OpenLigaDB API: {e}")
        traceback.print_exc()
    return all_matches


def main() -> None:
    errors: List[str] = []
    log("🚀 Starte Match-Scraping...")
    log(
        "\n🔎 Quellen (GitHub-tauglich, ohne deinen PC):\n"
        "  OpenLigaDB JSON     — england (pl), spain (la1), championsleague (ucl), europaleague (uelYYYY)\n"
        "  Livescore JSON      — italy (serie-a), france (ligue-1)\n"
        "  UEFA Match API      — conferenceleague Ligaphase (competitionId 2019)\n"
        "  football-data.co.uk — Fallback für italy/france, nur bereits gespielte Partien\n"
        "  fussballdaten.de und Transfermarkt werden NICHT verwendet (403/202 auf Actions)\n"
    )
    season = get_display_season()
    oldb_season = get_openligadb_season()
    log(f"📆 Saison {oldb_season}/{season} (OpenLigaDB-Jahr {oldb_season})")

    try:
        for league in [
            'england',
            'spain',
            'italy',
            'france',
            'championsleague',
            'europaleague',
            'conferenceleague',
        ]:
            try:
                log(f"\n📊 Scrape {league}...")
                matches = scrape_league(league)
                save_matches_json(league, season, matches)
            except Exception as e:
                error_msg = f"Fehler bei {league}: {e}"
                log(f"❌ {error_msg}")
                traceback.print_exc()
                errors.append(error_msg)

        if errors:
            log(f"\n⚠️ Scraping abgeschlossen mit {len(errors)} Fehler(n):")
            for error in errors:
                log(f"  - {error}")
            log("ℹ️ Workflow wird fortgesetzt, da nicht alle Ligen kritisch sind")
        else:
            log("\n✅ Scraping abgeschlossen ohne Fehler!")
    except Exception as e:
        log(f"\n❌ Kritischer Fehler beim Scraping: {e}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == '__main__':
    main()
