import re
import sys
import csv
import time
import json
import unicodedata
from typing import Set, Dict, List

try:
    import requests
    from bs4 import BeautifulSoup
except Exception as e:
    print("FEHLER: Bitte installiere die Abhängigkeiten: pip install requests beautifulsoup4")
    sys.exit(2)


TRANSFERMARKT_URLS = {
    "1-bundesliga-verletzte": "https://www.transfermarkt.de/bundesliga/verletztespieler/wettbewerb/L1",
    "2-bundesliga-verletzte": "https://www.transfermarkt.de/2-bundesliga/verletztespieler/wettbewerb/L2",
    "1-bundesliga-sperren":   "https://www.transfermarkt.de/bundesliga/sperrenausfaelle/wettbewerb/L1",
    "2-bundesliga-sperren":   "https://www.transfermarkt.de/bundesliga/sperrenausfaelle/wettbewerb/L2",
}


def http_get(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def fetch_players(url: str) -> Set[str]:
    """Scrape Transfermarkt tables for injured/suspended players."""
    html = http_get(url)
    soup = BeautifulSoup(html, "html.parser")
    players: Set[str] = set()
    for link in soup.select("table a.spielprofil_tooltip"):
        name = (link.text or "").strip()
        if name:
            players.add(name)
    return players


def build_status_dict() -> Dict[str, str]:
    injured = fetch_players(TRANSFERMARKT_URLS["1-bundesliga-verletzte"]).union(
        fetch_players(TRANSFERMARKT_URLS["2-bundesliga-verletzte"]))
    suspended = fetch_players(TRANSFERMARKT_URLS["1-bundesliga-sperren"]).union(
        fetch_players(TRANSFERMARKT_URLS["2-bundesliga-sperren"]))

    status: Dict[str, str] = {}
    for p in injured:
        status[norm(p)] = "verletzt"
    for p in suspended:
        status[norm(p)] = "gesperrt"
    return status


def norm(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("&amp;", "&").strip().lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    s = s.replace('ß', 'ss')
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def strip_existing_marker(player: str) -> str:
    # Entferne alte Marker wie " (false)" oder " (false:verletzt)"
    return re.sub(r"\s*\(false(?::[a-z]+)?\)$", "", player.strip(), flags=re.IGNORECASE)


def mark_players_in_txt(input_txt: str) -> None:
    # Lade Status-Lexikon
    status_dict = build_status_dict()

    with open(input_txt, "r", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()

    out_lines: List[str] = []
    for line in lines:
        raw = line.rstrip("\n")
        if not raw or raw.startswith("#"):
            out_lines.append(raw)
            continue

        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 7:
            out_lines.append(raw)
            continue

        # Erwartetes Format: Team | TW | ABW | MF1 | MF2 | ANG1 | ANG2
        team = parts[0].strip()
        players = [strip_existing_marker(p.strip()) for p in parts[1:7]]

        updated: List[str] = []
        for p in players:
            if not p:
                updated.append(p)
                continue
            status = status_dict.get(norm(p), "fit")
            if status == "fit":
                updated.append(p)
            else:
                # Markiere maschinenlesbar
                updated.append(f"{p} (false:{status})")

        new_line = " | ".join([team] + updated)
        out_lines.append(new_line)

    with open(input_txt, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\n".join(out_lines) + "\n")

    print(f"✓ Fitness-Status aktualisiert in: {input_txt}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fitness_check_tm.py empfohlene_spieler_pro_team.txt")
        sys.exit(1)
    mark_players_in_txt(sys.argv[1])


