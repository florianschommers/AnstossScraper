#!/usr/bin/env python3
"""
Script zum Hochladen von Lineup-Daten nach GitHub Repository
"""

import requests
import json
import os
import base64
from datetime import datetime
from typing import Optional

# GitHub Repository Konfiguration
GITHUB_REPO = "florianschommers/AnstossScraper"
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN Umgebungsvariable muss gesetzt sein!")
GITHUB_API_BASE = "https://api.github.com/repos"

HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def get_current_season() -> str:
    """Ermittelt die aktuelle Saison (Juli - Juni)"""
    now = datetime.now()
    if now.month >= 7:
        return str(now.year + 1)
    else:
        return str(now.year)

def get_file_sha(repo: str, path: str) -> Optional[str]:
    """Holt SHA-Hash einer Datei von GitHub"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            return response.json().get('sha')
        return None
    except:
        return None

def upload_file_to_github(repo: str, path: str, content: str, message: str = "Update lineup data"):
    """Lädt eine Datei zu GitHub hoch"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    
    # Prüfe ob Datei existiert
    sha = get_file_sha(repo, path)
    
    # Encode Content als Base64
    content_bytes = content.encode('utf-8')
    content_encoded = base64.b64encode(content_bytes).decode('utf-8')
    
    data = {
        "message": message,
        "content": content_encoded,
        "branch": "main"
    }
    
    if sha:
        data["sha"] = sha
    
    try:
        response = requests.put(url, headers=HEADERS, json=data)
        if response.status_code in [200, 201]:
            print(f"✅ Hochgeladen: {path}")
            return True
        else:
            print(f"❌ Fehler beim Hochladen von {path}: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Fehler beim Hochladen von {path}: {e}")
        return False

def main():
    """Hauptfunktion"""
    print("🚀 Starte Upload von Lineup-Daten nach GitHub...")
    print(f"📦 Repository: {GITHUB_REPO}")
    
    season = get_current_season()
    int_season = get_current_season()  # Internationale Saison ist gleich
    
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
    
    lineups_dir = "data/lineups"
    if not os.path.exists(lineups_dir):
        print(f"⚠️ Verzeichnis {lineups_dir} existiert nicht")
        return
    
    uploaded = 0
    failed = 0
    
    for league_name, league_season in leagues:
        filename = f"lineups_{league_name}_{league_season}.json"
        filepath = os.path.join(lineups_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"⚠️ Datei nicht gefunden: {filepath}")
            continue
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            github_path = f"data/lineups/{filename}"
            message = f"Update lineups for {league_name} season {league_season}"
            
            if upload_file_to_github(GITHUB_REPO, github_path, content, message):
                uploaded += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Fehler bei {filename}: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"✅ Erfolgreich hochgeladen: {uploaded}")
    print(f"❌ Fehlgeschlagen: {failed}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()

