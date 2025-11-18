#!/usr/bin/env python3
"""
Lineup-Scraper für Anstoss App
Scrapt Aufstellungen von fussballdaten.de für alle Spiele und speichert sie als JSON auf GitHub
"""

import requests
import re
import json
import os
import sys
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple
import time

# Import Team-Slug-Konverter
from team_slug_converter import convert_team_to_slug, REQUEST_DELAY

# User-Agent für Requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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

def fetch_html(url: str) -> Optional[str]:
    """Lädt HTML von einer URL mit Rate Limiting"""
    try:
        time.sleep(REQUEST_DELAY)  # Rate Limiting
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            return response.text
        else:
            print(f"  ⚠️ HTTP {response.status_code} für {url}")
            return None
    except Exception as e:
        print(f"  ❌ Fehler beim Laden von {url}: {e}")
        return None

def extract_team_html(html: str, css_class: str) -> str:
    """Extrahiert Team-HTML aus dem Gesamt-HTML (heim-content oder gast-content)"""
    this_class = css_class
    other_class = "gast-content" if css_class == "heim-content" else "heim-content"
    
    # Finde Start-Position
    start_pattern = re.compile(f'<div[^>]*class="[^"]*{re.escape(this_class)}[^"]*"[^>]*>', re.IGNORECASE)
    start_match = start_pattern.search(html)
    if not start_match:
        return ""
    
    content_start = start_match.end()
    
    # Finde End-Position (nächstes other_class div)
    end_pattern = re.compile(f'<div[^>]*class="[^"]*{re.escape(other_class)}[^"]*"[^>]*>', re.IGNORECASE)
    end_match = end_pattern.search(html, content_start)
    content_end = end_match.start() if end_match else len(html)
    
    if content_start >= 0 and content_start < content_end and content_end <= len(html):
        return html[content_start:content_end]
    return ""

def extract_start11_area(team_html: str) -> str:
    """Extrahiert den Start-11-Bereich (vor Reservebank)"""
    splitter = ["Reservebank", "Ersatzbank", "Bank"]
    cut = -1
    for s in splitter:
        idx = team_html.find(s)
        if idx >= 0:
            cut = idx if cut == -1 else min(cut, idx)
    return team_html[:cut] if cut > 0 else team_html

def analyze_start11(html_segment: str) -> List[str]:
    """Analysiert Start-11 nur aus Person-Links (wie in LiveBingo.kt)"""
    players = []
    # Pattern: <a[^>]*class="[^"]*name[^"]*"[^>]*href="/person/([^/]+)/"[^>]*>([\s\S]*?)</a>
    pattern = re.compile(r'<a[^>]*class="[^"]*name[^"]*"[^>]*href="/person/([^/]+)/"[^>]*>([\s\S]*?)</a>', re.IGNORECASE)
    
    slug_to_name = {}
    for match in pattern.finditer(html_segment):
        if len(slug_to_name) >= 11:
            break
        
        slug = match.group(1).strip()
        inner = match.group(2)
        
        # Versuche title-Attribut zu finden
        title_match = re.search(r'title="([^"]+)"', inner)
        title_name = title_match.group(1) if title_match else None
        
        # Extrahiere Text (ohne Tags)
        text_name = re.sub(r'<[^>]+>', ' ', inner).strip()
        text_name = re.sub(r'\s+', ' ', text_name)
        
        best_name = title_name if title_name and title_name.strip() else text_name
        clean_name = simplify_player_name(best_name)
        
        # Filtere Trainer
        if clean_name and not is_coach(clean_name):
            slug_to_name[slug] = clean_name
    
    return list(slug_to_name.values())

def simplify_player_name(name: str) -> str:
    """Vereinfacht Spielernamen (wie in LiveBingo.kt)"""
    if not name:
        return ""
    # Entferne HTML-Entities
    cleaned = name.replace("&amp;", "&").replace("&quot;", '"')
    # Diakritika entfernen
    import unicodedata
    cleaned = unicodedata.normalize('NFD', cleaned)
    cleaned = ''.join(c for c in cleaned if unicodedata.category(c) != 'Mn')
    cleaned = cleaned.replace("ß", "ss")
    # Whitespace normalisieren
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def is_coach(name: str) -> bool:
    """Prüft ob Name ein Trainer ist"""
    if not name:
        return False
    lower_name = name.lower()
    return "trainer" in lower_name or "head coach" in lower_name or "coach" in lower_name

