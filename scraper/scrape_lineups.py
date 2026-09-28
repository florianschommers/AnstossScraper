#!/usr/bin/env python3
"""
Aufstellungen für Anstoss — unbeaufsichtigt auf GitHub Actions.

Quellen: Livescore JSON (Ligen) und UEFA Match API (CL/EL/ECL).
Nur Spiele im Zeitfenster (Standard: letzte 30 Min bis +6 Stunden).
Bestehende lineups_*.json werden gemerged, leere Startelfs überschreiben nichts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

HEADERS = {
    'User-Agent': (
        'AnstossScraper/1.0 (+https://github.com/florianschommers/AnstossScraper) '
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
}

POS_MAP = {
    'goalkeeper': 'Torwart',
    'gk': 'Torwart',
    'defender': 'Abwehr',
    'df': 'Abwehr',
    'midfielder': 'Mittelfeld',
    'mf': 'Mittelfeld',
    'forward': 'Angriff',
    'attacker': 'Angriff',
    'fw': 'Angriff',
    'winger': 'Angriff',
}

STOP = {
    'fc', 'cf', 'ac', 'afc', 'cfc', 'sc', 'sv', 'tsg', 'rc', 'us', 'as', 'ssc',
    'the', 'de', 'calcio', 'club', 'united', 'hotspur', 'wanderers', '04',
    '1909', '1907', '1893', '1913', '1', '1.',
}

LIVESCORE_LEAGUES = {
    'bundesliga': ('germany', 'bundesliga', 'Europe/Berlin'),
    '2bundesliga': ('germany', '2-bundesliga', 'Europe/Berlin'),
    'dfbpokal': ('germany', 'dfb-cup', 'Europe/Berlin'),
    'england': ('england', 'premier-league', 'Europe/London'),
    'spain': ('spain', 'laliga', 'Europe/Madrid'),
    'italy': ('italy', 'serie-a', 'Europe/Rome'),
    'france': ('france', 'ligue-1', 'Europe/Paris'),
    'friendlies': ('international-friendlies', 'friendlies', 'Europe/Berlin', 'de'),
}

# id, Saisonjahre (None = Anzeige-Saison), phase: tournament | qualifying | all
UEFA_LEAGUES = {
    'championsleague': ('1', None, 'tournament'),
    'europaleague': ('14', None, 'tournament'),
    'conferenceleague': ('2019', None, 'tournament'),
    'nationsleague': ('2014', None, 'all'),
    'euro': ('3', ('2028', '2024'), 'tournament'),
    'euroqualifying': ('3', ('2028', '2024'), 'qualifying'),
    'worldcup': ('17', ('2026',), 'tournament'),
    'worldcupqualifying': ('17', ('2026',), 'qualifying'),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def get_openligadb_season() -> str:
    now = datetime.now()
    if now.month >= 7:
        return str(now.year)
    return str(now.year - 1)


def get_display_season() -> str:
    return str(int(get_openligadb_season()) + 1)


def europe_naive_to_utc(dt_naive: datetime, zone_name: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt_naive.replace(tzinfo=ZoneInfo(zone_name)).astimezone(timezone.utc)
    except Exception:
        month = dt_naive.month
        offset = 1 if zone_name == 'Europe/London' else (2 if 3 <= month <= 10 else 1)
        return (dt_naive - timedelta(hours=offset)).replace(tzinfo=timezone.utc)


def http_get(url: str) -> Tuple[int, str]:
    log(f"  🌐 GET {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=45)
        log(f"     HTTP {response.status_code} | {len(response.content or b'')} Bytes")
        return response.status_code, response.text or ''
    except Exception as e:
        log(f"     ❌ {e}")
        return 0, ''


def strip_accents(text: str) -> str:
    nfd = unicodedata.normalize('NFD', text or '')
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')


def norm_team(name: str) -> str:
    s = strip_accents(name or '').lower()
    s = s.replace('ß', 'ss').replace('.', ' ').replace('-', ' ').replace("'", ' ')
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)
    parts = [p for p in s.split() if p and p not in STOP]
    return ' '.join(parts)


def team_score(a: str, b: str) -> float:
    na, nb = norm_team(a), norm_team(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    if na in nb or nb in na:
        return 85.0
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if not inter:
        return 0.0
    return 100.0 * len(inter) / max(len(ta), len(tb))


def map_position(raw: str) -> str:
    key = (raw or '').strip().lower()
    return POS_MAP.get(key, 'Mittelfeld')


def parse_iso_utc(value: str) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).replace('+00:00', 'Z')
    if s.endswith('Z') and '.' in s:
        s = s.split('.')[0] + 'Z'
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_livescore_esd(esd, zone_name: str) -> Optional[datetime]:
    digits = re.sub(r'\D', '', str(esd or ''))
    if len(digits) < 12:
        return None
    digits = digits[:14].ljust(14, '0')
    try:
        local = datetime.strptime(digits, '%Y%m%d%H%M%S')
    except ValueError:
        return None
    return europe_naive_to_utc(local, zone_name)


def flatten_match(raw: dict) -> Optional[Dict]:
    if isinstance(raw.get('homeTeam'), str) and isinstance(raw.get('awayTeam'), str):
        home, away = raw['homeTeam'], raw['awayTeam']
        date_time = raw.get('dateTime') or ''
        matchday = raw.get('matchday')
        phase = raw.get('phase') or ''
    else:
        t1 = raw.get('team1') or raw.get('Team1') or {}
        t2 = raw.get('team2') or raw.get('Team2') or {}
        if not isinstance(t1, dict) or not isinstance(t2, dict):
            return None
        home = t1.get('teamName') or t1.get('TeamName') or ''
        away = t2.get('teamName') or t2.get('TeamName') or ''
        date_time = raw.get('matchDateTimeUTC') or raw.get('MatchDateTimeUTC') or raw.get('dateTime') or ''
        group = raw.get('group') or raw.get('Group') or {}
        matchday = None
        phase = ''
        if isinstance(group, dict):
            matchday = group.get('groupOrderID') or group.get('GroupOrderID')
            phase = group.get('groupName') or group.get('GroupName') or ''
        if matchday is None:
            matchday = raw.get('matchday') or raw.get('Matchday')
        if not phase:
            phase = raw.get('phase') or ''
    if not home or not away:
        return None
    kickoff = parse_iso_utc(str(date_time))
    if kickoff is None:
        return None
    try:
        matchday_i = int(matchday) if matchday is not None and str(matchday).isdigit() else matchday
    except (TypeError, ValueError):
        matchday_i = matchday
    return {
        'homeTeam': home,
        'awayTeam': away,
        'dateTime': kickoff.replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'matchday': matchday_i if matchday_i is not None else 1,
        'phase': phase if isinstance(phase, str) else '',
        'kickoff': kickoff,
    }


def load_matches(league: str) -> List[Dict]:
    path = os.path.join('data', 'matches', f'matches_{league}.json')
    if not os.path.isfile(path):
        log(f"  ⚠️ Match-Datei fehlt: {path}")
        return []
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    raw_list = data.get('matches') if isinstance(data, dict) else data
    if not isinstance(raw_list, list):
        return []
    out = []
    for raw in raw_list:
        rec = flatten_match(raw) if isinstance(raw, dict) else None
        if rec:
            out.append(rec)
    return out


def in_window(kickoff: datetime, now: datetime, ahead: timedelta, back: timedelta) -> bool:
    return (now - back) <= kickoff <= (now + ahead)


def load_existing_lineups(league: str, season: str) -> Dict:
    path = os.path.join('data', 'lineups', f'lineups_{league}.json')
    if not os.path.isfile(path):
        return {'league': league, 'season': season, 'lastUpdated': '', 'lineups': []}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('lineups'), list):
            data.setdefault('league', league)
            data.setdefault('season', season)
            return data
    except Exception as e:
        log(f"  ⚠️ Alte Lineup-Datei unlesbar: {e}")
    return {'league': league, 'season': season, 'lastUpdated': '', 'lineups': []}


def lineup_quality(players: List) -> int:
    if not isinstance(players, list):
        return 0
    n = 0
    for p in players:
        if isinstance(p, str) and p.strip():
            n += 1
        elif isinstance(p, dict) and (p.get('name') or '').strip():
            n += 1
    return n


def upsert_lineup(store: Dict, rec: Dict) -> bool:
    """True wenn geschrieben/ersetzt."""
    key_home, key_away = norm_team(rec['homeTeam']), norm_team(rec['awayTeam'])
    new_q = lineup_quality(rec.get('homeLineup')) + lineup_quality(rec.get('awayLineup'))
    if new_q < 22:
        return False
    lineups = store['lineups']
    for i, old in enumerate(lineups):
        if norm_team(old.get('homeTeam', '')) != key_home:
            continue
        if norm_team(old.get('awayTeam', '')) != key_away:
            continue
        same_md = str(old.get('matchday', '')) == str(rec.get('matchday', ''))
        same_dt = (old.get('dateTime') or '')[:16] == (rec.get('dateTime') or '')[:16]
        if same_md or same_dt:
            old_q = lineup_quality(old.get('homeLineup')) + lineup_quality(old.get('awayLineup'))
            if new_q >= old_q:
                lineups[i] = rec
                return True
            log("     ↷ Bestehende vollständige Aufstellung behalten")
            return False
    lineups.append(rec)
    return True


def livescore_players(side: dict) -> List[Dict[str, str]]:
    out = []
    for p in side.get('Ps') or []:
        if str(p.get('Pon') or '').upper() == 'COACH':
            continue
        if not p.get('Fp'):
            continue
        name = f"{p.get('Fn') or ''} {p.get('Ln') or ''}".strip()
        if not name:
            continue
        out.append({'name': name, 'position': map_position(str(p.get('Pon') or ''))})
    return out[:11]


def fetch_livescore_events(country: str, slug: str, zone_name: str, locale: Optional[str] = None) -> List[Dict]:
    url = f'https://prod-cdn-public-api.livescore.com/v1/api/app/stage/soccer/{country}/{slug}/1'
    if locale:
        url += f'?locale={locale}'
    status, body = http_get(url)
    if status != 200:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    events = []
    for st in data.get('Stages') or []:
        for ev in st.get('Events') or []:
            kick = parse_livescore_esd(ev.get('Esd'), zone_name)
            if kick is None:
                continue
            home = ((ev.get('T1') or [{}])[0] or {}).get('Nm') or ''
            away = ((ev.get('T2') or [{}])[0] or {}).get('Nm') or ''
            events.append({
                'eid': str(ev.get('Eid') or ''),
                'home': home,
                'away': away,
                'kickoff': kick,
            })
    return events


def fetch_livescore_lineup(eid: str) -> Optional[Tuple[List[Dict[str, str]], List[Dict[str, str]]]]:
    url = f'https://prod-cdn-public-api.livescore.com/v1/api/app/lineups/soccer/{eid}'
    status, body = http_get(url)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    home_ps: List[Dict[str, str]] = []
    away_ps: List[Dict[str, str]] = []
    for side in data.get('Lu') or []:
        players = livescore_players(side)
        tnb = side.get('Tnb')
        if tnb == 1:
            home_ps = players
        elif tnb == 2:
            away_ps = players
    if len(home_ps) < 11 or len(away_ps) < 11:
        log(f"     ℹ️ Noch keine Startelf (Heim {len(home_ps)}, Gast {len(away_ps)})")
        return None
    return home_ps, away_ps


def match_event(match: Dict, events: List[Dict]) -> Optional[Dict]:
    best = None
    best_score = 0.0
    for ev in events:
        if not ev.get('eid'):
            continue
        delta = abs((ev['kickoff'] - match['kickoff']).total_seconds())
        if delta > 3 * 3600:
            continue
        hs = team_score(match['homeTeam'], ev['home'])
        aws = team_score(match['awayTeam'], ev['away'])
        score = hs + aws - delta / 3600.0
        if hs >= 50 and aws >= 50 and score > best_score:
            best_score = score
            best = ev
    return best


def uefa_player(entry: dict) -> Optional[Dict[str, str]]:
    p = entry.get('player') or {}
    trans = p.get('translations') or {}
    name = ''
    for bag_key in ('name', 'officialName', 'shortName'):
        bag = trans.get(bag_key)
        if isinstance(bag, dict):
            name = bag.get('DE') or bag.get('EN') or name
            if name:
                break
    name = name or p.get('internationalName') or p.get('clubShirtName') or ''
    name = str(name).strip()
    if not name:
        return None
    pos = map_position(str(p.get('fieldPosition') or ''))
    return {'name': name, 'position': pos}


def fetch_uefa_window(competition_id: str, season_year: str, now: datetime, ahead: timedelta, back: timedelta,
                       phase_mode: str = 'tournament') -> List[Dict]:
    found = []
    offset = 0
    while offset < 500:
        url = (
            f'https://match.uefa.com/v5/matches?competitionId={competition_id}'
            f'&seasonYear={season_year}&limit=100&offset={offset}'
        )
        status, body = http_get(url)
        if status != 200:
            break
        try:
            chunk = json.loads(body)
        except json.JSONDecodeError:
            break
        if not isinstance(chunk, list) or not chunk:
            break
        for raw in chunk:
            rnd = raw.get('round') or {}
            phase = str(rnd.get('phase') or '').upper()
            if phase_mode == 'tournament' and phase == 'QUALIFYING':
                continue
            if phase_mode == 'qualifying' and phase != 'QUALIFYING':
                continue
            kick = parse_iso_utc((raw.get('kickOffTime') or {}).get('dateTime') or '')
            if kick is None or not in_window(kick, now, ahead, back):
                continue
            home = (raw.get('homeTeam') or {}).get('internationalName') or ''
            away = (raw.get('awayTeam') or {}).get('internationalName') or ''
            found.append({
                'id': str(raw.get('id') or ''),
                'home': home,
                'away': away,
                'kickoff': kick,
                'status': raw.get('status'),
                'lineupStatus': raw.get('lineupStatus'),
            })
        if len(chunk) < 100:
            break
        offset += 100
    return found


def fetch_uefa_lineup(match_id: str) -> Optional[Tuple[List[Dict[str, str]], List[Dict[str, str]]]]:
    url = f'https://match.uefa.com/v5/matches/{match_id}/lineups'
    status, body = http_get(url)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if str(data.get('lineupStatus') or '').upper() in ('NOT_AVAILABLE', ''):
        log(f"     ℹ️ UEFA lineupStatus={data.get('lineupStatus')}")
        return None
    def side(key: str) -> List[Dict[str, str]]:
        players = []
        for entry in (data.get(key) or {}).get('field') or []:
            rec = uefa_player(entry)
            if rec:
                players.append(rec)
        return players[:11]
    home, away = side('homeTeam'), side('awayTeam')
    if len(home) < 11 or len(away) < 11:
        log(f"     ℹ️ UEFA Feld unvollständig Heim {len(home)} Gast {len(away)}")
        return None
    return home, away


def scrape_livescore_league(league: str, country: str, slug: str, zone: str,
                            window_matches: List[Dict], store: Dict, locale: Optional[str] = None) -> int:
    if not window_matches:
        log("  ⏭️ Keine Spiele im Zeitfenster")
        return 0
    events = fetch_livescore_events(country, slug, zone, locale)
    log(f"  Livescore {country}/{slug}: {len(events)} Events in der Saison")
    added = 0
    for match in window_matches:
        ev = match_event(match, events)
        if not ev:
            log(f"  ⚠️ Kein Livescore-Event: {match['homeTeam']} vs {match['awayTeam']}")
            continue
        log(f"  → {match['homeTeam']} vs {match['awayTeam']} eid={ev['eid']}")
        lu = fetch_livescore_lineup(ev['eid'])
        if not lu:
            continue
        rec = {
            'homeTeam': match['homeTeam'],
            'awayTeam': match['awayTeam'],
            'dateTime': match['dateTime'],
            'matchday': match['matchday'],
            'phase': match.get('phase') or '',
            'homeLineup': lu[0],
            'awayLineup': lu[1],
        }
        if upsert_lineup(store, rec):
            added += 1
            log(f"     ✅ Startelf 11/11 gespeichert")
    return added


def scrape_uefa_league(league: str, competition_id: str, window_matches: List[Dict], store: Dict,
                       now: datetime, ahead: timedelta, back: timedelta,
                       season_years: Optional[Tuple[str, ...]] = None,
                       phase_mode: str = 'tournament') -> int:
    if not window_matches:
        log("  ⏭️ Keine Spiele im Zeitfenster")
        return 0
    years = list(season_years) if season_years else [get_display_season()]
    uefa_matches: List[Dict] = []
    for season_year in years:
        found = fetch_uefa_window(competition_id, season_year, now, ahead, back, phase_mode)
        log(f"  UEFA competition {competition_id} Saison {season_year}: {len(found)} Spiele im Fenster")
        uefa_matches.extend(found)
    added = 0
    for match in window_matches:
        best = None
        best_score = 0.0
        for um in uefa_matches:
            if not um.get('id'):
                continue
            delta = abs((um['kickoff'] - match['kickoff']).total_seconds())
            if delta > 3 * 3600:
                continue
            hs = team_score(match['homeTeam'], um['home'])
            aws = team_score(match['awayTeam'], um['away'])
            score = hs + aws
            if hs >= 45 and aws >= 45 and score > best_score:
                best_score = score
                best = um
        if not best:
            log(f"  ⚠️ Kein UEFA-Match: {match['homeTeam']} vs {match['awayTeam']}")
            continue
        log(f"  → {match['homeTeam']} vs {match['awayTeam']} uefa={best['id']} status={best.get('lineupStatus')}")
        lu = fetch_uefa_lineup(best['id'])
        if not lu:
            continue
        rec = {
            'homeTeam': match['homeTeam'],
            'awayTeam': match['awayTeam'],
            'dateTime': match['dateTime'],
            'matchday': match['matchday'],
            'phase': match.get('phase') or 'gruppenphase',
            'homeLineup': lu[0],
            'awayLineup': lu[1],
        }
        if upsert_lineup(store, rec):
            added += 1
            log("     ✅ UEFA-Startelf gespeichert")
    return added


def save_store(league: str, store: Dict) -> None:
    out_dir = os.path.join('data', 'lineups')
    os.makedirs(out_dir, exist_ok=True)
    store['lastUpdated'] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    store['season'] = store.get('season') or get_display_season()
    path = os.path.join(out_dir, f'lineups_{league}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    log(f"💾 {path} ({len(store['lineups'])} Aufstellungen gesamt)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--window-hours', type=float, default=6.0)
    parser.add_argument('--lookback-minutes', type=float, default=30.0)
    args = parser.parse_args()
    if os.path.basename(os.getcwd()) == 'scraper':
        os.chdir('..')
    ahead = timedelta(hours=args.window_hours)
    back = timedelta(minutes=args.lookback_minutes)
    now = datetime.now(timezone.utc)
    season = get_display_season()

    log("🚀 Lineup-Update (Livescore + UEFA, kein fussballdaten.de)")
    log(f"   Fenster: -{int(back.total_seconds()//60)} Min bis +{args.window_hours:g} h | jetzt {now.isoformat()}")
    log("   Cron zielt auf Anstoß-Cluster (~15 Läufe/Woche), dieser Lauf holt nur fällige Spiele.\n")

    order = [
        'bundesliga', '2bundesliga', 'dfbpokal',
        'england', 'spain', 'italy', 'france',
        'championsleague', 'europaleague', 'conferenceleague',
        'nationsleague', 'friendlies', 'euro', 'worldcup',
        'euroqualifying', 'worldcupqualifying',
    ]
    total_new = 0
    for league in order:
        log(f"\n📊 {league}")
        matches = load_matches(league)
        window = [m for m in matches if in_window(m['kickoff'], now, ahead, back)]
        log(f"   {len(matches)} Spiele in JSON, {len(window)} im Fenster")
        store = load_existing_lineups(league, season)
        before = json.dumps(store.get('lineups'), ensure_ascii=False, sort_keys=True)
        if league in LIVESCORE_LEAGUES:
            entry = LIVESCORE_LEAGUES[league]
            country, slug, zone = entry[0], entry[1], entry[2]
            locale = entry[3] if len(entry) > 3 else None
            added = scrape_livescore_league(league, country, slug, zone, window, store, locale)
        else:
            competition_id, season_years, phase_mode = UEFA_LEAGUES[league]
            added = scrape_uefa_league(
                league, competition_id, window, store, now, ahead, back,
                season_years, phase_mode,
            )
        after = json.dumps(store.get('lineups'), ensure_ascii=False, sort_keys=True)
        if added or before != after:
            save_store(league, store)
            total_new += added
        elif window:
            log("  ℹ️ Fenster-Spiele ohne neue Startelf — Datei unverändert")
        else:
            log("  ⏭️ nichts zu tun")

    log(f"\n✅ Fertig. Neue/aktualisierte Aufstellungen in diesem Lauf: {total_new}")


if __name__ == '__main__':
    main()
