#!/usr/bin/env python3
"""
Match-Scraper für Anstoss App
Scrapt Match-Daten von fussballdaten.de und speichert sie als JSON.
"""

import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    'Referer': 'https://www.fussballdaten.de/',
}

TEAM_MAPPINGS = {
    'england': {
        'manchester-city': 'Manchester City',
        'mancity': 'Manchester City',
        'man.city': 'Manchester City',
        'arsenal': 'Arsenal',
        'liverpool': 'Liverpool',
        'chelsea': 'Chelsea',
        'manchester-united': 'Manchester United',
        'man.united': 'Manchester United',
        'tottenham': 'Tottenham Hotspur',
        'brighton': 'Brighton & Hove Albion',
        'west-ham-united': 'West Ham United',
        'westham': 'West Ham United',
        'aston-villa': 'Aston Villa',
        'crystal-palace': 'Crystal Palace',
        'fulham': 'Fulham',
        'wolves': 'Wolverhampton Wanderers',
        'everton': 'Everton',
        'brentford': 'Brentford',
        'nottingham-forest': 'Nottingham Forest',
        'luton-town': 'Luton Town',
        'burnley': 'Burnley',
        'sheffield-united': 'Sheffield United',
        'ipswich-town': 'Ipswich Town',
        'leicester-city': 'Leicester City',
        'southampton': 'Southampton',
        'leeds-united': 'Leeds United',
        'leeds': 'Leeds United',
        'norwich-city': 'Norwich City',
        'watford': 'Watford',
        'afc-bournemouth': 'AFC Bournemouth',
        'bournemouth': 'AFC Bournemouth',
    },
    'spain': {},
    'italy': {},
    'france': {},
}

LEAGUE_PATHS = {
    'england': 'england',
    'spain': 'spanien',
    'italy': 'italien',
    'france': 'frankreich',
    'bundesliga1': 'bundesliga',
    'bundesliga2': '2liga',
}

INT_LEAGUE_PATHS = {
    'championsleague': 'championsleague',
    'europaleague': 'europaleague',
    'conferenceleague': 'conferenceleague',
}

INT_PHASES = [
    'gruppenphase',
    'league-stage',
    'play-offs',
    'achtelfinale',
    'viertelfinale',
    'halbfinale',
    'finale',
]
PHASES_WITH_MATCHDAYS = {'gruppenphase', 'league-stage'}

TITLE_TEAMS_RE = re.compile(r'^\s*(.+?)\s+-\s+(.+?)\s+\|')
TITLE_DATE_RE = re.compile(r'(\d{2})\.(\d{2})\.(\d{4})')
TIME_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')
SCORE_RE = re.compile(r'^(\d{1,2}):(\d{1,2})$')
MATCH_HREF_RE = re.compile(
    r'^/[a-z0-9-]+/\d{4}/(?:[a-z0-9-]+/)*[a-z][a-z0-9.-]*-[a-z0-9.-]+/?$',
    re.IGNORECASE,
)
LIVE_CLASSES = {'live', 'is-live', 'has-live'}


def log(msg: str) -> None:
    print(msg, flush=True)


def get_current_season() -> str:
    """fussballdaten.de nutzt das Endjahr: 2027 = Saison 2026/27."""
    now = datetime.now()
    if now.month >= 7:
        return str(now.year + 1)
    return str(now.year)


def get_international_season() -> str:
    return get_current_season()


def normalize_team_slug(slug: str, league: str) -> str:
    slug_lower = slug.lower().strip()
    if league in TEAM_MAPPINGS and slug_lower in TEAM_MAPPINGS[league]:
        return TEAM_MAPPINGS[league][slug_lower]
    return slug.replace('.', '-').replace('-', ' ').title()


def parse_team_from_slug(slug: str, league: str) -> Tuple[str, str]:
    parts = slug.split('-')
    if len(parts) >= 2:
        home_slug = parts[0]
        away_slug = '-'.join(parts[1:])
        return normalize_team_slug(home_slug, league), normalize_team_slug(away_slug, league)
    return '', ''


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, 'lxml')
    except Exception:
        return BeautifulSoup(html, 'html.parser')


