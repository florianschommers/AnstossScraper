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
from typing import List, Dict, Optional, Tuple, Union
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

def get_openligadb_season() -> str:
    """Ermittelt die Saison für OpenLigaDB API (aktuell -1, da OpenLigaDB eine Saison zurück ist)
    Wird für Match-Dateien verwendet, die von OpenLigaDB kommen (bundesliga, 2bundesliga, dfbpokal)"""
    current = get_current_season()
    season_int = int(current) if current.isdigit() else 2025
    return str(season_int - 1)

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

def assign_positions_by_order(players: List[str]) -> List[Dict[str, str]]:
    """
    Ordnet Positionen basierend auf der Reihenfolge zu.
    Regel:
    - Position 0, 1 (erste 2) = "Angriff" (Stürmer)
    - Position 10 (letzter) = "Torwart"
    - Position 7, 8, 9 (3 über dem Torwart) = "Abwehr"
    - Position 2-6 (Rest) = "Mittelfeld"
    
    Gibt Liste von Dicts zurück: [{"name": "Spieler", "position": "Angriff"}, ...]
    """
    if len(players) != 11:
        # Fallback: Wenn nicht genau 11 Spieler, keine Positionen zuordnen
        return [{"name": player, "position": ""} for player in players]
    
    result = []
    for i, player in enumerate(players):
        if i < 2:
            # Erste 2 = Stürmer
            position = "Angriff"
        elif i >= 7 and i < 10:
            # Position 7, 8, 9 = Abwehr
            position = "Abwehr"
        elif i == 10:
            # Letzter = Torwart
            position = "Torwart"
        else:
            # Position 2-6 = Mittelfeld
            position = "Mittelfeld"
        
        result.append({"name": player, "position": position})
    
    return result

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

def find_matchday_for_match(league_path: str, season: str, home_team: str, away_team: str, is_international: bool = False, liga_id: int = 1, phase: str = '') -> Optional[Union[int, str]]:
    """
    Findet den richtigen Spieltag für ein Match, indem durch Spieltage iteriert wird
    und geprüft wird, ob das spezifische Match auf diesem Spieltag ist.
    
    WICHTIG: Prüft nicht nur, ob es zukünftige Spiele gibt, sondern ob das spezifische Match dort ist!
    """
    from team_slug_converter import convert_team_to_slug
    
    now = datetime.now()
    home_slug = convert_team_to_slug(home_team, liga_id, is_international)
    away_slug = convert_team_to_slug(away_team, liga_id, is_international)
    
    if is_international:
        # Internationale Ligen: Prüfe Phasen mit Spieltagen
        if phase in ['gruppenphase', 'league-stage']:
            for matchday in range(1, 21):
                url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/{matchday}/"
                html = fetch_html(url)
                if not html or len(html) < 1000:
                    continue
                
                # Prüfe ob das spezifische Match auf diesem Spieltag ist
                if home_slug and away_slug:
                    # Prüfe beide Varianten (home-away und away-home)
                    if (f"{home_slug}-{away_slug}" in html or f"{away_slug}-{home_slug}" in html):
                        print(f"    📅 Spieltag {matchday} gefunden (Match gefunden auf diesem Spieltag)")
                        return matchday
                # Fallback: Prüfe ob Spiele in der Zukunft sind (wenn Team-Slugs nicht gefunden)
                elif has_future_matches(html, now):
                    print(f"    📅 Spieltag {matchday} gefunden (hat zukünftige Spiele, aber Match nicht verifiziert)")
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
            
            # Prüfe ob das spezifische Match in dieser Runde ist
            if home_slug and away_slug:
                if (f"{home_slug}-{away_slug}" in html or f"{away_slug}-{home_slug}" in html):
                    print(f"    📅 Runde {round_name} gefunden (Match gefunden in dieser Runde)")
                    return round_name
            # Fallback: Prüfe ob Spiele in der Zukunft sind
            elif has_future_matches(html, now):
                print(f"    📅 Runde {round_name} gefunden (hat zukünftige Spiele, aber Match nicht verifiziert)")
                return round_name
    else:
        # Normale Ligen: Iteriere durch Spieltage 1-34
        for matchday in range(1, 35):
            url = f"https://www.fussballdaten.de/{league_path}/{season}/{matchday}/"
            html = fetch_html(url)
            if not html or len(html) < 1000:
                continue
            
            # Prüfe ob das spezifische Match auf diesem Spieltag ist
            if home_slug and away_slug:
                # Prüfe beide Varianten (home-away und away-home)
                if (f"{home_slug}-{away_slug}" in html or f"{away_slug}-{home_slug}" in html):
                    print(f"    📅 Spieltag {matchday} gefunden (Match gefunden auf diesem Spieltag)")
                    return matchday
            # Fallback: Prüfe ob Spiele in der Zukunft sind (wenn Team-Slugs nicht gefunden)
            elif has_future_matches(html, now):
                print(f"    📅 Spieltag {matchday} gefunden (hat zukünftige Spiele, aber Match nicht verifiziert)")
                return matchday
    
    return None

