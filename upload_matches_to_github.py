#!/usr/bin/env python3
"""
Script zum Hochladen von Match-Daten (2. Bundesliga und DFB-Pokal) in GitHub Repository
"""

import requests
import json
import os
import time
from datetime import datetime
from typing import List, Dict, Optional

# GitHub Repository Konfiguration
GITHUB_REPO = "florianschommers/AnstossScraper"
# Token aus Umgebungsvariable (für GitHub Actions) - KEIN Fallback, muss gesetzt sein
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN Umgebungsvariable muss gesetzt sein!")
GITHUB_API_BASE = "https://api.github.com/repos"

# Authorization Header - unterstützt sowohl 'token' als auch 'Bearer' Format
def get_headers(token: str):
    """Erstellt Header mit korrektem Authorization-Format"""
    # Prüfe ob Token bereits 'Bearer' oder 'token' Präfix hat
    if token.startswith('Bearer ') or token.startswith('token '):
        auth_header = token
    else:
        # Standard: verwende 'Bearer' für GitHub Actions, 'token' als Fallback
        auth_header = f'Bearer {token}'
    
    return {
        'Authorization': auth_header,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Anstoss-Match-Uploader'
    }

def get_current_season() -> str:
    """Ermittelt die aktuelle Saison (August - Juli)"""
    now = datetime.now()
    if now.month >= 7:  # Ab Juli
        return str(now.year + 1)
    else:
        return str(now.year)

def get_openligadb_season() -> str:
    """Ermittelt die Saison für OpenLigaDB API (aktuell -1, da OpenLigaDB eine Saison zurück ist)"""
    current = get_current_season()
    season_int = int(current) if current.isdigit() else 2025
    return str(season_int - 1)

