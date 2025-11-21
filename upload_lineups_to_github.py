#!/usr/bin/env python3
"""
Script zum Hochladen von Lineup-Daten nach GitHub Repository
"""

import requests
import json
import os
import base64
import time
from datetime import datetime
from typing import Optional

# GitHub Repository Konfiguration
GITHUB_REPO = "florianschommers/AnstossScraper"
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN Umgebungsvariable muss gesetzt sein!")
GITHUB_API_BASE = "https://api.github.com/repos"

# Authorization Header - unterstützt sowohl 'token' als auch 'Bearer' Format
def get_headers():
    """Erstellt Header mit korrektem Authorization-Format"""
    # Prüfe ob Token bereits 'Bearer' oder 'token' Präfix hat
    if GITHUB_TOKEN.startswith('Bearer ') or GITHUB_TOKEN.startswith('token '):
        auth_header = GITHUB_TOKEN
    else:
        # Standard: verwende 'Bearer' für GitHub Actions, 'token' als Fallback
        auth_header = f'Bearer {GITHUB_TOKEN}'
    
    return {
        'Authorization': auth_header,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Anstoss-Lineup-Uploader'
    }

def get_current_season() -> str:
    """Ermittelt die aktuelle Saison (Juli - Juni)"""
    now = datetime.now()
    if now.month >= 7:
        return str(now.year + 1)
    else:
        return str(now.year)

def check_repo_exists(repo: str) -> bool:
    """Prüft ob das Repository existiert und zugänglich ist"""
    url = f"{GITHUB_API_BASE}/{repo}"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
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

def get_file_sha(repo: str, path: str) -> Optional[str]:
    """Holt SHA-Hash einer Datei von GitHub"""
    url = f"{GITHUB_API_BASE}/{repo}/contents/{path}"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            return response.json().get('sha')
        elif response.status_code == 404:
            # Datei existiert noch nicht, das ist OK
            return None
        return None
    except requests.exceptions.Timeout:
        print(f"⚠️ Timeout beim Abrufen der Datei {path}")
        return None
    except Exception as e:
        print(f"⚠️ Fehler beim Abrufen der Datei {path}: {e}")
        return None

def upload_file_to_github(repo: str, path: str, content: str, message: str = "Update lineup data", max_retries: int = 3):
    """Lädt eine Datei zu GitHub hoch mit Retry-Logik für temporäre Fehler"""
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
    
    # Retry-Logik für temporäre Fehler
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.put(url, headers=get_headers(), json=data, timeout=30)
            if response.status_code in [200, 201]:
                print(f"✅ Hochgeladen: {path}")
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
    print("🚀 Starte Upload von Lineup-Daten nach GitHub...")
    print(f"📦 Repository: {GITHUB_REPO}")
    
    # Prüfe zuerst ob Repository existiert und zugänglich ist
    print("\n🔍 Prüfe Repository-Zugriff...")
    if not check_repo_exists(GITHUB_REPO):
        print("\n❌ Repository-Zugriff fehlgeschlagen. Upload wird abgebrochen.")
        return
    
    print("✅ Repository ist zugänglich\n")
    
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
        filename = f"lineups_{league_name}.json"
        filepath = os.path.join(lineups_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"⚠️ Datei nicht gefunden: {filepath}")
            continue
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            github_path = f"data/lineups/{filename}"
            message = f"Update lineups for {league_name}"
            
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