# Team-Name-Konvertierung wird jetzt von team_slug_converter.py übernommen

def find_matchday_for_match(league_path: str, season: str, home_team: str, away_team: str, is_international: bool = False, liga_id: int = 1, phase: str = '') -> Optional[int]:
    """
    Findet den richtigen Spieltag für ein Match, indem durch Spieltage iteriert wird
    und geprüft wird, ob Spiele in der Zukunft sind.
    
    Beispiel Bundesliga:
    - Iteriere durch Spieltage 1, 2, 3, ...
    - Prüfe ob Spiele in der Zukunft sind
    - Sobald Spiele in der Zukunft gefunden werden, ist das der richtige Spieltag
    """
    now = datetime.now()
    
    if is_international:
        # Internationale Ligen: Prüfe Phasen mit Spieltagen
        if phase in ['gruppenphase', 'league-stage']:
            for matchday in range(1, 21):
                url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/{matchday}/"
                html = fetch_html(url)
                if not html or len(html) < 1000:
                    continue
                
                # Prüfe ob Spiele in der Zukunft sind
                if has_future_matches(html, now):
                    print(f"    📅 Spieltag {matchday} gefunden (hat zukünftige Spiele)")
                    return matchday
        else:
            # Phasen ohne Spieltage (achtelfinale, etc.)
            return None
    elif liga_id == 3:  # DFB-Pokal
        # DFB-Pokal: Prüfe Runden
        rounds = ['1-runde', '2-runde', 'achtelfinale', 'viertelfinale', 'halbfinale', 'finale']
        for round_name in rounds:
            url = f"https://www.fussballdaten.de/{league_path}/{season}/{round_name}/"
            html = fetch_html(url)
            if not html or len(html) < 1000:
                continue
            
            # Prüfe ob Spiele in der Zukunft sind
            if has_future_matches(html, now):
                print(f"    📅 Runde {round_name} gefunden (hat zukünftige Spiele)")
                return round_name  # Für DFB-Pokal ist matchday der Runden-Name
    else:
        # Normale Ligen: Iteriere durch Spieltage 1-34
        for matchday in range(1, 35):
            url = f"https://www.fussballdaten.de/{league_path}/{season}/{matchday}/"
            html = fetch_html(url)
            if not html or len(html) < 1000:
                continue
            
            # Prüfe ob Spiele in der Zukunft sind
            if has_future_matches(html, now):
                print(f"    📅 Spieltag {matchday} gefunden (hat zukünftige Spiele)")
                return matchday
    
    return None

def has_future_matches(html: str, now: datetime) -> bool:
    """
    Prüft ob die HTML-Seite Spiele in der Zukunft enthält.
    Sucht nach Datums-Patterns im HTML und vergleicht mit jetzt.
    """
    # Pattern für zukünftige Spiele: title="... (DD.MM.YYYY) ..." mit Uhrzeit
    zukunft_pattern = re.compile(
        r'title="[^"]*\((\d{2})\.(\d{2})\.(\d{4})[^)]*\)[^"]*"[^>]*>[\s\S]*?<span>(\d{2}:\d{2})</span>',
        re.IGNORECASE
    )
    
    # Pattern für Live-Spiele (sind auch "in der Zukunft" im Sinne von "aktuell")
    live_pattern = re.compile(
        r'class="ergebnis\s+live"',
        re.IGNORECASE
    )
    
    # Prüfe auf Live-Spiele
    if live_pattern.search(html):
        return True
    
    # Prüfe auf zukünftige Spiele
    for match in zukunft_pattern.finditer(html):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        time_str = match.group(4)
        
        try:
            hour, minute = map(int, time_str.split(':'))
            match_datetime = datetime(year, month, day, hour, minute)
            
            # Prüfe ob das Spiel in der Zukunft ist (oder heute)
            if match_datetime >= now:
                return True
        except:
            continue
    
    return False