def fetch_openligadb_matches(league_shortcut: str, season: str) -> List[Dict]:
    """Holt Match-Daten von der OpenLigaDB API"""
    all_matches = []
    
    try:
        api_url = f"https://api.openligadb.de/getmatchdata/{league_shortcut}/{season}"
        print(f"🔍 Lade von OpenLigaDB API: {api_url}")
        
        response = requests.get(api_url, headers={'User-Agent': 'Anstoss-App/1.0'}, timeout=30)
        
        print(f"   📊 HTTP Status: {response.status_code}")
        print(f"   📏 Response-Länge: {len(response.text)} Zeichen")
        
        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code} für {api_url}")
            print(f"   Response: {response.text[:200]}")
            return all_matches
        
        data = response.json()
        
        print(f"   📦 JSON-Typ: {type(data)}")
        if isinstance(data, list):
            print(f"   📋 Array-Länge: {len(data)}")
        elif isinstance(data, dict):
            print(f"   📋 Dict-Keys: {list(data.keys())[:10]}")
        
        if not isinstance(data, list):
            print(f"⚠️ Unerwartetes Datenformat von API (erwartet: list, erhalten: {type(data)})")
            # Versuche trotzdem zu parsen, falls es ein Dict mit 'matches' Key ist
            if isinstance(data, dict) and 'matches' in data:
                print(f"   🔄 Versuche 'matches' Key aus Dict zu extrahieren...")
                data = data.get('matches', [])
            else:
                return all_matches
        
        # Speichere die Original-API-Daten direkt
        for i, match_data in enumerate(data):
            if not isinstance(match_data, dict):
                print(f"   ⚠️ Match {i} ist kein Dict: {type(match_data)}")
                continue
                
            # WICHTIG: OpenLigaDB API verwendet 'team1' und 'team2' (kleingeschrieben), nicht 'Team1'/'Team2'
            # Versuche verschiedene mögliche Feldnamen
            team1 = (match_data.get('team1') or match_data.get('Team1') or 
                    match_data.get('homeTeam') or match_data.get('HomeTeam') or {})
            team2 = (match_data.get('team2') or match_data.get('Team2') or 
                    match_data.get('awayTeam') or match_data.get('AwayTeam') or {})
            
            # Debug: Zeige ersten Match
            if i == 0:
                print(f"   🔍 Erster Match-Struktur:")
                print(f"      Match Keys: {list(match_data.keys())[:20]}")
                # Prüfe alle möglichen Team-Feldnamen
                for key in match_data.keys():
                    if 'team' in key.lower() or 'Team' in key:
                        print(f"      Gefunden Team-Key: '{key}' = {match_data[key]}")
                print(f"      Team1 (Team1): {match_data.get('Team1')}")
                print(f"      Team1 (team1): {match_data.get('team1')}")
                print(f"      Team2 (Team2): {match_data.get('Team2')}")
                print(f"      Team2 (team2): {match_data.get('team2')}")
                print(f"      Team1-Typ: {type(team1)}")
                print(f"      Team2-Typ: {type(team2)}")
                if isinstance(team1, dict):
                    print(f"      Team1 Keys: {list(team1.keys())}")
                if isinstance(team2, dict):
                    print(f"      Team2 Keys: {list(team2.keys())}")
            
            if not isinstance(team1, dict) or not isinstance(team2, dict):
                print(f"   ⚠️ Match {i}: Team1 oder Team2 ist kein Dict (Team1: {type(team1)}, Team2: {type(team2)})")
                # Versuche alternative Feldnamen
                if isinstance(team1, str) or isinstance(team2, str):
                    print(f"   🔄 Team1/Team2 sind Strings, versuche direkten Zugriff...")
                    # Wenn Team1/Team2 direkt Strings sind, überspringe diesen Match
                    continue
                continue
            
            # WICHTIG: OpenLigaDB API verwendet 'teamName' (kleingeschrieben), nicht 'TeamName'
            # Prüfe verschiedene mögliche Feldnamen für TeamName
            team1_name = (team1.get('teamName') or team1.get('TeamName') or team1.get('name') or 
                         team1.get('Name') or team1.get('shortName') or team1.get('ShortName'))
            team2_name = (team2.get('teamName') or team2.get('TeamName') or team2.get('name') or 
                         team2.get('Name') or team2.get('shortName') or team2.get('ShortName'))
            
            if not team1_name or not team2_name:
                print(f"   ⚠️ Match {i}: Fehlende TeamName")
                print(f"      Team1 Keys: {list(team1.keys()) if isinstance(team1, dict) else 'N/A'}")
                print(f"      Team2 Keys: {list(team2.keys()) if isinstance(team2, dict) else 'N/A'}")
                print(f"      Team1: {team1}")
                print(f"      Team2: {team2}")
                continue
            
            # Für DFB-Pokal: Prüfe ob Match wirklich DFB-Pokal ist (filtere Bundesliga-Spiele raus)
            if league_shortcut == 'dfb':
                league_shortcut_in_match = None
                if 'LeagueShortcut' in match_data:
                    league_shortcut_in_match = match_data.get('LeagueShortcut')
                elif 'leagueShortcut' in match_data:
                    league_shortcut_in_match = match_data.get('leagueShortcut')
                elif 'League' in match_data and isinstance(match_data.get('League'), dict):
                    league_obj = match_data.get('League')
                    if 'LeagueShortcut' in league_obj:
                        league_shortcut_in_match = league_obj.get('LeagueShortcut')
                
                # Nur DFB-Pokal Matches akzeptieren
                if league_shortcut_in_match and league_shortcut_in_match.lower() != 'dfb':
                    print(f"   ⏭️ Gefiltert (falsche Liga): {team1.get('TeamName')} vs {team2.get('TeamName')} - LeagueShortcut={league_shortcut_in_match}")
                    continue
            
            all_matches.append(match_data)
        
        print(f"✅ {len(all_matches)} Matches von OpenLigaDB API geladen (von {len(data)} total)")
        
    except Exception as e:
        print(f"❌ Fehler beim Laden von OpenLigaDB API: {e}")
        import traceback
        traceback.print_exc()
    
    return all_matches