def find_current_matchday(league_path: str, season: str, is_international: bool = False, liga_id: int = 1) -> Optional[Union[int, str]]:
    """
    Findet den aktuellen Spieltag, indem durch Spieltage iteriert wird
    und geprüft wird, ob Spiele in der Zukunft sind.
    
    Gibt den ersten Spieltag zurück, der zukünftige Spiele hat.
    """
    now = datetime.now()
    
    if is_international:
        # Internationale Ligen: Prüfe Phasen mit Spieltagen
        phases_with_matchdays = ['gruppenphase', 'league-stage']
        for phase in phases_with_matchdays:
            for matchday in range(1, 21):
                url = f"https://www.fussballdaten.de/{league_path}/{season}/{phase}/{matchday}/"
                html = fetch_html(url)
                if not html or len(html) < 1000:
                    continue
                
                # Prüfe ob Spiele in der Zukunft sind
                if has_future_matches(html, now):
                    print(f"   📅 Aktueller Spieltag gefunden: {phase} {matchday}")
                    return (phase, matchday)
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
                print(f"   📅 Aktuelle Runde gefunden: {round_name}")
                return round_name
        return None
    else:
        # Normale Ligen: Iteriere durch Spieltage 1-34
        for matchday in range(1, 35):
            url = f"https://www.fussballdaten.de/{league_path}/{season}/{matchday}/"
            html = fetch_html(url)
            if not html or len(html) < 1000:
                continue
            
            # Prüfe ob Spiele in der Zukunft sind
            if has_future_matches(html, now):
                print(f"   📅 Aktueller Spieltag gefunden: {matchday}")
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

def extract_games_with_dates(html: str) -> List[Dict]:
    """
    Extrahiert alle Spiele mit Datum und Status (gespielt/nicht gespielt) aus HTML.
    Gibt Liste von Dicts zurück: [{"datum": datetime, "gespielt": bool}, ...]
    """
    spiele = []
    
    # Pattern für Spiele mit Datum: title="Team1 - Team2 (DD.MM.YYYY) ..."
    # Kann gefolgt sein von: <span>HH:MM</span> (nicht gespielt) ODER Endergebnis (gespielt)
    
    # Pattern 1: Nicht gespielte Spiele (mit Uhrzeit)
    zukunft_pattern = re.compile(
        r'title="[^"]*\((\d{2})\.(\d{2})\.(\d{4})[^)]*\)"[^>]*>[\s\S]*?<span>(\d{2}:\d{2})</span>',
        re.IGNORECASE
    )
    
    for match in zukunft_pattern.finditer(html):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        
        try:
            spiel_datum = datetime(year, month, day)
            spiele.append({
                "datum": spiel_datum,
                "gespielt": False
            })
        except:
            continue
    
    # Pattern 2: Gespielte Spiele (mit Endergebnis, ohne Uhrzeit)
    # Suche nach Datum in title-Attribut und prüfe ob danach ein Ergebnis kommt
    gespielt_pattern = re.compile(
        r'title="[^"]*\((\d{2})\.(\d{2})\.(\d{4})[^)]*\)"[^>]*>[\s\S]*?<div[^>]*class="[^"]*ergebnis[^"]*"[^>]*>(\d+:\d+)</div>',
        re.IGNORECASE
    )
    
    for match in gespielt_pattern.finditer(html):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        
        try:
            spiel_datum = datetime(year, month, day)
            spiele.append({
                "datum": spiel_datum,
                "gespielt": True
            })
        except:
            continue
    
    # Pattern 3: Live-Spiele (zählen als "nicht gespielt")
    live_pattern = re.compile(
        r'title="[^"]*\((\d{2})\.(\d{2})\.(\d{4})[^)]*\)"[^>]*>[\s\S]*?<div[^>]*class="[^"]*ergebnis[^"]*live[^"]*"',
        re.IGNORECASE
    )
    
    for match in live_pattern.finditer(html):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        
        try:
            spiel_datum = datetime(year, month, day)
            spiele.append({
                "datum": spiel_datum,
                "gespielt": False
            })
        except:
            continue
    
    return spiele