def fetch_html(url: str) -> Optional[str]:
    log(f"  🌐 GET {url}")
    try:
        time.sleep(0.2)
        response = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        size = len(response.content or b'')
        final = response.url if response.url != url else ''
        extra = f" | redirect→ {final}" if final else ''
        log(f"     HTTP {response.status_code} | {size} Bytes{extra}")

        if response.status_code != 200:
            snippet = re.sub(r'\s+', ' ', (response.text or '')[:180]).strip()
            if snippet:
                log(f"     Body: {snippet}")
            return None

        text = response.text or ''
        if 'Not Found (#404)' in text:
            log("     ⚠️ HTML ist eine 404-Seite (Status 200)")
            return None
        if len(text) < 1000:
            log(f"     ⚠️ HTML zu kurz ({len(text)} Zeichen) — ignoriere Seite")
            return None

        title_m = re.search(r'<title>([^<]{0,160})</title>', text, re.IGNORECASE)
        if title_m:
            log(f"     <title> {title_m.group(1).strip()}")
        return text
    except Exception as e:
        log(f"     ❌ Request-Fehler: {e}")
        return None


def parse_title_meta(title: str) -> Tuple[Optional[str], Optional[str], Optional[datetime]]:
    """title='FC Arsenal - Coventry City | 21.08.2026 | Premier League | 1. Spieltag'"""
    if not title:
        return None, None, None
    home = away = None
    teams = TITLE_TEAMS_RE.match(title)
    if teams:
        home, away = teams.group(1).strip(), teams.group(2).strip()
    date = None
    dm = TITLE_DATE_RE.search(title)
    if dm:
        try:
            date = datetime(int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
        except ValueError:
            date = None
    return home, away, date


def to_iso_z(dt: datetime) -> str:
    """Naive lokale Anstoßzeit, mit Z-Suffix wie bisher für die App."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    return dt.replace(microsecond=0).isoformat() + 'Z'


def class_list(el) -> List[str]:
    if el is None:
        return []
    raw = el.get('class') or []
    if isinstance(raw, str):
        return raw.split()
    return list(raw)


def text_or_title(el) -> str:
    if el is None:
        return ''
    return (el.get('title') or el.get_text(' ', strip=True) or '').strip()


def score_from_v2_link(result_a) -> Optional[str]:
    if result_a is None:
        return None
    home_el = result_a.select_one('.srv2-score-h')
    away_el = result_a.select_one('.srv2-score-g')
    if home_el and away_el:
        hs, gs = home_el.get_text(strip=True), away_el.get_text(strip=True)
        if hs.isdigit() and gs.isdigit():
            return f'{hs}:{gs}'
    joined = re.sub(r'\s+', '', result_a.get_text())
    m = SCORE_RE.search(joined)
    if m:
        return m.group(0)
    return None


def first_span_text(anchor) -> str:
    if anchor is None:
        return ''
    span = anchor.find('span')
    if span:
        return span.get_text(strip=True)
    return anchor.get_text(strip=True)


def classify_status(classes: List[str], score: Optional[str], time_str: Optional[str]) -> str:
    lowered = {c.lower() for c in classes}
    if lowered & LIVE_CLASSES:
        return 'live'
    if 'has-result' in lowered or ('ergebnis' in lowered and 'live' not in lowered):
        return 'finished'
    if 'is-upcoming' in lowered:
        return 'upcoming'
    if score and not time_str:
        return 'finished'
    if time_str:
        return 'upcoming'
    if score:
        return 'finished'
    return 'upcoming'


def diagnose_markers(soup: BeautifulSoup) -> Dict[str, int]:
    counts = {
        'spiel-row-v2': len(soup.select('div.spiel-row-v2')),
        'spiele-row': len(soup.select('div.spiele-row')),
        'a.srv2-ergebnis': len(soup.select('a.srv2-ergebnis')),
        'a.ergebnis': len(soup.select('a.ergebnis')),
        'a.srv2-ergebnis.has-result': len(soup.select('a.srv2-ergebnis.has-result')),
        'a.srv2-ergebnis.is-upcoming': len(soup.select('a.srv2-ergebnis.is-upcoming')),
    }
    log(
        "     Marker: "
        f"spiel-row-v2={counts['spiel-row-v2']} | "
        f"spiele-row={counts['spiele-row']} | "
        f"a.srv2-ergebnis={counts['a.srv2-ergebnis']} "
        f"(has-result={counts['a.srv2-ergebnis.has-result']}, "
        f"is-upcoming={counts['a.srv2-ergebnis.is-upcoming']}) | "
        f"a.ergebnis={counts['a.ergebnis']}"
    )
    return counts


def build_match(
    *,
    matchday: Optional[int],
    home: str,
    away: str,
    status: str,
    score: Optional[str],
    match_date: Optional[datetime],
    time_str: Optional[str],
    phase: Optional[str],
) -> Dict:
    hour, minute = 15, 0
    if time_str and TIME_RE.match(time_str):
        hour, minute = map(int, time_str.split(':'))

    if status == 'live':
        date_time = to_iso_z(datetime.now(timezone.utc))
        rec = {
            'matchday': matchday,
            'homeTeam': home,
            'awayTeam': away,
            'dateTime': date_time,
            'score': None,
            'isFinished': False,
            'isLive': True,
            'liveScore': score,
        }
    elif status == 'finished':
        if match_date:
            dt = match_date.replace(hour=hour, minute=minute)
        else:
            dt = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        rec = {
            'matchday': matchday,
            'homeTeam': home,
            'awayTeam': away,
            'dateTime': to_iso_z(dt),
            'score': score,
            'isFinished': True,
            'isLive': False,
            'liveScore': None,
        }
    else:
        if match_date:
            dt = match_date.replace(hour=hour, minute=minute)
        else:
            dt = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        rec = {
            'matchday': matchday,
            'homeTeam': home,
            'awayTeam': away,
            'dateTime': to_iso_z(dt),
            'score': None,
            'isFinished': False,
            'isLive': False,
            'liveScore': None,
        }
    if phase:
        rec['phase'] = phase
    return rec


def parse_v2_matches(
    soup: BeautifulSoup,
    matchday: Optional[int],
    league: str,
    phase: Optional[str] = None,
) -> List[Dict]:
    rows = soup.select('div.spiel-row-v2')
    log(
        f"     Parser: spiel-row-v2 ({len(rows)} Zeilen) — "
        "Spiel = <div class='spiel-row-v2'>; "
        "Teams = a.srv2-team-name in .srv2-heim / .srv2-gast; "
        "Status = Klassen auf a.srv2-ergebnis "
        "(has-result=beendet, is-upcoming=zukünftig, live/is-live=live); "
        "Ergebnis = span.srv2-score-h + ':' + span.srv2-score-g; "
        "Datum = title '... | TT.MM.JJJJ | ...'; "
        "Uhrzeit = span.srv2-zeit-time"
    )
    matches: List[Dict] = []
    for i, row in enumerate(rows, 1):
        heim = row.select_one('.srv2-heim a.srv2-team-name')
        gast = row.select_one('.srv2-gast a.srv2-team-name')
        result_a = row.select_one('a.srv2-ergebnis')
        title = (result_a.get('title') if result_a else '') or ''
        classes = class_list(result_a)
        href = (result_a.get('href') if result_a else '') or ''

        home = text_or_title(heim)
        away = text_or_title(gast)
        title_home, title_away, match_date = parse_title_meta(title)
        home = home or title_home or ''
        away = away or title_away or ''
        if (not home or not away) and href:
            slug = href.rstrip('/').split('/')[-1]
            slug_home, slug_away = parse_team_from_slug(slug, league)
            home = home or slug_home
            away = away or slug_away

        score = score_from_v2_link(result_a)
        time_el = row.select_one('.srv2-zeit-time')
        time_str = time_el.get_text(strip=True) if time_el else None
        if time_str and not TIME_RE.match(time_str):
            time_str = None

        if not home or not away:
            log(
                f"     ↷ Zeile {i}: kein Spiel — Teams fehlen "
                f"(class={ ' '.join(classes)!r}, title={title[:90]!r}, href={href})"
            )
            continue

        status = classify_status(classes, score, time_str)
        rec = build_match(
            matchday=matchday,
            home=home,
            away=away,
            status=status,
            score=score,
            match_date=match_date,
            time_str=time_str,
            phase=phase,
        )
        label = {'live': 'LIVE', 'finished': 'BEENDET', 'upcoming': 'ZUKUNFT'}[status]
        score_txt = score or time_str or '-'
        log(
            f"     ✓ {label}: {home} vs {away} | {rec['dateTime']} | {score_txt} | "
            f"festgemacht an class='{' '.join(classes)}' + title-Datum | {href}"
        )
        matches.append(rec)
    return matches


def parse_legacy_matches(
    soup: BeautifulSoup,
    matchday: Optional[int],
    league: str,
    phase: Optional[str] = None,
) -> List[Dict]:
    rows = soup.select('div.spiele-row')
    log(
        f"     Parser: spiele-row ({len(rows)} Zeilen) — "
        "Spiel = <div class='spiele-row'>; "
        "Begegnung = mittleres <a href='/{liga}/.../heim-gast/'>; "
        "Teams = title 'Heim - Gast | TT.MM.JJJJ'; "
        "LIVE = class enthält 'live'; "
        "BEENDET = class enthält 'ergebnis' und Span '1:0'; "
        "ZUKUNFT = Span '18:45' ohne ergebnis-Klasse"
    )
    matches: List[Dict] = []
    for i, row in enumerate(rows, 1):
        result_a = None
        for anchor in row.find_all('a', href=True):
            href = anchor.get('href') or ''
            if MATCH_HREF_RE.match(href):
                result_a = anchor
                break
        if result_a is None:
            log(f"     ↷ Zeile {i}: kein Spiel-Link (href mit heim-gast)")
            continue

        href = result_a.get('href') or ''
        title = result_a.get('title') or ''
        classes = class_list(result_a)
        home, away, match_date = parse_title_meta(title)
        if not home or not away:
            slug = href.rstrip('/').split('/')[-1]
            home, away = parse_team_from_slug(slug, league)

        span_txt = first_span_text(result_a)
        score = span_txt if SCORE_RE.match(span_txt or '') else None
        time_str = span_txt if TIME_RE.match(span_txt or '') else None
        # 3:0 ist Score; 18:45 ist Uhrzeit. SCORE_RE matched beides (18:45 → 18 und 45).
        if score and TIME_RE.match(score):
            hour = int(score.split(':')[0])
            if hour >= 10:
                time_str = score
                score = None

        if not home or not away:
            log(
                f"     ↷ Zeile {i}: Teams fehlen "
                f"(class={' '.join(classes)!r}, title={title[:90]!r}, href={href})"
            )
            continue

        status = classify_status(classes, score, time_str)
        rec = build_match(
            matchday=matchday,
            home=home,
            away=away,
            status=status,
            score=score,
            match_date=match_date,
            time_str=time_str,
            phase=phase,
        )
        label = {'live': 'LIVE', 'finished': 'BEENDET', 'upcoming': 'ZUKUNFT'}[status]
        score_txt = score or time_str or '-'
        log(
            f"     ✓ {label}: {home} vs {away} | {rec['dateTime']} | {score_txt} | "
            f"festgemacht an class='{' '.join(classes)}' + title-Datum | {href}"
        )
        matches.append(rec)
    return matches


def parse_matches_html(
    html: str,
    matchday: Optional[int],
    league: str,
    phase: Optional[str] = None,
) -> List[Dict]:
    soup = make_soup(html)
    counts = diagnose_markers(soup)
    if counts['spiel-row-v2'] > 0:
        return parse_v2_matches(soup, matchday, league, phase)
    if counts['spiele-row'] > 0:
        return parse_legacy_matches(soup, matchday, league, phase)
    log(
        "     ⚠️ Keine bekannten Spiel-Marker. "
        "Erwartet: div.spiel-row-v2 (Ligen neu) oder div.spiele-row (CL/EL alt)."
    )
    return []


def scrape_domestic_league(league: str, season: str, max_matchday: int = 38) -> List[Dict]:
    league_path = LEAGUE_PATHS.get(league, league)
    all_matches: List[Dict] = []
    consecutive_empty = 0
    max_consecutive_empty = 3

    log(f"   Liga-Pfad: /{league_path}/{season}/{{spieltag}}/")
    log("   Spielerkennung: siehe Marker + ✓-Zeilen je Spieltag")

    for matchday in range(1, max_matchday + 1):
        url = f"https://www.fussballdaten.de/{league_path}/{season}/{matchday}/"
        log(f"\n  📅 Spieltag {matchday}")
        html = fetch_html(url)
        if not html:
            consecutive_empty += 1
            log(
                f"     leer ({consecutive_empty}/{max_consecutive_empty}) — "
                "kein HTML, Parser läuft nicht"
            )
            if consecutive_empty >= max_consecutive_empty:
                log(f"  ⛔ {max_consecutive_empty} leere Seiten hintereinander — stoppe")
                break
            continue

        consecutive_empty = 0
        matches = parse_matches_html(html, matchday, league)
        all_matches.extend(matches)
        log(f"  ✅ Spieltag {matchday}: {len(matches)} Spiele gefunden")

    return all_matches


def scrape_england_matches(season: str) -> List[Dict]:
    return scrape_domestic_league('england', season)


def scrape_league_matches(league: str, season: str) -> List[Dict]:
    return scrape_domestic_league(league, season)


def scrape_international_matches(league: str, season: str) -> List[Dict]:
    all_matches: List[Dict] = []
    league_path = INT_LEAGUE_PATHS.get(league)
    if not league_path:
        return all_matches

    log(f"   Liga-Pfad: /{league_path}/{season}/{{phase}}/{{spieltag}}/")

    for phase in INT_PHASES:
        has_matchdays = phase in PHASES_WITH_MATCHDAYS
        log(f"\n  📂 Phase {phase} ({'Spieltage' if has_matchdays else 'K.O.-Runde'})")

        if has_matchdays:
            consecutive_empty = 0
            for matchday in range(1, 21):
                url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/{matchday}/"
                log(f"\n    📅 {phase} Spieltag {matchday}")
                html = fetch_html(url)
                if not html:
                    consecutive_empty += 1
                    log("     leer — kein HTML")
                    if matchday == 1:
                        log(f"  ⛔ {phase} Spieltag 1 fehlt — Phase übersprungen")
                        break
                    if consecutive_empty >= 3:
                        log(f"  ⛔ 3 leere Spieltage — stoppe Phase {phase}")
                        break
                    continue
                consecutive_empty = 0
                matches = parse_matches_html(html, matchday, league, phase)
                all_matches.extend(matches)
                log(f"  ✅ {league} {phase} Spieltag {matchday}: {len(matches)} Spiele")
        else:
            url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/"
            html = fetch_html(url)
            if not html:
                log(f"     {phase} nicht vorhanden")
                continue
            matches = parse_matches_html(html, None, league, phase)
            all_matches.extend(matches)
            log(f"  ✅ {league} {phase}: {len(matches)} Spiele")

    return all_matches


def save_matches_json(league: str, season: str, matches: List[Dict], output_dir: str = 'data/matches'):
    os.makedirs(output_dir, exist_ok=True)
    output_data = {
        'league': league,
        'season': season,
        'lastUpdated': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'matches': matches,
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
    all_matches: List[Dict] = []
    try:
        api_url = f"https://api.openligadb.de/getmatchdata/{league_shortcut}/{season}"
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
            team1 = match_data.get('Team1', {})
            team2 = match_data.get('Team2', {})
            if not isinstance(team1, dict) or not isinstance(team2, dict):
                continue
            if not team1.get('TeamName') or not team2.get('TeamName'):
                continue
            all_matches.append(match_data)
        log(f"✅ {len(all_matches)} Matches von OpenLigaDB API geladen (Original-Format)")
        if all_matches:
            first_match = all_matches[0]
            team1_name = first_match.get('Team1', {}).get('TeamName', '')
            team2_name = first_match.get('Team2', {}).get('TeamName', '')
            match_date = first_match.get('MatchDateTime', '')
            log(f"   📝 Beispiel: {team1_name} vs {team2_name} am {match_date}")
    except Exception as e:
        log(f"❌ Fehler beim Laden von OpenLigaDB API: {e}")
        traceback.print_exc()
    return all_matches


def scrape_dfbpokal_matches(season: str) -> List[Dict]:
    all_matches: List[Dict] = []
    league_path = 'dfb-pokal'
    rounds = ['1-runde', '2-runde', 'achtelfinale', 'viertelfinale', 'halbfinale', 'finale']
    for round_name in rounds:
        url = f"https://www.fussballdaten.de/{league_path}/{season}/{round_name}/"
        log(f"🔍 Versuche DFB-Pokal: {url}")
        html = fetch_html(url)
        if not html:
            log(f"⚠️ Keine Daten für {round_name}")
            continue
        matches = parse_matches_html(html, 1, league_path)
        all_matches.extend(matches)
        log(f"✅ DFB-Pokal {round_name}: {len(matches)} Spiele gefunden")
    if not all_matches:
        log("⚠️ Keine DFB-Pokal-Spiele gefunden.")
    return all_matches


def print_parser_legend() -> None:
    log(
        "\n🔎 So erkennt der Parser ein Spiel:\n"
        "  NEU (Premier League, La Liga, …):\n"
        "    • Zeile:     <div class=\"spiel-row-v2\">\n"
        "    • Heim/Gast: a.srv2-team-name in .srv2-heim / .srv2-gast\n"
        "    • Status:    a.srv2-ergebnis.has-result | .is-upcoming | .live\n"
        "    • Ergebnis:  span.srv2-score-h  +  span.srv2-score-g  (nicht mehr '3:0' in einem Span)\n"
        "    • Datum:     title=\"Heim - Gast | TT.MM.JJJJ | Liga | n. Spieltag\"\n"
        "    • Uhrzeit:   span.srv2-zeit-time\n"
        "  ALT (Champions League u. a.):\n"
        "    • Zeile:     <div class=\"spiele-row\">\n"
        "    • Link:      <a class=\"ergebnis\" href=\"/{liga}/…/heim-gast/\">\n"
        "    • LIVE:      class enthält 'live'\n"
        "    • Beendet:   class='ergebnis' + Span 1:0\n"
        "    • Zukunft:   leere class + Span 18:45\n"
        "    • Datum:     title=\"Heim - Gast | TT.MM.JJJJ | …\"\n"
    )


def main() -> None:
    errors: List[str] = []
    log("🚀 Starte Match-Scraping...")
    print_parser_legend()

    try:
        season = get_current_season()
        log(f"📆 Saison-URL-Jahr: {season} (fussballdaten: Saison {int(season)-1}/{season})")

        try:
            log("\n📊 Scrape England...")
            england_matches = scrape_england_matches(season)
            save_matches_json('england', season, england_matches)
        except Exception as e:
            error_msg = f"Fehler bei England: {e}"
            log(f"❌ {error_msg}")
            traceback.print_exc()
            errors.append(error_msg)

        try:
            log("\n📊 Scrape Spain...")
            spain_matches = scrape_league_matches('spain', season)
            save_matches_json('spain', season, spain_matches)
        except Exception as e:
            error_msg = f"Fehler bei Spain: {e}"
            log(f"❌ {error_msg}")
            traceback.print_exc()
            errors.append(error_msg)

        try:
            log("\n📊 Scrape Italy...")
            italy_matches = scrape_league_matches('italy', season)
            save_matches_json('italy', season, italy_matches)
        except Exception as e:
            error_msg = f"Fehler bei Italy: {e}"
            log(f"❌ {error_msg}")
            traceback.print_exc()
            errors.append(error_msg)

        try:
            log("\n📊 Scrape France...")
            france_matches = scrape_league_matches('france', season)
            save_matches_json('france', season, france_matches)
        except Exception as e:
            error_msg = f"Fehler bei France: {e}"
            log(f"❌ {error_msg}")
            traceback.print_exc()
            errors.append(error_msg)

        try:
            int_season = get_international_season()
            log(f"\n📊 Scrape International (Saison {int_season})...")
            for league in ['championsleague', 'europaleague', 'conferenceleague']:
                try:
                    log(f"\n  📊 Scrape {league}...")
                    int_matches = scrape_international_matches(league, int_season)
                    save_matches_json(league, int_season, int_matches)
                except Exception as e:
                    error_msg = f"Fehler bei {league}: {e}"
                    log(f"❌ {error_msg}")
                    traceback.print_exc()
                    errors.append(error_msg)
        except Exception as e:
            error_msg = f"Fehler bei International: {e}"
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