def scrape_lineup_for_match(league_path: str, season: str, phase: str, matchday: Optional[int], home_team: str, away_team: str, is_international: bool = False, liga_id: int = 1) -> Optional[Tuple[List[str], List[str]]]:
    """Scrapt Aufstellung für ein einzelnes Spiel - OPTIMIERT: Testet zuerst nur ±2 Spieltage, dann alle anderen"""
    # Erstelle Team-Slugs mit der korrekten Konvertierungs-Logik
    home_slug = convert_team_to_slug(home_team, liga_id, is_international)
    away_slug = convert_team_to_slug(away_team, liga_id, is_international)
    
    if not home_slug or not away_slug:
        print(f"    ⚠️ Konnte Team-Slugs nicht erstellen: {home_team} → {home_slug}, {away_team} → {away_slug}")
        return None
    
    # OPTIMIERT: Teste zuerst nur ±1 Spieltag (statt ±2) für maximale Performance
    # Ziel: 112 Spiele × 3 Spieltage (±1) × 2 URLs = 672 Requests (statt 20.808)
    # Wenn alle im ersten Versuch gefunden werden: ~5-6 Minuten statt 173 Minuten
    
    # STEP 1: Spieltag-Ermittlung für jede Liga
    # - Bundesliga/2. Bundesliga/England/Spain/Italy/France: matchday kommt direkt aus Match-Daten (wird beim Scraping aus URL extrahiert)
    # - DFB-Pokal: matchday ist Runden-Name (z.B. "1-runde", "achtelfinale")
    # - Internationale Ligen: phase + matchday kommen aus Match-Daten
    
    # Phase 1: Teste zuerst nur den spezifischen Spieltag ±1 (3 Spieltage: base-1, base, base+1)
    if is_international:
        # International: Teste zuerst spezifischen Spieltag (kein ±1, da Phase wichtig ist)
        first_rounds_to_test = []
        if matchday and phase:
            first_rounds_to_test.append((phase, matchday))
    elif liga_id == 3:  # DFB-Pokal
        # DFB-Pokal: Teste zuerst spezifische Runde (kein ±1, da Runden-Namen sind)
        first_rounds_to_test = []
        if matchday and isinstance(matchday, str):
            dfb_rounds = ["1-runde", "2-runde", "achtelfinale", "viertelfinale", "halbfinale", "finale"]
            if matchday in dfb_rounds:
                first_rounds_to_test.append(matchday)
    else:
        # Normale Ligen: Teste zuerst nur ±1 Spieltag (3 Spieltage: base-1, base, base+1)
        first_rounds_to_test = []
        if matchday:
            try:
                base_matchday = int(matchday) if isinstance(matchday, (int, str)) else 1
                # ±1 Spieltag: base-1, base, base+1 (nur 3 Spieltage statt 5!)
                matchdays_to_test = list(range(max(1, base_matchday - 1), min(35, base_matchday + 2)))
                first_rounds_to_test = [str(md) for md in matchdays_to_test]
            except:
                first_rounds_to_test = []
    
    # Phase 1: Teste zuerst nur ±1 Spieltag (schnell!)
    for round_value in first_rounds_to_test:
        if is_international:
            test_phase, test_matchday = round_value
            if test_matchday:
                base_url = f"https://www.fussballdaten.de/{league_path}/{season}/{test_phase}/{test_matchday}"
            else:
                base_url = f"https://www.fussballdaten.de/{league_path}/{season}/{test_phase}"
            urls = [
                f"{base_url}/{home_slug}-{away_slug}/aufstellung/",
                f"{base_url}/{away_slug}-{home_slug}/aufstellung/"
            ]
        else:
            # Deutsche/ausländische Ligen
            urls = [
                f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{home_slug}-{away_slug}/aufstellung/",
                f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{away_slug}-{home_slug}/aufstellung/"
            ]
        
        for url in urls:
            html = fetch_html(url)
            
            if html and "heim-content" in html and "gast-content" in html:
                # STEP 2: Sofort abbrechen wenn gefunden (keine weiteren Tests!)
                print(f"    ✅ Aufstellungsseite gefunden: {url}")
                
                heim_html = extract_team_html(html, "heim-content")
                gast_html = extract_team_html(html, "gast-content")
                
                heim_start11 = analyze_start11(extract_start11_area(heim_html))
                gast_start11 = analyze_start11(extract_start11_area(gast_html))
                
                print(f"    🏠 Heim: {len(heim_start11)} Spieler")
                print(f"    ✈️ Gast: {len(gast_start11)} Spieler")
                
                if heim_start11 and gast_start11:
                    # Bestimme Zuordnung aus URL
                    is_home_first = f"{home_slug}-{away_slug}" in url
                    if is_home_first:
                        return (heim_start11, gast_start11)
                    else:
                        return (gast_start11, heim_start11)
                # Wenn Parsing fehlschlägt, versuche nächste URL (aber nicht nächsten Spieltag!)
    
    # Phase 2: Nur wenn Phase 1 komplett fehlgeschlagen ist, teste ±1 weitere Spieltage
    # (Nur für normale Ligen, nicht für DFB-Pokal oder internationale Ligen)
    if not is_international and liga_id != 3 and matchday:
        try:
            base_matchday = int(matchday) if isinstance(matchday, (int, str)) else 1
            # Erweitere ±1 auf ±2 (falls Phase 1 fehlgeschlagen ist)
            matchdays_tested = list(range(max(1, base_matchday - 1), min(35, base_matchday + 2)))
            # Teste ±2 (base-2, base+2) - aber nur wenn Phase 1 fehlgeschlagen ist
            fallback_matchdays = []
            if base_matchday - 2 >= 1 and str(base_matchday - 2) not in first_rounds_to_test:
                fallback_matchdays.append(str(base_matchday - 2))
            if base_matchday + 2 < 35 and str(base_matchday + 2) not in first_rounds_to_test:
                fallback_matchdays.append(str(base_matchday + 2))
            
            if fallback_matchdays:
                print(f"    ⚠️ Phase 1 fehlgeschlagen, teste jetzt ±2 Spieltage: {fallback_matchdays}")
                for round_value in fallback_matchdays:
                    urls = [
                        f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{home_slug}-{away_slug}/aufstellung/",
                        f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{away_slug}-{home_slug}/aufstellung/"
                    ]
                    
                    for url in urls:
                        html = fetch_html(url)
                        
                        if html and "heim-content" in html and "gast-content" in html:
                            print(f"    ✅ Aufstellungsseite gefunden (Phase 2): {url}")
                            
                            heim_html = extract_team_html(html, "heim-content")
                            gast_html = extract_team_html(html, "gast-content")
                            
                            heim_start11 = analyze_start11(extract_start11_area(heim_html))
                            gast_start11 = analyze_start11(extract_start11_area(gast_html))
                            
                            print(f"    🏠 Heim: {len(heim_start11)} Spieler")
                            print(f"    ✈️ Gast: {len(gast_start11)} Spieler")
                            
                            if heim_start11 and gast_start11:
                                # STEP 2: Sofort abbrechen wenn gefunden!
                                is_home_first = f"{home_slug}-{away_slug}" in url
                                if is_home_first:
                                    return (heim_start11, gast_start11)
                                else:
                                    return (gast_start11, heim_start11)
    
    # Beide Phasen fehlgeschlagen
    total_tested = len(first_rounds_to_test)
    print(f"    ❌ Keine Aufstellung gefunden nach {total_tested} Spieltagen/Runden")
    return None

