#!/usr/bin/env python3
"""
Script zum Hochladen von Match-Daten (2. Bundesliga und DFB-Pokal) in GitHub Repository
"""

import requests
import json
import os
from datetime import datetime
from typing import List, Dict

# GitHub Repository Konfiguration
GITHUB_REPO = "florianschommers/AnstossScraper"
# Token aus Umgebungsvariable (für GitHub Actions) - KEIN Fallback, muss gesetzt sein
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN Umgebungsvariable muss gesetzt sein!")
GITHUB_API_BASE = "https://api.github.com/repos"

# User-Agent für Requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def get_current_season() -> str:
    """Ermittelt die aktuelle Saison (August - Juli)"""
    now = datetime.now()
    if now.month >= 7:  # Ab Juli
        return str(now.year + 1)
    else:
        return str(now.year)

def fetch_openligadb_matches(league_shortcut: str, season: str) -> List[Dict]:
    """Holt Match-Daten von der OpenLigaDB API"""
    all_matches = []
    
    try:
        api_url = f"https://www.openligadb.de/api/getmatchdata/{league_shortcut}/{season}"
        print(f"🔍 Lade von OpenLigaDB API: {api_url}")
        
        response = requests.get(api_url, headers={'User-Agent': 'Anstoss-App/1.0'}, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code} für {api_url}")
            return all_matches
        
        data = response.json()
        
        if not isinstance(data, list):
            print(f"⚠️ Unerwartetes Datenformat von API")
            return all_matches
        
        # Speichere die Original-API-Daten direkt
        for match_data in data:
            team1 = match_data.get('Team1', {})
            team2 = match_data.get('Team2', {})
            if not isinstance(team1, dict) or not isinstance(team2, dict):
                continue
            if not team1.get('TeamName') or not team2.get('TeamName'):
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
        
        print(f"✅ {len(all_matches)} Matches von OpenLigaDB API geladen")
        
    except Exception as e:
        print(f"❌ Fehler beim Laden von OpenLigaDB API: {e}")
        import traceback
        traceback.print_exc()
    
    return all_matches

def get_file_sha(repo: str, path: str, token: str) -> str:
    """Holt SHA-Hash einer Datei von GitHub (für Update)"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()['sha']
    except:
        pass
    return None

def upload_file_to_github(repo: str, path: str, content: str, token: str, message: str = "Update match data"):
    """Lädt eine Datei in GitHub Repository hoch"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
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
    
    try:
        response = requests.put(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            print(f"✅ Erfolgreich hochgeladen: {path}")
            return True
        else:
            print(f"❌ Fehler beim Hochladen: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Fehler beim Hochladen: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Hauptfunktion"""
    print("🚀 Starte Upload von Match-Daten nach GitHub...")
    print(f"📦 Repository: {GITHUB_REPO}")
    
    season = get_current_season()
    season_int = int(season) if season.isdigit() else 2025
    
    # 2. Bundesliga
    print("\n📊 Lade 2. Bundesliga von OpenLigaDB API...")
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
    
    # DFB-Pokal
    print("\n📊 Lade DFB-Pokal von OpenLigaDB API...")
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