def find_matchdays_to_scrape(league_path: str, season: str, is_international: bool = False, liga_id: int = 1) -> List[Union[int, str]]:
    """
    Findet alle Spieltage, die gescrapt werden sollen:
    - Alle Spieltage mit Spielen innerhalb von HEUTE + 7 Tage
    - Nachholspiele (erkannt durch > 6 Tage Abstand zu gespielten Spielen)
    
    Gibt Liste von Spieltagen zurück: [16, 17, 18] oder ["achtelfinale", "viertelfinale"] für DFB-Pokal
    """
    heute = datetime.now()
    spieltage_zum_scrapen = []
    nachholspiel_spieltage = []
    
    # Bestimme Spieltag-Range basierend auf Liga
    if is_international:
        # Internationale Ligen: Nicht implementiert (behalten alte Logik)
        return None
    elif liga_id == 3:  # DFB-Pokal
        # DFB-Pokal: Runden-Namen
        spieltag_range = ['1-runde', '2-runde', 'achtelfinale', 'viertelfinale', 'halbfinale', 'finale']
    elif liga_id in [51, 41, 31]:  # England, Spanien, Italien
        # 20 Teams = 38 Spieltage
        spieltag_range = range(1, 39)
    elif liga_id == 21:  # Frankreich
        # 18 Teams = 34 Spieltage
        spieltag_range = range(1, 35)
    else:  # Bundesliga, 2. Bundesliga
        # 18 Teams = 34 Spieltage
        spieltag_range = range(1, 35)
    
    print(f"\n🔍 Suche Spieltage zum Scrapen (7-Tage-Fenster)...")
    
    for spieltag in spieltag_range:
        url = f"https://www.fussballdaten.de/{league_path}/{season}/{spieltag}/"
        html = fetch_html(url)
        
        if not html or len(html) < 1000:
            continue
        
        # Extrahiere alle Spiele mit Datum
        alle_spiele = extract_games_with_dates(html)
        
        if not alle_spiele:
            continue
        
        # Gruppiere nach gespielt/nicht gespielt
        gespielte = [s for s in alle_spiele if s['gespielt']]
        nicht_gespielte = [s for s in alle_spiele if not s['gespielt']]
        
        # Keine zukünftigen Spiele → Spieltag fertig
        if not nicht_gespielte:
            continue
        
        # Fall 1: Es gibt sowohl gespielte als auch nicht gespielte Spiele
        # → Prüfe auf Nachholspiele (> 6 Tage Abstand)
        if gespielte and nicht_gespielte:
            letztes_gespielt = max(s['datum'] for s in gespielte)
            erstes_nicht_gespielt = min(s['datum'] for s in nicht_gespielte)
            
            abstand_spiele = (erstes_nicht_gespielt - letztes_gespielt).days
            
            if abstand_spiele > 6:
                # NACHHOLSPIELE erkannt!
                print(f"   ⚠️ Spieltag {spieltag}: Nachholspiele erkannt (+{abstand_spiele} Tage)")
                nachholspiel_spieltage.append(spieltag)
                # Weiter zum nächsten Spieltag (aber Nachholspiele merken!)
                continue
        
        # Fall 2: Prüfe Abstand zu heute
        erstes_nicht_gespielt = min(s['datum'] for s in nicht_gespielte)
        abstand_heute = (erstes_nicht_gespielt.date() - heute.date()).days
        
        if abstand_heute <= 7:
            print(f"   ✅ Spieltag {spieltag}: Innerhalb 7 Tage (+{abstand_heute} Tage)")
            spieltage_zum_scrapen.append(spieltag)
        else:
            print(f"   ⛔ Spieltag {spieltag}: Zu weit weg (+{abstand_heute} Tage) → STOPP")
            break  # Stoppe Iteration
    
    # Kombiniere: Nachholspiele + reguläre Spieltage
    alle_spieltage = nachholspiel_spieltage + spieltage_zum_scrapen
    
    if nachholspiel_spieltage:
        print(f"\n   📋 Nachholspiel-Spieltage: {nachholspiel_spieltage}")
    print(f"   📋 Reguläre Spieltage: {spieltage_zum_scrapen}")
    print(f"   📊 Gesamt zum Scrapen: {alle_spieltage}\n")
    
    return alle_spieltage