def load_matches_from_json(file_path: str) -> List[Dict]:
    """Lädt Matches aus JSON-Datei"""
    # Stelle sicher, dass der Pfad korrekt ist
    if not os.path.isabs(file_path) and os.path.basename(os.getcwd()) == 'scraper':
        # Wenn wir im scraper/ Verzeichnis sind und der Pfad relativ ist, gehe nach oben
        if not file_path.startswith('..'):
            file_path = os.path.join('..', file_path)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'matches' in data:
                return data['matches']
            elif isinstance(data, list):
                return data
            else:
                return []
    except Exception as e:
        print(f"❌ Fehler beim Laden von {file_path}: {e}")
        return []

def scrape_lineups_for_league(league_name: str, season: str, data_dir: str = 'data/matches') -> Dict:
    """Scrapt Aufstellungen für alle Spiele einer Liga"""
    print(f"\n{'='*60}")
    print(f"🏆 Liga: {league_name} (Saison {season})")
    print(f"{'='*60}")
    
    # Stelle sicher, dass das Verzeichnis relativ zum Repository-Root ist
    # Wenn wir im scraper/ Verzeichnis sind, gehen wir ein Verzeichnis nach oben
    if os.path.basename(os.getcwd()) == 'scraper':
        data_dir = os.path.join('..', data_dir)
    
    # Lade Matches
    match_file = os.path.join(data_dir, f"matches_{league_name}_{season}.json")
    if not os.path.exists(match_file):
        print(f"⚠️ Match-Datei nicht gefunden: {match_file}")
        return {"league": league_name, "season": season, "lineups": []}
    
    matches = load_matches_from_json(match_file)
    print(f"📊 Gefundene Spiele: {len(matches)}")
    
    # Bestimme League-Path, ob international und Liga-ID
    league_configs = {
        "bundesliga": ("bundesliga", False, 1),
        "2bundesliga": ("2liga", False, 2),
        "dfbpokal": ("dfb-pokal", False, 3),
        "championsleague": ("championsleague", True, 11),
        "europaleague": ("europaleague", True, 12),
        "conferenceleague": ("conferenceleague", True, 13),
        "england": ("england", False, 51),
        "spain": ("spanien", False, 41),
        "italy": ("italien", False, 31),
        "france": ("frankreich", False, 21),
    }
    
    league_path, is_international, liga_id = league_configs.get(league_name, (league_name, False, 1))
    
    lineups = []
    successful = 0
    failed = 0
    
    for i, match in enumerate(matches, 1):
        home_team = match.get('homeTeam', '')
        away_team = match.get('awayTeam', '')
        date_time = match.get('dateTime', '')
        matchday = match.get('matchday', None)
        phase = match.get('phase', '')
        
        print(f"\n[{i}/{len(matches)}] {home_team} vs {away_team}")
        
        # STEP 1: Finde den richtigen Spieltag, wenn nicht vorhanden oder unsicher
        if not matchday or matchday == 1:  # matchday=1 ist oft falsch (besonders bei DFB-Pokal)
            print(f"    🔍 Suche richtigen Spieltag...")
            found_matchday = find_matchday_for_match(
                league_path, season, home_team, away_team, is_international, liga_id, phase
            )
            if found_matchday:
                matchday = found_matchday
                print(f"    ✅ Spieltag gefunden: {matchday}")
            else:
                print(f"    ⚠️ Spieltag nicht gefunden, verwende vorhandenen: {matchday}")
        
        # Scrapte Aufstellung (testet automatisch ±1 Spieltag)
        lineup = scrape_lineup_for_match(
            league_path, season, phase, matchday,
            home_team, away_team, is_international, liga_id
        )
        
        if lineup:
            lineups.append({
                "homeTeam": home_team,
                "awayTeam": away_team,
                "dateTime": date_time,
                "matchday": matchday,
                "phase": phase,
                "homeLineup": lineup[0],
                "awayLineup": lineup[1]
            })
            successful += 1
            print(f"  ✅ Aufstellung gescrappt: {len(lineup[0])} Heim, {len(lineup[1])} Auswärts")
        else:
            failed += 1
            print(f"  ❌ Aufstellung nicht gefunden")
    
    print(f"\n{'='*60}")
    print(f"✅ Erfolgreich: {successful}")
    print(f"❌ Fehlgeschlagen: {failed}")
    print(f"{'='*60}")
    
    return {
        "league": league_name,
        "season": season,
        "lastUpdated": datetime.now().isoformat(),
        "lineups": lineups
    }

