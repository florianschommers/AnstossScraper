#!/usr/bin/env python3
"""
Match-Scraper für Anstoss App
Scrapt Match-Daten von fussballdaten.de und speichert sie als JSON
"""

import requests
import re
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import os
from typing import List, Dict, Optional, Tuple

# User-Agent für Requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Team-Name-Mappings (vereinfacht, kann erweitert werden)
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

def get_current_season() -> str:
    """Ermittelt die aktuelle Saison (Juli - Juni)"""
    now = datetime.now()
    if now.month >= 7:  # Ab Juli
        return str(now.year + 1)
    else:
        return str(now.year)

def get_international_season() -> str:
    """Ermittelt die aktuelle internationale Saison (Juli - Juni)"""
    return get_current_season()

def normalize_team_slug(slug: str, league: str) -> str:
    """Normalisiert Team-Slug und mappt zu Display-Name"""
    slug_lower = slug.lower().strip()
    
    # Prüfe Mappings
    if league in TEAM_MAPPINGS:
        if slug_lower in TEAM_MAPPINGS[league]:
            return TEAM_MAPPINGS[league][slug_lower]
    
    # Fallback: Slug aufbereiten
    # Ersetze Punkte durch Bindestriche, dann Bindestriche durch Leerzeichen
    normalized = slug.replace('.', '-').replace('-', ' ').title()
    return normalized

def parse_team_from_slug(slug: str, league: str) -> Tuple[str, str]:
    """Extrahiert Home- und Away-Team aus Slug"""
    parts = slug.split('-')
    if len(parts) >= 2:
        home_slug = parts[0]
        away_slug = '-'.join(parts[1:])
        home_team = normalize_team_slug(home_slug, league)
        away_team = normalize_team_slug(away_slug, league)
        return home_team, away_team
    return '', ''