def check_repo_exists(repo: str, token: str) -> bool:
    """Prüft ob das Repository existiert und zugänglich ist"""
    url = f"{GITHUB_API_BASE}/{repo}"
    try:
        response = requests.get(url, headers=get_headers(token), timeout=10)
        if response.status_code == 200:
            return True
        elif response.status_code == 404:
            print(f"❌ Repository {repo} wurde nicht gefunden (404)")
            return False
        elif response.status_code == 403:
            print(f"❌ Keine Berechtigung für Repository {repo} (403)")
            print(f"   WICHTIG: Der GITHUB_TOKEN hat keine Berechtigung für dieses externe Repository.")
            print(f"   Lösung: Erstelle einen Personal Access Token (PAT) mit 'repo' Berechtigung")
            print(f"   und speichere ihn als Secret 'ANSTOSS_SCRAPER_TOKEN' im Repository.")
            return False
        elif response.status_code == 500:
            print(f"❌ GitHub Server-Fehler (500) beim Zugriff auf {repo}")
            print(f"   Dies kann ein temporäres Problem sein. Versuche es später erneut.")
            return False
        elif response.status_code == 503:
            print(f"❌ GitHub Service nicht verfügbar (503) beim Zugriff auf {repo}")
            print(f"   Dies kann ein temporäres Problem sein. Versuche es später erneut.")
            return False
        else:
            print(f"❌ Unerwarteter Fehler beim Zugriff auf {repo}: HTTP {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print(f"❌ Timeout beim Zugriff auf Repository {repo}")
        return False
    except Exception as e:
        print(f"❌ Fehler beim Prüfen des Repositories {repo}: {e}")
        return False

def get_file_sha(repo: str, path: str, token: str) -> Optional[str]:
    """Holt SHA-Hash einer Datei von GitHub (für Update)"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    
    try:
        response = requests.get(url, headers=get_headers(token), timeout=10)
        if response.status_code == 200:
            return response.json().get('sha')
        elif response.status_code == 404:
            # Datei existiert noch nicht, das ist OK
            return None
    except requests.exceptions.Timeout:
        print(f"⚠️ Timeout beim Abrufen der Datei {path}")
        return None
    except Exception as e:
        print(f"⚠️ Fehler beim Abrufen der Datei {path}: {e}")
        return None
    return None

def upload_file_to_github(repo: str, path: str, content: str, token: str, message: str = "Update match data", max_retries: int = 3):
    """Lädt eine Datei in GitHub Repository hoch mit Retry-Logik für temporäre Fehler"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    
    # Prüfe ob Datei bereits existiert
    existing_sha = get_file_sha(repo, path, token)
    
    # Encode content als base64
    import base64
    content_bytes = content.encode('utf-8')
    content_b64 = base64.b64encode(content_bytes).decode('utf-8')
    
    data = {
        'message': message,
        'content': content_b64,
        'branch': 'main'
    }
    
    if existing_sha:
        data['sha'] = existing_sha
        print(f"📝 Aktualisiere vorhandene Datei: {path}")
    else:
        print(f"➕ Erstelle neue Datei: {path}")
    
    # Retry-Logik für temporäre Fehler
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.put(url, headers=get_headers(token), json=data, timeout=30)
            if response.status_code in [200, 201]:
                print(f"✅ Erfolgreich hochgeladen: {path}")
                return True
            elif response.status_code == 404:
                print(f"❌ Repository oder Branch nicht gefunden (404) für {path}")
                print(f"   Stelle sicher, dass das Repository existiert und der Branch 'main' vorhanden ist")
                return False
            elif response.status_code == 403:
                print(f"❌ Keine Berechtigung zum Hochladen (403) für {path}")
                print(f"   WICHTIG: Der GITHUB_TOKEN hat keine Berechtigung für dieses externe Repository.")
                print(f"   Lösung: Erstelle einen Personal Access Token (PAT) mit 'repo' Berechtigung")
                print(f"   und speichere ihn als Secret 'ANSTOSS_SCRAPER_TOKEN' im Repository.")
                return False
            elif response.status_code == 500:
                if attempt < max_retries:
                    wait_time = attempt * 5  # Exponentielles Backoff: 5s, 10s, 15s
                    print(f"⚠️ GitHub Server-Fehler (500) beim Hochladen von {path} (Versuch {attempt}/{max_retries})")
                    print(f"   Warte {wait_time} Sekunden vor erneutem Versuch...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ GitHub Server-Fehler (500) beim Hochladen von {path} nach {max_retries} Versuchen")
                    print(f"   Dies kann ein temporäres Problem sein. Der nächste Workflow-Lauf wird es erneut versuchen.")
                    return False
            elif response.status_code == 502 or response.status_code == 503:
                # Bad Gateway / Service Unavailable - auch retry-würdig
                if attempt < max_retries:
                    wait_time = attempt * 5
                    print(f"⚠️ GitHub Service-Fehler ({response.status_code}) beim Hochladen von {path} (Versuch {attempt}/{max_retries})")
                    print(f"   Warte {wait_time} Sekunden vor erneutem Versuch...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ GitHub Service-Fehler ({response.status_code}) beim Hochladen von {path} nach {max_retries} Versuchen")
                    return False
            else:
                print(f"❌ Fehler beim Hochladen von {path}: HTTP {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                wait_time = attempt * 5
                print(f"⚠️ Timeout beim Hochladen von {path} (Versuch {attempt}/{max_retries})")
                print(f"   Warte {wait_time} Sekunden vor erneutem Versuch...")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Timeout beim Hochladen von {path} nach {max_retries} Versuchen")
                return False
        except Exception as e:
            if attempt < max_retries:
                wait_time = attempt * 5
                print(f"⚠️ Fehler beim Hochladen von {path} (Versuch {attempt}/{max_retries}): {e}")
                print(f"   Warte {wait_time} Sekunden vor erneutem Versuch...")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Fehler beim Hochladen von {path}: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    return False

def main():
    """Hauptfunktion"""
    print("🚀 Starte Upload von Match-Daten nach GitHub...")
    print(f"📦 Repository: {GITHUB_REPO}")
    
    # Prüfe zuerst ob Repository existiert und zugänglich ist
    print("\n🔍 Prüfe Repository-Zugriff...")
    if not check_repo_exists(GITHUB_REPO, GITHUB_TOKEN):
        print("\n❌ Repository-Zugriff fehlgeschlagen. Upload wird abgebrochen.")
        return
    
    print("✅ Repository ist zugänglich\n")
    
    # WICHTIG: OpenLigaDB verwendet Saison -1 (z.B. 2025 statt 2026)
    # fussballdaten.de verwendet Saison +1 (z.B. 2026 statt 2025)
    # ABER: 1. Bundesliga verwendet normale Saison (nicht -1), da sie nicht von OpenLigaDB kommt
    from datetime import datetime
    now = datetime.now()
    if now.month >= 7:  # Ab Juli
        current_season = str(now.year + 1)
    else:
        current_season = str(now.year)
    
    season = get_openligadb_season()  # Für OpenLigaDB: aktuell -1
    season_int = int(season) if season.isdigit() else 2025
    
    # 1. Bundesliga (verwendet normale Saison, nicht OpenLigaDB)
    print("\n📊 Lade 1. Bundesliga von OpenLigaDB API...")
    print(f"   ℹ️ Verwende Saison: {current_season} (normale Saison für 1. Bundesliga)")
    bl1_matches = fetch_openligadb_matches('bl1', current_season)
    
    # Fallback auf vorherige Saison wenn leer
    if len(bl1_matches) == 0:
        current_season_int = int(current_season) if current_season.isdigit() else 2026
        if current_season_int > 2020:
            previous_season = str(current_season_int - 1)
            print(f"⚠️ Keine Matches für Saison {current_season}, versuche {previous_season}...")
            bl1_matches = fetch_openligadb_matches('bl1', previous_season)
            if len(bl1_matches) > 0:
                current_season = previous_season
    
    if len(bl1_matches) > 0:
        # Speichere als JSON-Array (Original-API-Format)
        json_content = json.dumps(bl1_matches, indent=2, ensure_ascii=False)
        file_path = f"data/matches/matches_bundesliga_{current_season}.json"
        message = f"Update 1. Bundesliga matches for season {current_season}"
        upload_file_to_github(GITHUB_REPO, file_path, json_content, GITHUB_TOKEN, message)
    else:
        print("⚠️ Keine 1. Bundesliga Matches gefunden")
    
    # 2. Bundesliga
    print("\n📊 Lade 2. Bundesliga von OpenLigaDB API...")
    print(f"   ℹ️ Verwende OpenLigaDB Saison: {season} (fussballdaten.de würde {int(season) + 1} verwenden)")
    bl2_matches = fetch_openligadb_matches('bl2', season)
    
    # Fallback auf vorherige Saison wenn leer
    if len(bl2_matches) == 0 and season_int > 2020:
        previous_season = str(season_int - 1)
        print(f"⚠️ Keine Matches für Saison {season}, versuche {previous_season}...")
        bl2_matches = fetch_openligadb_matches('bl2', previous_season)
        if len(bl2_matches) > 0:
            season = previous_season
    
    if len(bl2_matches) > 0:
        # Speichere als JSON-Array (Original-API-Format)
        json_content = json.dumps(bl2_matches, indent=2, ensure_ascii=False)
        file_path = f"data/matches/matches_2bundesliga_{season}.json"
        message = f"Update 2. Bundesliga matches for season {season}"
        upload_file_to_github(GITHUB_REPO, file_path, json_content, GITHUB_TOKEN, message)
    else:
        print("⚠️ Keine 2. Bundesliga Matches gefunden")
    
    # DFB-Pokal (verwendet auch OpenLigaDB, daher gleiche Saison)
    print("\n📊 Lade DFB-Pokal von OpenLigaDB API...")
    print(f"   ℹ️ Verwende OpenLigaDB Saison: {season} (fussballdaten.de würde {int(season) + 1} verwenden)")
    dfb_matches = fetch_openligadb_matches('dfb', season)
    
    # Fallback auf vorherige Saison wenn leer
    if len(dfb_matches) == 0 and season_int > 2020:
        previous_season = str(season_int - 1)
        print(f"⚠️ Keine Matches für Saison {season}, versuche {previous_season}...")
        dfb_matches = fetch_openligadb_matches('dfb', previous_season)
        if len(dfb_matches) > 0:
            season = previous_season
    
    if len(dfb_matches) > 0:
        # Speichere als JSON-Array (Original-API-Format)
        json_content = json.dumps(dfb_matches, indent=2, ensure_ascii=False)
        file_path = f"data/matches/matches_dfbpokal_{season}.json"
        message = f"Update DFB-Pokal matches for season {season}"
        upload_file_to_github(GITHUB_REPO, file_path, json_content, GITHUB_TOKEN, message)
    else:
        print("⚠️ Keine DFB-Pokal Matches gefunden")
    
    print("\n✅ Upload abgeschlossen!")

if __name__ == '__main__':
    main()