def save_lineups_json(league_name: str, season: str, lineups_data: Dict, output_dir: str = 'data/lineups'):
    """Speichert Aufstellungen als JSON"""
    # Stelle sicher, dass das Verzeichnis relativ zum Repository-Root ist
    # Wenn wir im scraper/ Verzeichnis sind, gehen wir ein Verzeichnis nach oben
    if os.path.basename(os.getcwd()) == 'scraper':
        output_dir = os.path.join('..', output_dir)
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"lineups_{league_name}_{season}.json")
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(lineups_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Gespeichert: {filename} ({len(lineups_data['lineups'])} Aufstellungen)")

def main():
    """Hauptfunktion"""
    print("🚀 Starte Lineup-Scraping für alle Ligen...")
    
    season = get_current_season()
    int_season = get_international_season()
    
    # Alle Ligen
    leagues = [
        ("bundesliga", season),
        ("2bundesliga", season),
        ("dfbpokal", season),
        ("championsleague", int_season),
        ("europaleague", int_season),
        ("conferenceleague", int_season),
        ("england", season),
        ("spain", season),
        ("italy", season),
        ("france", season),
    ]
    
    for league_name, league_season in leagues:
        try:
            lineups_data = scrape_lineups_for_league(league_name, league_season)
            save_lineups_json(league_name, league_season, lineups_data)
        except Exception as e:
            print(f"❌ Fehler bei Liga {league_name}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n✅ Scraping abgeschlossen!")

if __name__ == "__main__":
    main()

