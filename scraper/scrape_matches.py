#!/usr/bin/env python3
"""
Match-Scraper für Anstoss App.

Läuft unbeaufsichtigt auf GitHub Actions.
fussballdaten.de blockt Runner per Cloudflare (403 Just a moment) —
deshalb OpenLigaDB (JSON-API) und Transfermarkt (HTML ohne CF-Challenge).
"""

import json
import os
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json,text/html;q=0.9,*/*;q=0.8',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
}

SCORE_RE = re.compile(r'^(\d{1,2}):(\d{1,2})$')
SPIELTAG_RE = re.compile(r'(\d+)\.\s*Spieltag', re.I)
DATE_RE = re.compile(r'(\d{2})\.(\d{2})\.(\d{2,4})')
TIME_RE = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b')


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


def http_get(url: str, accept: str = 'application/json,text/html;q=0.9') -> Tuple[int, str, str]:
    log(f"  🌐 GET {url}")
    try:
        headers = dict(HEADERS)
        headers['Accept'] = accept
        response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)
        body = response.text or ''
        extra = f" | redirect→ {response.url}" if response.url != url else ''
        log(f"     HTTP {response.status_code} | {len(response.content or b'')} Bytes{extra}")
        if response.status_code != 200:
            snippet = re.sub(r'\s+', ' ', body[:160]).strip()
            if snippet:
                log(f"     Body: {snippet}")
        if 'Just a moment' in body or 'cf-chl' in body.lower():
            log("     ⚠️ Cloudflare-Challenge — Quelle für GitHub-Runner unbrauchbar")
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
    if 'achtel' in n:
        return 'achtelfinale'
    if 'viertel' in n:
        return 'viertelfinale'
    if 'halb' in n:
        return 'halbfinale'
    if 'finale' in n:
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


def parse_tm_datetime(row, last_dt: Optional[datetime]) -> Optional[datetime]:
    """Datum steht oft nur in der ersten Zeile eines Tages, Uhrzeit nur bei Wechsel."""
    cells = row.find_all('td')
    date_txt = cells[0].get_text(' ', strip=True) if cells else ''
    time_txt = cells[1].get_text(' ', strip=True) if len(cells) > 1 else ''
    dm = DATE_RE.search(date_txt)
    tm = TIME_RE.search(time_txt)

    year = month = day = None
    hour, minute = 15, 0
    if last_dt:
        year, month, day = last_dt.year, last_dt.month, last_dt.day
        hour, minute = last_dt.hour, last_dt.minute

    if dm:
        day, month, year = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        if year < 100:
            year += 2000
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))
    if day is None or month is None or year is None:
        return None
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def parse_transfermarkt_html(html: str, international: bool) -> List[Dict]:
    soup = BeautifulSoup(html, 'lxml')
    matches: List[Dict] = []
    current_matchday = 1
    current_phase = 'gruppenphase' if international else None
    last_dt: Optional[datetime] = None
    seen = set()

    for el in soup.select('.content-box-headline, table tr'):
        if el.name in ('div', 'h2') or 'content-box-headline' in (el.get('class') or []):
            headline = el.get_text(' ', strip=True)
            sm = SPIELTAG_RE.search(headline)
            if sm:
                current_matchday = int(sm.group(1))
            if international:
                current_phase = phase_from_group_name(headline)
            continue
        if el.name != 'tr':
            continue

        report = el.select_one('a[href*="spielbericht"]')
        if report is None:
            continue

        team_links = [
            a for a in el.select('td.hauptlink a[title]')
            if 'spielbericht' not in (a.get('href') or '')
        ]
        home = away = ''
        if len(team_links) >= 2:
            home = (team_links[0].get('title') or team_links[0].get_text(strip=True)).strip()
            away = (team_links[-1].get('title') or team_links[-1].get_text(strip=True)).strip()
        if not home or not away:
            continue

        raw_score = report.get_text(strip=True).replace('\xa0', '')
        score = raw_score if SCORE_RE.match(raw_score) else None
        dt = parse_tm_datetime(el, last_dt)
        if dt is None:
            continue
        last_dt = dt
        date_time = to_iso_z(dt)

        key = (home, away, date_time, current_matchday)
        if key in seen:
            continue
        seen.add(key)

        now = datetime.now(timezone.utc)
        kickoff = dt.replace(tzinfo=timezone.utc)
        finished = score is not None
        is_live = (not finished) and kickoff <= now <= kickoff + timedelta(hours=3)

        rec = {
            'matchday': current_matchday,
            'homeTeam': home,
            'awayTeam': away,
            'dateTime': date_time,
            'score': score if finished and not is_live else None,
            'isFinished': finished and not is_live,
            'isLive': is_live,
            'liveScore': score if is_live else None,
        }
        if international:
            rec['phase'] = current_phase or 'gruppenphase'
        matches.append(rec)

        status_lbl = 'LIVE' if rec['isLive'] else ('BEENDET' if rec['isFinished'] else 'ZUKUNFT')
        n = len(matches)
        if n <= 6 or n % 50 == 0:
            log(
                f"     ✓ {status_lbl}: {home} vs {away} | {date_time} | {raw_score} | "
                f"festgemacht an Transfermarkt-Zeile Spieltag {current_matchday} + "
                f"a[href*=spielbericht] | {report.get('href')}"
            )
    return matches


def scrape_transfermarkt(league: str, kind: str, code: str, international: bool) -> List[Dict]:
    season = get_openligadb_season()
    url = (
        f'https://www.transfermarkt.de/{league}/gesamtspielplan/'
        f'{kind}/{code}/saison_id/{season}'
    )
    log(f"   Quelle: Transfermarkt Gesamtspielplan | saison_id={season}")
    log("   Spiel = Tabellenzeile mit a[href*=spielbericht]; Teams = a[title] in td.hauptlink; "
        "Ergebnis = Linktext 4:1 bzw. -:- ; Datum/Uhrzeit in den ersten TDs; "
        "Spieltag = vorherige Überschrift 'n. Spieltag'")

    status, body, final = http_get(url, accept='text/html')
    if status != 200 or not body or 'Just a moment' in body:
        log(f"  ⛔ Transfermarkt lieferte keine Seite für {league}")
        return []
    if 'Nicht gefunden' in body or 'Page not found' in body:
        log("  ⛔ Transfermarkt 404")
        return []

    matches = parse_transfermarkt_html(body, international)
    log(f"  ✅ {league} via Transfermarkt: {len(matches)} Spiele")
    return matches


def scrape_league(league: str) -> List[Dict]:
    """
    england/spain/CL/EL: OpenLigaDB (läuft auf GitHub).
    italy/france/ECL: Transfermarkt (kein Cloudflare-JS).
    """
    configs = {
        'england': {'oldb': ['pl', 'epl', 'pl1']},
        'spain': {'oldb': ['la1']},
        'italy': {'tm': ('wettbewerb', 'IT1')},
        'france': {'tm': ('wettbewerb', 'FR1')},
        'championsleague': {'oldb': ['ucl', f"ucl{get_openligadb_season()}"], 'international': True},
        'europaleague': {'oldb': [f"uel{get_openligadb_season()}", 'uel'], 'international': True},
        'conferenceleague': {'tm': ('pokalwettbewerb', 'UCOL'), 'international': True},
    }
    cfg = configs[league]
    international = bool(cfg.get('international'))
    if 'oldb' in cfg:
        return scrape_openligadb(league, cfg['oldb'], international)
    kind, code = cfg['tm']
    return scrape_transfermarkt(league, kind, code, international)


def save_matches_json(league: str, season: str, matches: List[Dict], output_dir: str = 'data/matches'):
    os.makedirs(output_dir, exist_ok=True)
    output_data = {
        'league': league,
        'season': season,
        'lastUpdated': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'matches': matches,
        'source': 'openligadb-or-transfermarkt',
    }
    filename = f"{output_dir}/matches_{league}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    log(f"💾 Gespeichert: {filename} ({len(matches)} Matches)")


def save_matches_json_array(league: str, season: str, matches: List[Dict], output_dir: str = 'data/matches'):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/matches_{league}.json"
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
        "  OpenLigaDB JSON  — england (pl), spain (la1), championsleague (ucl), europaleague (uelYYYY)\n"
        "  Transfermarkt    — italy (IT1), france (FR1), conferenceleague (UCOL)\n"
        "  fussballdaten.de wird NICHT mehr verwendet (Cloudflare 403 auf Actions-Runnern)\n"
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