def scrape_lineup_for_match(league_path: str, season: str, phase: str, matchday: Optional[int], home_team: str, away_team: str, is_international: bool = False, liga_id: int = 1) -> Optional[Tuple[List[str], List[str], bool]]:
    """Scrapt Aufstellung für ein einzelnes Spiel - OPTIMIERT: Testet zuerst nur ±2 Spieltage, dann alle anderen"""
    # Erstelle Team-Slugs mit der korrekten Konvertierungs-Logik
    home_slug = convert_team_to_slug(home_team, liga_id, is_international)
    away_slug = convert_team_to_slug(away_team, liga_id, is_international)
    
    print(f"    🔍 Team-Slugs: '{home_team}' → '{home_slug}', '{away_team}' → '{away_slug}'")
    print(f"    📋 Spieltag: {matchday}, Phase: {phase}, Liga-ID: {liga_id}, International: {is_international}")
    
    if not home_slug or not away_slug:
        print(f"    ❌ Konnte Team-Slugs nicht erstellen: {home_team} → {home_slug}, {away_team} → {away_slug}")
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
        # WICHTIG: Nur die aktuelle Phase verwenden (z.B. gruppenphase 5, nicht alle Phasen)
        first_rounds_to_test = []
        if matchday and phase:
            first_rounds_to_test.append((phase, matchday))
        elif phase:
            # Phase ohne Spieltag (z.B. achtelfinale)
            first_rounds_to_test.append((phase, None))
    elif liga_id == 3:  # DFB-Pokal
        # DFB-Pokal: Teste zuerst spezifische Runde (kein ±1, da Runden-Namen sind)
        first_rounds_to_test = []
        if matchday and isinstance(matchday, str):
            dfb_rounds = ["1-runde", "2-runde", "achtelfinale", "viertelfinale", "halbfinale", "finale"]
            if matchday in dfb_rounds:
                first_rounds_to_test.append(matchday)
    else:
        # Normale Ligen: Teste zuerst nur den spezifischen Spieltag (kein ±1, da wir den richtigen Spieltag haben)
        first_rounds_to_test = []
        if matchday:
            try:
                base_matchday = int(matchday) if isinstance(matchday, (int, str)) else 1
                # OPTIMIERT: Nur den spezifischen Spieltag testen (kein ±1, da matchday bereits korrekt ist)
                first_rounds_to_test = [str(base_matchday)]
            except:
                first_rounds_to_test = []
    
    # Phase 1: Teste zuerst nur ±1 Spieltag (schnell!)
    print(f"    📅 Phase 1: Teste {len(first_rounds_to_test)} Spieltage/Runden: {first_rounds_to_test}")
    for round_value in first_rounds_to_test:
        if is_international:
            test_phase, test_matchday = round_value
            if test_matchday:
                base_url = f"https://www.fussballdaten.de/{league_path}/{season}/{test_phase}/{test_matchday}"
            else:
                base_url = f"https://www.fussballdaten.de/{league_path}/{season}/{test_phase}"
            urls = [
                f"{base_url}/{home_slug}-{away_slug}/",
                f"{base_url}/{away_slug}-{home_slug}/"
            ]
        else:
            # Deutsche/ausländische Ligen
            urls = [
                f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{home_slug}-{away_slug}/",
                f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{away_slug}-{home_slug}/"
            ]
        
        for url in urls:
            print(f"    🌐 Teste URL: {url}")
            html = fetch_html(url)
            
            if not html:
                print(f"    ⚠️ HTML ist None/leer für {url}")
                continue
            
            if "heim-content" not in html or "gast-content" not in html:
                print(f"    ⚠️ HTML hat keine heim-content/gast-content (Länge: {len(html)})")
                # Prüfe ob es eine 404 oder andere Fehlerseite ist
                if "404" in html or "nicht gefunden" in html.lower():
                    print(f"    ❌ 404-Fehler für {url}")
                continue
            
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
                    print(f"    ✅ Aufstellung erfolgreich geparst! (Home-First: {is_home_first})")
                    # Prüfe ob Positionen zugeordnet werden sollen (nicht für Bundesliga/2. Bundesliga/DFB-Pokal)
                    assign_positions = liga_id not in [1, 2, 3]  # Nicht für 1. Bundesliga, 2. Bundesliga und DFB-Pokal
                    if is_home_first:
                        return (heim_start11, gast_start11, assign_positions)
                    else:
                        return (gast_start11, heim_start11, assign_positions)
                else:
                    print(f"    ⚠️ Aufstellungsseite gefunden, aber Parsing fehlgeschlagen (Heim: {len(heim_start11)}, Gast: {len(gast_start11)})")
                # Wenn Parsing fehlschlägt, versuche nächste URL (aber nicht nächsten Spieltag!)
    
    # Phase 2: Teste ±1 Spieltag, wenn Phase 1 fehlgeschlagen ist (nur für normale Ligen)
    # WICHTIG: ±1 ist okay, wenn das Match nicht auf dem erwarteten Spieltag gefunden wird
    fallback_matchdays = []
    if not is_international and liga_id != 3 and matchday:
        try:
            base_matchday = int(matchday) if isinstance(matchday, (int, str)) else 1
            # Teste ±1 (base-1, base+1) - aber nur wenn Phase 1 fehlgeschlagen ist
            if base_matchday - 1 >= 1 and str(base_matchday - 1) not in first_rounds_to_test:
                fallback_matchdays.append(str(base_matchday - 1))
            if base_matchday + 1 < 35 and str(base_matchday + 1) not in first_rounds_to_test:
                fallback_matchdays.append(str(base_matchday + 1))
        except:
            fallback_matchdays = []
        
        if fallback_matchdays:
            print(f"    ⚠️ Phase 1 fehlgeschlagen, teste jetzt ±1 Spieltag: {fallback_matchdays}")
            for round_value in fallback_matchdays:
                urls = [
                    f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{home_slug}-{away_slug}/",
                    f"https://www.fussballdaten.de/{league_path}/{season}/{round_value}/{away_slug}-{home_slug}/"
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
                            # Sofort abbrechen wenn gefunden!
                            is_home_first = f"{home_slug}-{away_slug}" in url
                            # Prüfe ob Positionen zugeordnet werden sollen (nicht für Bundesliga/2. Bundesliga/DFB-Pokal)
                            assign_positions = liga_id not in [1, 2, 3]  # Nicht für 1. Bundesliga, 2. Bundesliga und DFB-Pokal
                            if is_home_first:
                                return (heim_start11, gast_start11, assign_positions)
                            else:
                                return (gast_start11, heim_start11, assign_positions)
    
    # Beide Phasen fehlgeschlagen
    total_tested = len(first_rounds_to_test) + len(fallback_matchdays)
    print(f"    ❌ FEHLER: Keine Aufstellung gefunden!")
    print(f"    📊 Getestet: {total_tested} Spieltage/Runden")
    print(f"    📋 Phase 1: {len(first_rounds_to_test)} Spieltage/Runden")
    if fallback_matchdays:
        print(f"    📋 Phase 2: {len(fallback_matchdays)} Spieltage/Runden")
    print(f"    🏠 Team-Slugs: {home_slug} vs {away_slug}")
    print(f"    📅 Matchday: {matchday}, Phase: {phase}")
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
    # WICHTIG: Deutsche Ligen verwenden leeren season-String für Dateinamen
    display_season = season if season else "aktuell"
    print(f"\n{'='*60}")
    print(f"🏆 Liga: {league_name} (Saison {display_season})")
    print(f"{'='*60}")
    
    # Stelle sicher, dass das Verzeichnis relativ zum Repository-Root ist
    # Wenn wir im scraper/ Verzeichnis sind, gehen wir ein Verzeichnis nach oben
    if os.path.basename(os.getcwd()) == 'scraper':
        data_dir = os.path.join('..', data_dir)
    
    # Lade Matches
    # WICHTIG: ALLE Ligen verwenden jetzt Dateinamen OHNE Saison
    match_file = os.path.join(data_dir, f"matches_{league_name}.json")
    if not os.path.exists(match_file):
        print(f"⚠️ Match-Datei nicht gefunden: {match_file}")
        return {"league": league_name, "season": season if season else get_current_season(), "lineups": []}
    
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
    
    # WICHTIG: Für Scraping-URLs (fussballdaten.de) verwende Saison +1
    # ALLE Ligen: season ist leer für Dateinamen, aber für Scraping-URLs brauchen wir die aktuelle Saison
    if league_name in ["bundesliga", "2bundesliga", "dfbpokal"]:
        # Deutsche Ligen: Hole aktuelle Saison für Scraping-URLs
        scraping_season = get_current_season()
        # WICHTIG: Alle deutschen Ligen verwenden die aktuelle Saison für Scraping-URLs (kein +1 mehr)
        print(f"   ℹ️ Match-Datei: matches_{league_name}.json, Scraping Saison: {scraping_season}")
    elif league_name in ["championsleague", "europaleague", "conferenceleague"]:
        # Internationale Ligen: Verwende internationale Saison für Scraping-URLs
        scraping_season = get_international_season()
        print(f"   ℹ️ Match-Datei: matches_{league_name}.json, Scraping Saison: {scraping_season}")
    else:
        # Andere Ligen (england, spain, italy, france): Verwende aktuelle Saison für Scraping-URLs
        scraping_season = get_current_season()
        print(f"   ℹ️ Match-Datei: matches_{league_name}.json, Scraping Saison: {scraping_season}")
    
    # WICHTIG: Finde alle Spieltage innerhalb 7 Tage + Nachholspiele
    # Für internationale Ligen: Verwende alte Logik (find_current_matchday)
    if is_international:
        print(f"\n🔍 Suche aktuellen Spieltag (Internationale Liga)...")
        current_matchday = find_current_matchday(league_path, scraping_season, is_international, liga_id)
        spieltage_zum_scrapen = [current_matchday] if current_matchday else []
        if current_matchday:
            print(f"✅ Aktueller Spieltag: {current_matchday}")
        else:
            print(f"⚠️ Kein aktueller Spieltag gefunden")
    else:
        # Normale Ligen: Verwende neue 7-Tage-Logik
        spieltage_zum_scrapen = find_matchdays_to_scrape(league_path, scraping_season, is_international, liga_id)
        if not spieltage_zum_scrapen:
            print(f"⚠️ Keine Spieltage zum Scrapen gefunden")
    
    # Filtere Matches nach gefundenen Spieltagen (kann mehrere sein!)
    filtered_matches = []
    original_matches = matches.copy()  # Speichere Original-Matches für Fallback
    
    if spieltage_zum_scrapen:
        print(f"   🔍 Filtere Matches für Spieltage: {spieltage_zum_scrapen}...")
        matchday_counts = {}  # Debug: Zähle Matchdays
        for match in matches:
            # Extrahiere Matchday aus Match
            team1 = match.get('Team1') or match.get('team1') or {}
            team2 = match.get('Team2') or match.get('team2') or {}
            
            # Initialisiere Variablen
            matchday = None
            phase = ''
            
            if isinstance(team1, dict) and isinstance(team2, dict):
                # OpenLigaDB Format: Prüfe verschiedene mögliche Felder für Matchday
                # WICHTIG: OpenLigaDB verwendet 'group' (kleingeschrieben), nicht 'Group'!
                
                # Versuche group.groupOrderID (für OpenLigaDB - kleingeschrieben!)
                group_obj = match.get('group') or match.get('Group')
                if group_obj and isinstance(group_obj, dict):
                    matchday = group_obj.get('groupOrderID') or group_obj.get('GroupOrderID')
                    phase = group_obj.get('groupName') or group_obj.get('GroupName') or ''
                
                # Versuche direktes Matchday-Feld (verschiedene Schreibweisen)
                if not matchday:
                    matchday = (match.get('Matchday') or match.get('matchday') or 
                               match.get('MatchDay') or match.get('matchDay') or
                               match.get('GroupOrderID') or match.get('groupOrderID'))
                
                # Versuche aus League-Objekt
                if not matchday:
                    league_obj = match.get('League') or match.get('league')
                    if league_obj and isinstance(league_obj, dict):
                        matchday = league_obj.get('GroupOrderID') or league_obj.get('groupOrderID')
                
                # Phase extrahieren (falls noch nicht gesetzt)
                if not phase:
                    group_obj = match.get('group') or match.get('Group')
                    if group_obj and isinstance(group_obj, dict):
                        phase = group_obj.get('groupName') or group_obj.get('GroupName') or ''
                    if not phase:
                        phase = match.get('phase', '')
                
                # DEBUG: Zeige Match-Struktur beim ersten Match
                if len(matchday_counts) == 0:
                    print(f"   🔍 DEBUG: Erster Match Keys: {list(match.keys())[:15]}")
                    group_obj = match.get('group') or match.get('Group')
                    if group_obj:
                        print(f"   🔍 DEBUG: group Keys: {list(group_obj.keys()) if isinstance(group_obj, dict) else 'N/A'}")
                    league_obj = match.get('League') or match.get('league')
                    if league_obj:
                        print(f"   🔍 DEBUG: League Keys: {list(league_obj.keys()) if isinstance(league_obj, dict) else 'N/A'}")
            else:
                matchday = match.get('matchday', None)
                phase = match.get('phase', '')
            
            # Debug: Zähle Matchdays
            matchday_key = str(matchday) if matchday is not None else 'None'
            matchday_counts[matchday_key] = matchday_counts.get(matchday_key, 0) + 1
            
            # Prüfe ob Match zu einem der gewünschten Spieltage gehört
            if is_international:
                # International: spieltage_zum_scrapen enthält (phase, matchday) Tupel
                for spieltag in spieltage_zum_scrapen:
                    if isinstance(spieltag, tuple):
                        target_phase, target_matchday_num = spieltag
                        if phase == target_phase and matchday == target_matchday_num:
                            filtered_matches.append(match)
                            break
            elif liga_id == 3:
                # DFB-Pokal: spieltage_zum_scrapen enthält Runden-Namen (Strings)
                if matchday in spieltage_zum_scrapen:
                    filtered_matches.append(match)
            else:
                # Normale Ligen: spieltage_zum_scrapen enthält Integers
                # Konvertiere matchday zu Integer für Vergleich (kann String oder Integer sein)
                try:
                    matchday_int = int(matchday) if matchday is not None else None
                    if matchday_int is not None and matchday_int in spieltage_zum_scrapen:
                        filtered_matches.append(match)
                except (ValueError, TypeError):
                    # Wenn matchday nicht konvertierbar ist, überspringe dieses Match
                    pass
        
        # Debug: Zeige Matchday-Verteilung
        print(f"   📊 Matchday-Verteilung in Match-Datei: {dict(sorted(matchday_counts.items(), key=lambda x: int(x[0]) if x[0] != 'None' and x[0].isdigit() else 999))}")
        
        original_count = len(matches)
        matches = filtered_matches
        print(f"📊 Gefiltert: {len(matches)} Matches für Spieltage {spieltage_zum_scrapen} (von {original_count} total)")
        
        # WICHTIG: Wenn keine Matches gefiltert wurden, aber spieltage_zum_scrapen gefunden wurden,
        # dann haben die Matches wahrscheinlich kein Matchday-Feld. In diesem Fall
        # filtern wir die Matches, indem wir für jedes Match prüfen, ob es zu einem Spieltag gehört.
        if len(matches) == 0 and original_count > 0:
            print(f"⚠️ WARNUNG: Keine Matches mit Matchday-Feld gefunden!")
            print(f"   → Prüfe für jedes Match, ob es zu Spieltagen {spieltage_zum_scrapen} gehört...")
            filtered_by_matchday_check = []
            for match in original_matches[:10]:  # Teste erstmal nur die ersten 10
                # WICHTIG: Prüfe zuerst, ob homeTeam/awayTeam existieren (andere Formate)
                if 'homeTeam' in match and 'awayTeam' in match:
                    home_team = match.get('homeTeam', '')
                    away_team = match.get('awayTeam', '')
                else:
                    # OpenLigaDB Format: Team1/Team2 sind Objekte mit TeamName
                    team1 = match.get('Team1') or match.get('team1')
                    team2 = match.get('Team2') or match.get('team2')
                    if team1 and team2 and isinstance(team1, dict) and isinstance(team2, dict):
                        home_team = (team1.get('TeamName') or team1.get('teamName') or 
                                    team1.get('name') or team1.get('Name') or '')
                        away_team = (team2.get('TeamName') or team2.get('teamName') or 
                                    team2.get('name') or team2.get('Name') or '')
                    else:
                        home_team = (team1 if isinstance(team1, str) else '') or match.get('homeTeam', '')
                        away_team = (team2 if isinstance(team2, str) else '') or match.get('awayTeam', '')
                
                if home_team and away_team:
                    # Prüfe ob dieses Match zum aktuellen Spieltag gehört
                    found_matchday = find_matchday_for_match(
                        league_path, scraping_season, home_team, away_team, is_international, liga_id, ''
                    )
                    if found_matchday in spieltage_zum_scrapen:
                        filtered_by_matchday_check.append(match)
            
            if len(filtered_by_matchday_check) > 0:
                print(f"   ✅ {len(filtered_by_matchday_check)} Matches gefunden, die zu Spieltagen {spieltage_zum_scrapen} gehören")
                print(f"   → Scrapte nur diese Matches (nicht alle {original_count})")
                matches = filtered_by_matchday_check
            else:
                print(f"   ⚠️ Keine Matches zu Spieltagen {spieltage_zum_scrapen} gefunden, verwende alle {original_count} Matches")
                matches = original_matches
    else:
        print(f"⚠️ Kein aktueller Spieltag gefunden, verwende alle {len(matches)} Matches")
    
    # Zeige alle Matches zu Beginn aufgelistet
    print(f"\n📋 Alle Matches die gescrappt werden sollen:")
    print(f"{'='*60}")
    parsed_matches_preview = []
    for i, match in enumerate(matches, 1):
        # Extrahiere Match-Info (gleiche Logik wie im Loop)
        # WICHTIG: Prüfe zuerst, ob homeTeam/awayTeam existieren (andere Formate)
        # Dann prüfe Team1/Team2 (OpenLigaDB Format)
        if 'homeTeam' in match and 'awayTeam' in match:
            # Andere Formate: Direkte Strings
            home_team = match.get('homeTeam', '')
            away_team = match.get('awayTeam', '')
            matchday = match.get('matchday', None)
            phase = match.get('phase', '')
        else:
            # OpenLigaDB Format: Team1/Team2 sind Objekte mit TeamName
            team1 = match.get('Team1') or match.get('team1')
            team2 = match.get('Team2') or match.get('team2')
            
            if team1 and team2 and isinstance(team1, dict) and isinstance(team2, dict):
                home_team = (team1.get('TeamName') or team1.get('teamName') or 
                            team1.get('name') or team1.get('Name') or '')
                away_team = (team2.get('TeamName') or team2.get('teamName') or 
                            team2.get('name') or team2.get('Name') or '')
                matchday = None
                if match.get('Group') and isinstance(match.get('Group'), dict):
                    matchday = match.get('Group').get('GroupOrderID')
                if not matchday:
                    matchday = match.get('Matchday') or match.get('matchday')
                phase = ''
                if match.get('Group') and isinstance(match.get('Group'), dict):
                    phase = match.get('Group').get('GroupName') or ''
                if not phase:
                    phase = match.get('phase', '')
            else:
                # Fallback: Versuche als Strings
                home_team = (team1 if isinstance(team1, str) else '') or match.get('homeTeam', '')
                away_team = (team2 if isinstance(team2, str) else '') or match.get('awayTeam', '')
                matchday = match.get('matchday', None)
                phase = match.get('phase', '')
        
        if home_team and away_team:
            match_info = f"  [{i:3d}/{len(matches)}] {home_team} vs {away_team}"
            if matchday:
                match_info += f" (Spieltag: {matchday})"
            if phase:
                match_info += f" (Phase: {phase})"
            parsed_matches_preview.append(match_info)
    
    # Zeige alle Matches (maximal 50, sonst zusammenfassen)
    if len(parsed_matches_preview) <= 50:
        for match_info in parsed_matches_preview:
            print(match_info)
    else:
        # Zeige erste 25 und letzte 25
        for match_info in parsed_matches_preview[:25]:
            print(match_info)
        print(f"  ... ({len(parsed_matches_preview) - 50} weitere Matches ausgelassen) ...")
        for match_info in parsed_matches_preview[-25:]:
            print(match_info)
    
    print(f"{'='*60}\n")
    
    lineups = []
    successful = 0
    failed = 0
    failed_matches = []  # Sammle fehlgeschlagene Spiele für Analyse
    
    # Speichere ersten Spieltag für Fallback, wenn find_matchday_for_match fehlschlägt
    saved_first_matchday = spieltage_zum_scrapen[0] if spieltage_zum_scrapen else None
    
    for i, match in enumerate(matches, 1):
        # WICHTIG: Prüfe zuerst, ob homeTeam/awayTeam existieren (andere Formate)
        # Dann prüfe Team1/Team2 (OpenLigaDB Format)
        if 'homeTeam' in match and 'awayTeam' in match:
            # Andere Formate: Direkte Strings
            home_team = match.get('homeTeam', '')
            away_team = match.get('awayTeam', '')
            date_time = match.get('dateTime', '')
            matchday = match.get('matchday', None)
            phase = match.get('phase', '')
        else:
            # OpenLigaDB Format: Team1/Team2 sind Objekte mit TeamName
            team1 = match.get('Team1') or match.get('team1')
            team2 = match.get('Team2') or match.get('team2')
            
            if team1 and team2 and isinstance(team1, dict) and isinstance(team2, dict):
                # OpenLigaDB Format: Extrahiere TeamName aus Objekten
                home_team = (team1.get('TeamName') or team1.get('teamName') or 
                            team1.get('name') or team1.get('Name') or '')
                away_team = (team2.get('TeamName') or team2.get('teamName') or 
                            team2.get('name') or team2.get('Name') or '')
                date_time = match.get('MatchDateTime') or match.get('matchDateTime') or match.get('dateTime', '')
                
                # OpenLigaDB: Spieltag kann in Group.GroupOrderID oder Matchday sein
                matchday = None
                if match.get('Group') and isinstance(match.get('Group'), dict):
                    matchday = match.get('Group').get('GroupOrderID')
                if not matchday:
                    matchday = match.get('Matchday') or match.get('matchday')
                
                # Phase für DFB-Pokal (z.B. "achtelfinale", "viertelfinale")
                phase = ''
                if match.get('Group') and isinstance(match.get('Group'), dict):
                    phase = match.get('Group').get('GroupName') or ''
                if not phase:
                    phase = match.get('phase', '')
            else:
                # Fallback: Versuche als Strings
                home_team = (team1 if isinstance(team1, str) else '') or match.get('homeTeam', '')
                away_team = (team2 if isinstance(team2, str) else '') or match.get('awayTeam', '')
                date_time = match.get('dateTime', '')
                matchday = match.get('matchday', None)
                phase = match.get('phase', '')
        
        print(f"\n[{i}/{len(matches)}] {home_team} vs {away_team}")
        
        # STEP 1: Finde den richtigen Spieltag, NUR wenn nicht vorhanden oder unsicher
        # WICHTIG: Wenn matchday bereits vorhanden und > 1, verwende ihn direkt (nicht neu suchen!)
        if not matchday:
            print(f"    🔍 Suche richtigen Spieltag...")
            found_matchday = find_matchday_for_match(
                league_path, scraping_season, home_team, away_team, is_international, liga_id, phase
            )
            if found_matchday:
                matchday = found_matchday
                print(f"    ✅ Spieltag gefunden: {matchday}")
            else:
                # Fallback: Wenn kein Spieltag gefunden wurde, aber wir bereits einen saved_first_matchday haben, verwende diesen
                if saved_first_matchday:
                    matchday = saved_first_matchday
                    print(f"    ⚠️ Spieltag nicht gefunden, verwende ersten Spieltag: {matchday}")
                else:
                    print(f"    ⚠️ Spieltag nicht gefunden, verwende vorhandenen: {matchday}")
        elif matchday == 1 and liga_id == 3:  # Nur für DFB-Pokal: matchday=1 ist oft falsch
            print(f"    🔍 Suche richtigen Spieltag (DFB-Pokal matchday=1 ist oft falsch)...")
            found_matchday = find_matchday_for_match(
                league_path, scraping_season, home_team, away_team, is_international, liga_id, phase
            )
            if found_matchday:
                matchday = found_matchday
                print(f"    ✅ Spieltag gefunden: {matchday}")
            else:
                # Fallback: Wenn kein Spieltag gefunden wurde, aber wir bereits einen saved_first_matchday haben, verwende diesen
                if saved_first_matchday:
                    matchday = saved_first_matchday
                    print(f"    ⚠️ Spieltag nicht gefunden, verwende ersten Spieltag: {matchday}")
                else:
                    print(f"    ⚠️ Spieltag nicht gefunden, verwende vorhandenen: {matchday}")
        else:
            # Spieltag ist bereits vorhanden und > 1, verwende ihn direkt
            print(f"    📅 Verwende vorhandenen Spieltag: {matchday}")
        
        # Scrapte Aufstellung (testet automatisch ±1 Spieltag)
        # WICHTIG: Verwende scraping_season für fussballdaten.de URLs
        lineup = scrape_lineup_for_match(
            league_path, scraping_season, phase, matchday,
            home_team, away_team, is_international, liga_id
        )
        
        if lineup:
            home_players, away_players, assign_positions = lineup
            
            # Ordne Positionen zu, wenn nicht Bundesliga/2. Bundesliga/DFB-Pokal
            if assign_positions:
                home_lineup_with_positions = assign_positions_by_order(home_players)
                away_lineup_with_positions = assign_positions_by_order(away_players)
                # Prüfe ob alle Positionen zugeordnet wurden
                home_positions_count = len([p for p in home_lineup_with_positions if p.get('position')])
                away_positions_count = len([p for p in away_lineup_with_positions if p.get('position')])
                print(f"  📍 Positionen zugeordnet: Heim {home_positions_count}/{len(home_players)}, Auswärts {away_positions_count}/{len(away_players)}")
            else:
                # Für Bundesliga/2. Bundesliga/DFB-Pokal: Nur Namen (wie bisher, einfache Liste)
                home_lineup_with_positions = home_players
                away_lineup_with_positions = away_players
            
            lineups.append({
                "homeTeam": home_team,
                "awayTeam": away_team,
                "dateTime": date_time,
                "matchday": matchday,
                "phase": phase,
                "homeLineup": home_lineup_with_positions,
                "awayLineup": away_lineup_with_positions
            })
            successful += 1
            print(f"  ✅ Aufstellung gescrappt: {len(home_players)} Heim, {len(away_players)} Auswärts")
        else:
            failed += 1
            print(f"  ❌ Aufstellung nicht gefunden für: {home_team} vs {away_team}")
            print(f"     Matchday: {matchday}, Phase: {phase}")
            # Sammle für spätere Analyse
            failed_matches.append({
                "homeTeam": home_team,
                "awayTeam": away_team,
                "matchday": matchday,
                "phase": phase,
                "dateTime": date_time
            })
    
    print(f"\n{'='*60}")
    print(f"📊 ZUSAMMENFASSUNG für {league_name} (Saison {season}):")
    print(f"✅ Erfolgreich: {successful}")
    print(f"❌ Fehlgeschlagen: {failed}")
    if failed > 0:
        print(f"\n⚠️ {failed} Spiele konnten nicht gefunden werden!")
        print(f"   Bitte prüfe die Logs oben für Details zu jedem fehlgeschlagenen Spiel.")
        # Speichere fehlgeschlagene Spiele in Datei für Analyse
        if os.path.basename(os.getcwd()) == 'scraper':
            failed_file = os.path.join('..', 'data', 'lineups', f'failed_{league_name}.json')
        else:
            failed_file = os.path.join('data', 'lineups', f'failed_{league_name}.json')
        os.makedirs(os.path.dirname(failed_file), exist_ok=True)
        with open(failed_file, 'w', encoding='utf-8') as f:
            json.dump({
                "league": league_name,
                "season": season,
                "failedCount": failed,
                "failedMatches": failed_matches,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
        print(f"   💾 Fehlgeschlagene Spiele gespeichert in: {failed_file}")
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
    filename = os.path.join(output_dir, f"lineups_{league_name}.json")
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(lineups_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Gespeichert: {filename} ({len(lineups_data['lineups'])} Aufstellungen)")

def main():
    """Hauptfunktion"""
    print("🚀 Starte Lineup-Scraping für alle Ligen...")
    
    # WICHTIG: ALLE Ligen verwenden jetzt Dateinamen OHNE Saison
    # fussballdaten.de verwendet Saison +1 (z.B. 2026 statt 2025) für Scraping-URLs
    season = get_current_season()  # Für fussballdaten.de URLs (Scraping)
    int_season = get_international_season()
    
    # Alle Ligen
    # WICHTIG: season wird nur für Scraping-URLs verwendet, NICHT für Dateinamen
    # Alle Dateinamen sind OHNE Jahreszahl (matches_england.json, matches_championsleague.json, etc.)
    leagues = [
        ("bundesliga", ""),  # 1. Bundesliga: Dateiname OHNE Saison
        ("2bundesliga", ""),  # 2. Bundesliga: Dateiname OHNE Saison
        ("dfbpokal", ""),  # DFB-Pokal: Dateiname OHNE Saison
        ("championsleague", ""),  # Champions League: Dateiname OHNE Saison
        ("europaleague", ""),  # Europa League: Dateiname OHNE Saison
        ("conferenceleague", ""),  # Conference League: Dateiname OHNE Saison
        ("england", ""),  # England: Dateiname OHNE Saison
        ("spain", ""),  # Spain: Dateiname OHNE Saison
        ("italy", ""),  # Italy: Dateiname OHNE Saison
        ("france", ""),  # France: Dateiname OHNE Saison
    ]
    
    for league_name, league_season in leagues:
        try:
            lineups_data = scrape_lineups_for_league(league_name, league_season)
            # Für deutsche Ligen: Verwende aktuelle Saison für Lineup-Dateinamen
            save_season = league_season if league_season else get_current_season()
            save_lineups_json(league_name, save_season, lineups_data)
        except Exception as e:
            print(f"❌ Fehler bei Liga {league_name}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n✅ Scraping abgeschlossen!")

if __name__ == "__main__":
    main()