def fetch_html(url: str) -> Optional[str]:
    """Lädt HTML von einer URL"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            return response.text
        return None
    except Exception as e:
        print(f"❌ Fehler beim Laden von {url}: {e}")
        return None

def parse_england_matches(html: str, matchday: int, season: str) -> List[Dict]:
    """Parst England-Matches aus HTML"""
    matches = []
    
    # Pattern für zukünftige Spiele
    zukunft_pattern = re.compile(
        r'href="/england/\d+/\d+/([a-z0-9.-]+)/"[^>]*title="[^"]*\((\d{2})\.(\d{2})\.(\d{4})[^)]*\)[^"]*"[^>]*>[\s\S]*?<span>(\d{2}:\d{2})</span>',
        re.IGNORECASE
    )
    
    # Pattern für Live-Spiele
    live_pattern = re.compile(
        r'class="ergebnis\s+live"[^>]*href="/england/\d+/\d+/([a-z0-9.-]+)/"[^>]*>[\s\S]*?<span[^>]*>(\d+:\d+)</span>',
        re.IGNORECASE
    )
    
    # Pattern für vergangene Spiele
    vergangen_pattern = re.compile(
        r'class="ergebnis"\s+href="/england/\d+/\d+/([a-z0-9.-]+)/"[^>]*title="[^"]*\((\d{2})\.(\d{2})\.(\d{4})[^)]*\)[^"]*"[^>]*>[\s\S]*?<span[^>]*id="[^"]*"[^>]*>(\d+:\d+)</span>',
        re.IGNORECASE
    )
    
    # Live-Spiele
    for match in live_pattern.finditer(html):
        slug = match.group(1)
        score = match.group(2)
        home_team, away_team = parse_team_from_slug(slug, 'england')
        if home_team and away_team:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            matches.append({
                'matchday': matchday,
                'homeTeam': home_team,
                'awayTeam': away_team,
                'dateTime': today.isoformat() + 'Z',
                'score': score,
                'isFinished': False,
                'isLive': True,
                'liveScore': score
            })
    
    # Zukünftige Spiele
    for match in zukunft_pattern.finditer(html):
        slug = match.group(1)
        day = int(match.group(2))
        month = int(match.group(3))
        year = int(match.group(4))
        time_str = match.group(5)
        
        home_team, away_team = parse_team_from_slug(slug, 'england')
        if home_team and away_team:
            hour, minute = map(int, time_str.split(':'))
            match_datetime = datetime(year, month, day, hour, minute)
            matches.append({
                'matchday': matchday,
                'homeTeam': home_team,
                'awayTeam': away_team,
                'dateTime': match_datetime.isoformat() + 'Z',
                'score': None,
                'isFinished': False,
                'isLive': False,
                'liveScore': None
            })
    
    # Vergangene Spiele
    for match in vergangen_pattern.finditer(html):
        slug = match.group(1)
        day = int(match.group(2))
        month = int(match.group(3))
        year = int(match.group(4))
        score = match.group(5)
        
        home_team, away_team = parse_team_from_slug(slug, 'england')
        if home_team and away_team:
            match_datetime = datetime(year, month, day, 15, 0)  # Geschätzte Uhrzeit
            matches.append({
                'matchday': matchday,
                'homeTeam': home_team,
                'awayTeam': away_team,
                'dateTime': match_datetime.isoformat() + 'Z',
                'score': score,
                'isFinished': True,
                'isLive': False,
                'liveScore': None
            })
    
    return matches

def scrape_england_matches(season: str) -> List[Dict]:
    """Scrapt alle England-Matches für eine Saison"""
    all_matches = []
    league_path = 'england'
    
    # Schätze aktuellen Spieltag
    current_week = datetime.now().isocalendar()[1]
    estimated_matchday = max(1, (current_week - 30) // 2)
    start_matchday = max(1, estimated_matchday - 5)
    
    consecutive_empty = 0
    max_consecutive_empty = 3
    
    for matchday in range(start_matchday, 39):
        url = f"https://www.fussballdaten.de/{league_path}/{season}/{matchday}/"
        html = fetch_html(url)
        
        if not html or len(html) < 1000:
            consecutive_empty += 1
            if consecutive_empty >= max_consecutive_empty:
                break
            continue
        
        consecutive_empty = 0
        matches = parse_england_matches(html, matchday, season)
        all_matches.extend(matches)
        
        print(f"✅ Spieltag {matchday}: {len(matches)} Spiele gefunden")
    
    return all_matches

def parse_league_matches(html: str, matchday: int, season: str, league_path: str) -> List[Dict]:
    """Parst Matches aus HTML für eine Liga (Spain, Italy, France)"""
    matches = []
    
    # Pattern für zukünftige Spiele
    zukunft_pattern = re.compile(
        rf'href="/{league_path}/\d+/\d+/([a-z0-9.-]+)/"[^>]*title="[^"]*\((\d{{2}})\.(\d{{2}})\.(\d{{4}})[^)]*\)[^"]*"[^>]*>[\s\S]*?<span>(\d{{2}}:\d{{2}})</span>',
        re.IGNORECASE
    )
    
    # Pattern für Live-Spiele
    live_pattern = re.compile(
        rf'class="ergebnis\s+live"[^>]*href="/{league_path}/\d+/\d+/([a-z0-9.-]+)/"[^>]*>[\s\S]*?<span[^>]*>(\d+:\d+)</span>',
        re.IGNORECASE
    )
    
    # Pattern für vergangene Spiele
    vergangen_pattern = re.compile(
        rf'class="ergebnis"\s+href="/{league_path}/\d+/\d+/([a-z0-9.-]+)/"[^>]*title="[^"]*\((\d{{2}})\.(\d{{2}})\.(\d{{4}})[^)]*\)[^"]*"[^>]*>[\s\S]*?<span[^>]*id="[^"]*"[^>]*>(\d+:\d+)</span>',
        re.IGNORECASE
    )
    
    # Live-Spiele
    for match in live_pattern.finditer(html):
        slug = match.group(1)
        score = match.group(2)
        home_team, away_team = parse_team_from_slug(slug, league_path)
        if home_team and away_team:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            matches.append({
                'matchday': matchday,
                'homeTeam': home_team,
                'awayTeam': away_team,
                'dateTime': today.isoformat() + 'Z',
                'score': score,
                'isFinished': False,
                'isLive': True,
                'liveScore': score
            })
    
    # Zukünftige Spiele
    for match in zukunft_pattern.finditer(html):
        slug = match.group(1)
        day = int(match.group(2))
        month = int(match.group(3))
        year = int(match.group(4))
        time_str = match.group(5)
        
        home_team, away_team = parse_team_from_slug(slug, league_path)
        if home_team and away_team:
            hour, minute = map(int, time_str.split(':'))
            match_datetime = datetime(year, month, day, hour, minute)
            matches.append({
                'matchday': matchday,
                'homeTeam': home_team,
                'awayTeam': away_team,
                'dateTime': match_datetime.isoformat() + 'Z',
                'score': None,
                'isFinished': False,
                'isLive': False,
                'liveScore': None
            })
    
    # Vergangene Spiele
    for match in vergangen_pattern.finditer(html):
        slug = match.group(1)
        day = int(match.group(2))
        month = int(match.group(3))
        year = int(match.group(4))
        score = match.group(5)
        
        home_team, away_team = parse_team_from_slug(slug, league_path)
        if home_team and away_team:
            match_datetime = datetime(year, month, day, 15, 0)
            matches.append({
                'matchday': matchday,
                'homeTeam': home_team,
                'awayTeam': away_team,
                'dateTime': match_datetime.isoformat() + 'Z',
                'score': score,
                'isFinished': True,
                'isLive': False,
                'liveScore': None
            })
    
    return matches

def scrape_league_matches(league: str, season: str) -> List[Dict]:
    """Scrapt Matches für eine Liga (Bundesliga, Spain, Italy, France)"""
    all_matches = []
    league_paths = {
        'bundesliga1': 'bundesliga',
        'bundesliga2': '2bundesliga',
        'spain': 'spanien',
        'italy': 'italien',
        'france': 'frankreich'
    }
    
    if league not in league_paths:
        return all_matches
    
    league_path = league_paths[league]
    
    # Ähnliche Logik wie England
    current_week = datetime.now().isocalendar()[1]
    estimated_matchday = max(1, (current_week - 30) // 2)
    start_matchday = max(1, estimated_matchday - 5)
    
    consecutive_empty = 0
    max_consecutive_empty = 3
    
    for matchday in range(start_matchday, 39):
        url = f"https://www.fussballdaten.de/{league_path}/{season}/{matchday}/"
        html = fetch_html(url)
        
        if not html or len(html) < 1000:
            consecutive_empty += 1
            if consecutive_empty >= max_consecutive_empty:
                break
            continue
        
        consecutive_empty = 0
        matches = parse_league_matches(html, matchday, season, league_path)
        all_matches.extend(matches)
        
        print(f"✅ {league} Spieltag {matchday}: {len(matches)} Spiele gefunden")
    
    return all_matches

def scrape_international_matches(league: str, season: str) -> List[Dict]:
    """Scrapt internationale Matches (Champions/Europa/Conference League)"""
    all_matches = []
    league_paths = {
        'championsleague': 'championsleague',
        'europaleague': 'europaleague',
        'conferenceleague': 'conferenceleague'
    }
    
    if league not in league_paths:
        return all_matches
    
    league_path = league_paths[league]
    phases = ['gruppenphase', 'play-offs', 'achtelfinale', 'viertelfinale', 'halbfinale', 'finale']
    
    if league == 'conferenceleague':
        phases = ['league-stage', 'play-offs', 'achtelfinale', 'viertelfinale', 'halbfinale', 'finale']
    
    for phase in phases:
        has_matchdays = phase in ['gruppenphase', 'league-stage']
        
        if has_matchdays:
            for matchday in range(1, 21):
                url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/{matchday}/"
                html = fetch_html(url)
                
                if not html or len(html) < 1000:
                    break
                
                # Parse Matches (vereinfacht)
                matches = parse_international_matches(html, phase, matchday, league)
                all_matches.extend(matches)
                print(f"✅ {league} {phase} Spieltag {matchday}: {len(matches)} Spiele")
        else:
            url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/"
            html = fetch_html(url)
            
            if html and len(html) >= 1000:
                matches = parse_international_matches(html, phase, None, league)
                all_matches.extend(matches)
                print(f"✅ {league} {phase}: {len(matches)} Spiele")
    
    return all_matches

def parse_international_matches(html: str, phase: str, matchday: Optional[int], league: str) -> List[Dict]:
    """Parst internationale Matches aus HTML"""
    matches = []
    
    # Pattern für Datum: "Donnerstag, 06.11.2025"
    date_pattern = re.compile(r'(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),?\s*(\d{2})\.(\d{2})\.(\d{4})')
    
    # Pattern für League-Format: /championsleague/2026/gruppenphase/4/psg-bayern/
    league_pattern = re.compile(
        r'href="/(championsleague|europaleague|conferenceleague)/\d{4}/(?:gruppenphase|league-stage)/\d+/([a-z0-9.]+)-([a-z0-9.]+)/"[^>]*>\s*<span[^>]*>(\d{1,2}:\d{1,2})</span>',
        re.IGNORECASE
    )
    
    # Pattern für Vereine-Format: /vereine/slavia-prag/fc-arsenal/
    vereine_pattern = re.compile(
        r'href="/vereine/((?:[a-z0-9-]+/)+[a-z0-9-]+)/"[^>]*>\s*<span[^>]*>(\d{1,2}:\d{1,2})</span>'
    )
    
    # Finde alle Daten
    date_matches = list(date_pattern.finditer(html))
    
    for date_match in date_matches:
        day = int(date_match.group(2))
        month = int(date_match.group(3))
        year = int(date_match.group(4))
        
        # Finde Abschnitt zwischen diesem und nächstem Datum
        start_idx = date_match.end()
        next_date = date_matches[date_matches.index(date_match) + 1] if date_matches.index(date_match) + 1 < len(date_matches) else None
        end_idx = next_date.start() if next_date else len(html)
        
        section = html[start_idx:end_idx]
        
        # Parse League-Format
        for match in league_pattern.finditer(section):
            home_slug = match.group(2)
            away_slug = match.group(3)
            time_str = match.group(4)
            
            home_team = normalize_team_slug(home_slug, league)
            away_team = normalize_team_slug(away_slug, league)
            
            if home_team and away_team:
                hour, minute = map(int, time_str.split(':'))
                match_datetime = datetime(year, month, day, hour, minute)
                
                # Prüfe ob Ergebnis oder Uhrzeit
                is_result = hour < 10
                
                matches.append({
                    'matchday': matchday,
                    'homeTeam': home_team,
                    'awayTeam': away_team,
                    'dateTime': match_datetime.isoformat() + 'Z',
                    'score': time_str if is_result else None,
                    'isFinished': is_result,
                    'isLive': False,
                    'liveScore': None,
                    'phase': phase
                })
        
        # Parse Vereine-Format
        for match in vereine_pattern.finditer(section):
            link_path = match.group(1)
            time_str = match.group(2)
            
            path_parts = link_path.split('/')
            if len(path_parts) >= 2:
                away_slug = path_parts[-1]
                home_slug = '/'.join(path_parts[:-1])
                
                home_team = normalize_team_slug(home_slug.replace('/', '-'), league)
                away_team = normalize_team_slug(away_slug, league)
                
                if home_team and away_team:
                    hour, minute = map(int, time_str.split(':'))
                    match_datetime = datetime(year, month, day, hour, minute)
                    
                    is_result = hour < 10
                    
                    matches.append({
                        'matchday': matchday,
                        'homeTeam': home_team,
                        'awayTeam': away_team,
                        'dateTime': match_datetime.isoformat() + 'Z',
                        'score': time_str if is_result else None,
                        'isFinished': is_result,
                        'isLive': False,
                        'liveScore': None,
                        'phase': phase
                    })
    
    return matches

def save_matches_json(league: str, season: str, matches: List[Dict], output_dir: str = 'data/matches'):
    """Speichert Matches als JSON-Datei"""
    os.makedirs(output_dir, exist_ok=True)
    
    output_data = {
        'league': league,
        'season': season,
        'lastUpdated': datetime.utcnow().isoformat() + 'Z',
        'matches': matches
    }
    
    filename = f"{output_dir}/matches_{league}_{season}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Gespeichert: {filename} ({len(matches)} Matches)")

def scrape_bundesliga_matches(season: str) -> List[Dict]:
    """Scrapt Bundesliga-Matches (1. und 2. Bundesliga)"""
    all_matches = []
    
    # Scrape 1. Bundesliga
    print("\n📊 Scrape 1. Bundesliga...")
    bl1_matches = scrape_league_matches('bundesliga1', season)
    all_matches.extend(bl1_matches)
    
    # Scrape 2. Bundesliga
    print("\n📊 Scrape 2. Bundesliga...")
    bl2_matches = scrape_league_matches('bundesliga2', season)
    all_matches.extend(bl2_matches)
    
    return all_matches

def main():
    """Hauptfunktion"""
    print("🚀 Starte Match-Scraping...")
    
    season = get_current_season()
    
    # Bundesliga (1. und 2. Liga)
    print("\n📊 Scrape Bundesliga...")
    bundesliga_matches = scrape_bundesliga_matches(season)
    save_matches_json('bundesliga', season, bundesliga_matches)
    
    # England
    print("\n📊 Scrape England...")
    england_matches = scrape_england_matches(season)
    save_matches_json('england', season, england_matches)
    
    # Spain
    print("\n📊 Scrape Spain...")
    spain_matches = scrape_league_matches('spain', season)
    save_matches_json('spain', season, spain_matches)
    
    # Italy
    print("\n📊 Scrape Italy...")
    italy_matches = scrape_league_matches('italy', season)
    save_matches_json('italy', season, italy_matches)
    
    # France
    print("\n📊 Scrape France...")
    france_matches = scrape_league_matches('france', season)
    save_matches_json('france', season, france_matches)
    
    # International
    int_season = get_international_season()
    print(f"\n📊 Scrape International (Saison {int_season})...")
    
    for league in ['championsleague', 'europaleague', 'conferenceleague']:
        print(f"\n  📊 Scrape {league}...")
        int_matches = scrape_international_matches(league, int_season)
        save_matches_json(league, int_season, int_matches)
    
    print("\n✅ Scraping abgeschlossen!")

if __name__ == '__main__':
    main()

