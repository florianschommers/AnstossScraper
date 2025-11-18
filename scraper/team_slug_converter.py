#!/usr/bin/env python3
"""
Team-Name-zu-Slug-Konverter - Portierung der App-Logik
Konvertiert Team-Namen zu fussballdaten.de URL-Slugs
"""

import re
import unicodedata
from typing import Optional, Dict

# Rate Limiting: Reduziert von 1.0 auf 0.5 Sekunden für schnellere Scraping (25min → ~12min)
REQUEST_DELAY = 0.5

def get_liga_specific_team_slug(team_name: str, liga_id: int) -> Optional[str]:
    """Gibt ligen-spezifische Team-Slugs zurück (für direkte Mappings)"""
    if liga_id == 99:  # Konferenz - verwendet Bundesliga-Mappings
        # Versuche zuerst 1. Bundesliga, dann 2. Bundesliga
        mapping = {
            # 1. Bundesliga Teams
            "FC Bayern München": "bayern",
            "Bayern München": "bayern",
            "Bayern": "bayern",
            "FC Bayern": "bayern",
            "Borussia Dortmund": "dortmund",
            "BVB": "dortmund",
            "RB Leipzig": "rbleipzig",
            "Leipzig": "rbleipzig",
            "RasenBallsport Leipzig": "rbleipzig",
            "Bayer 04 Leverkusen": "leverkusen",
            "Leverkusen": "leverkusen",
            "Bayer Leverkusen": "leverkusen",
            "VfB Stuttgart": "stuttgart",
            "Stuttgart": "stuttgart",
            "Eintracht Frankfurt": "frankfurt",
            "Frankfurt": "frankfurt",
            "Eintracht": "frankfurt",
            "SC Freiburg": "freiburg",
            "Freiburg": "freiburg",
            "TSG 1899 Hoffenheim": "hoffenheim",
            "Hoffenheim": "hoffenheim",
            "TSG Hoffenheim": "hoffenheim",
            "1899 Hoffenheim": "hoffenheim",
            "VfL Wolfsburg": "wolfsburg",
            "Wolfsburg": "wolfsburg",
            "Borussia Mönchengladbach": "mgladbach",
            "Mönchengladbach": "mgladbach",
            "Borussia M'gladbach": "mgladbach",
            "1. FSV Mainz 05": "mainz",
            "Mainz 05": "mainz",
            "Mainz": "mainz",
            "FSV Mainz": "mainz",
            "1. FC Union Berlin": "unionberlin",
            "Union Berlin": "unionberlin",
            "Union": "unionberlin",
            "FC Union Berlin": "unionberlin",
            "FC Augsburg": "augsburg",
            "Augsburg": "augsburg",
            "1. FC Heidenheim": "heidenheim",
            "Heidenheim": "heidenheim",
            "FC Heidenheim": "heidenheim",
            "1. FC Heidenheim 1846": "heidenheim",
            "1. FC Köln": "koeln",
            "FC Köln": "koeln",
            "Köln": "koeln",
            "Werder Bremen": "bremen",
            "SV Werder Bremen": "bremen",
            "Bremen": "bremen",
            "Werder": "bremen",
            "Hamburger SV": "hamburg",
            "HSV": "hamburg",
            "Hamburg": "hamburg",
            "Hamburger": "hamburg",
            "FC St. Pauli": "stpauli",
            "St. Pauli": "stpauli",
            "St Pauli": "stpauli",
            # 2. Bundesliga Teams
            "Holstein Kiel": "kiel",
            "Kiel": "kiel",
            "Holstein": "kiel",
            "VfL Bochum": "vflbochum",
            "Bochum": "vflbochum",
            "SV Elversberg": "elversberg",
            "Elversberg": "elversberg",
            "SV 07 Elversberg": "elversberg",
            "SC Paderborn 07": "paderborn",
            "Paderborn 07": "paderborn",
            "Paderborn": "paderborn",
            "SC Paderborn": "paderborn",
            "1. FC Magdeburg": "magdeburg",
            "Magdeburg": "magdeburg",
            "FC Magdeburg": "magdeburg",
            "Fortuna Düsseldorf": "dusseldorf",
            "Düsseldorf": "dusseldorf",
            "Fortuna": "dusseldorf",
            "1. FC Kaiserslautern": "klautern",
            "Kaiserslautern": "klautern",
            "FC Kaiserslautern": "klautern",
            "Karlsruher SC": "karlsruhe",
            "Karlsruhe": "karlsruhe",
            "Karlsruher": "karlsruhe",
            "KSC": "karlsruhe",
            "Hannover 96": "hannover",
            "Hannover": "hannover",
            "1. FC Nürnberg": "nuernberg",
            "Nürnberg": "nuernberg",
            "FC Nürnberg": "nuernberg",
            "Hertha BSC": "herthabsc",
            "Hertha BSC Berlin": "herthabsc",
            "Hertha": "herthabsc",
            "Hertha Berlin": "herthabsc",
            "SV Darmstadt 98": "darmstadt",
            "Darmstadt 98": "darmstadt",
            "Darmstadt": "darmstadt",
            "SV Darmstadt": "darmstadt",
            "SpVgg Greuther Fürth": "fuerth",
            "Greuther Fürth": "fuerth",
            "Fürth": "fuerth",
            "Greuther": "fuerth",
            "FC Schalke 04": "schalke",
            "Schalke 04": "schalke",
            "Schalke": "schalke",
            "FC Schalke": "schalke",
            "SC Preußen Münster": "muenster",
            "Preußen Münster": "muenster",
            "Münster": "muenster",
            "Preussen Muenser": "muenster",
            "Eintracht Braunschweig": "braunschweig",
            "Braunschweig": "braunschweig",
            "Eintracht BS": "braunschweig",
            "DSC Arminia Bielefeld": "arminiabielefeld",
            "Arminia Bielefeld": "arminiabielefeld",
            "Bielefeld": "arminiabielefeld",
            "Arminia": "arminiabielefeld",
            "Dynamo Dresden": "dresden",
            "SG Dynamo Dresden": "dresden",
        }
        return mapping.get(team_name)
    
    # Weitere Liga-Mappings können hier hinzugefügt werden
    return None

def vereinfache_team_name_fuer_vergleich(team_name: str, liga_id: int = 1) -> str:
    """Vereinfacht Team-Namen für fussballdaten.de URLs - Portierung der App-Logik"""
    if not team_name:
        return ""
    
    # Spezifische Mappings basierend auf Liga
    liga_specific_slug = get_liga_specific_team_slug(team_name, liga_id)
    if liga_specific_slug:
        return liga_specific_slug
    
    # Unicode-Normalisierung (wie Normalizer.normalize in Kotlin)
    slug = unicodedata.normalize('NFD', team_name)
    # Entferne diakritische Zeichen (wie .replace(Regex("\\p{M}+"), ""))
    slug = ''.join(c for c in slug if unicodedata.category(c) != 'Mn')
    slug = slug.lower()
    slug = slug.replace("ß", "ss")
    
    # Entferne Präfixe und Vereinsbegriffe (für deutsche Ligen + Konferenz)
    if liga_id in [1, 2, 3, 99]:
        # Entferne "1.", "2.", "3."
        slug = re.sub(r'\b(1\.|2\.|3\.)\s*', '', slug)
        # Entferne Vereinsbegriffe am Anfang
        slug = re.sub(r'\b(fc|sv|fsv|vfl|vfb|tsg|sc|spvgg|eintracht|fortuna|arminia|preußen|preussen)\s+', '', slug)
        # Entferne Vereinsbegriffe am Ende
        slug = re.sub(r'\s+(fc|sv|fsv|vfl|vfb|tsg|sc|spvgg|eintracht|fortuna|arminia|preußen|preussen)\b', '', slug)
    
    # Für andere Ligen: Entferne Standard-Präfixe
    if liga_id not in [1, 2, 3, 99]:
        slug = re.sub(r'\b(fc|as|rc|osc|ogc|stade|olympique|le)\s+', '', slug)
        slug = re.sub(r'\s+(fc|ac|hsc|cv)\b', '', slug)
    
    # Leerzeichen und Sonderzeichen entfernen
    slug = re.sub(r'[^a-z0-9]', '', slug)
    
    # Spezielle Mappings für bekannte Unterschiede (deutsche Ligen + Konferenz)
    if liga_id in [1, 2, 3, 99]:
        slug_mappings = {
            "bayernmunchen": "bayern",
            "fcbayernmunchen": "bayern",
            "fcbayern": "bayern",
            "borussiadortmund": "dortmund",
            "bvb": "dortmund",
            "borussiamonchengladbach": "mgladbach",
            "monchengladbach": "mgladbach",
            "werderbremen": "bremen",
            "svwerderbremen": "bremen",
            "svwerder": "bremen",
            "heidenheim1846": "heidenheim",
            "fcheidenheim1846": "heidenheim",
            "fcheidenheim": "heidenheim",
            "1heidenheim1846": "heidenheim",
            "1fcheidenheim1846": "heidenheim",
            "koln": "koeln",
            "fckoln": "koeln",
            "fckoeln": "koeln",
            "1fckoln": "koeln",
            "1fckoeln": "koeln",
            "koeln": "koeln",
            "dusseldorf": "duesseldorf",
            "fortunadusseldorf": "duesseldorf",
            "fortunaduesseldorf": "duesseldorf",
            "herthabsc": "herthabsc",
            "herthabscc": "herthabsc",
            "hoffenheim": "hoffenheim",
            "1899hoffenheim": "hoffenheim",
            "tsghoffenheim": "hoffenheim",
            "rbleipzig": "rbleipzig",
            "leipzigrb": "rbleipzig",
            "unionberlin": "unionberlin",
            "fcunionberlin": "unionberlin",
            "1unionberlin": "unionberlin",
            "1fcunionberlin": "unionberlin",
            "stpauli": "stpauli",
            "fcstpauli": "stpauli",
            "mainz05": "mainz",
            "fsvmainz05": "mainz",
            "mainz": "mainz",
            "1fsvmainz05": "mainz",
            "hamburger": "hamburg",
            "hamburgersv": "hamburg",
            "hsv": "hamburg",
            "stuttgart": "stuttgart",
            "vfbstuttgart": "stuttgart",
            "freiburg": "freiburg",
            "scfreiburg": "freiburg",
            "frankfurt": "frankfurt",
            "eintrachtfrankfurt": "frankfurt",
            "eintracht": "frankfurt",
            "bayer04leverkusen": "leverkusen",
            "bayerleverkusen": "leverkusen",
            "bayer04": "leverkusen",
            "leverkusen04": "leverkusen",
            "hannover96": "hannover",
            "schalke04": "schalke",
            "paderborn07": "paderborn",
            "kaiserslautern": "klautern",
            "1fckaiserslautern": "klautern",
            "karlsruher": "karlsruhe",
            "darmstadt98": "darmstadt",
            "07elversberg": "elversberg",
            "elversberg07": "elversberg",
            "greutherfurth": "fuerth",
            "greuterfurth": "fuerth",
            "bochum": "vflbochum",
            "dynamodresden": "dresden",
            "preussenmuenster": "muenster",
        }
        slug = slug_mappings.get(slug, slug)
    
    return slug

def convert_international_team_to_slug(team_name: str) -> str:
    """Konvertiert internationale Team-Namen zu Slugs - Portierung der App-Logik"""
    # Spezial-Mapping für Aufstellungs-URLs - EXAKTE Schreibweise von fussballdaten.de!
    aufstellung_mapping = {
        # Champions League
        "Slavia Prag": "slaviaprag",
        "Arsenal FC": "arsenal",
        "SSC Napoli": "sscneapel",
        "Eintracht Frankfurt": "frankfurt",
        "Olympiakos Piräus": "olympiakos",
        "PSV Eindhoven": "eindhoven",
        "Atlético Madrid": "atlmadrid",
        "Royale Union Saint-Gilloise": "stgilloise",
        "FK Bodø/Glimt": "bodo/glimt",
        "AS Monaco": "monaco",
        "Juventus Turin": "juventusturin",
        "Sporting Lissabon": "sporting",
        "Liverpool FC": "liverpool",
        "Real Madrid CF": "realmadrid",
        "Tottenham Hotspur FC": "tottenham",
        "FC Kopenhagen": "kopenhagen",
        "Paris Saint-Germain": "psg",
        "FC Bayern München": "bayern",
        "AEP Paphos FC": "aeppaphosfc",
        "Villarreal CF": "villarreal",
        "FK Qarabağ Ağdam": "karabakh",
        "Chelsea FC": "chelsea",
        "Olympique de Marseille": "olmarseille",
        "Atalanta Bergamo": "bergamo",
        "Newcastle United FC": "newcastle",
        "Athletic Club Bilbao": "athbilbao",
        "Manchester City FC": "mancity",
        "Borussia Dortmund": "dortmund",
        "Club Brugge KV": "clubbrugge",
        "FC Barcelona": "fcbarcelona",
        "Inter Mailand": "intermailand",
        "FC Kairat Almaty": "kairat",
        "Ajax Amsterdam": "ajaxamsterdam",
        "Galatasaray Istanbul": "galatasaray",
        "Benfica Lissabon": "benfica",
        "Bayer 04 Leverkusen": "leverkusen",
        # Europa League - weitere Mappings hier...
        # Conference League - weitere Mappings hier...
    }
    
    if team_name in aufstellung_mapping:
        return aufstellung_mapping[team_name]
    
    # Fallback: Vereinfachte Konvertierung
    slug = team_name.lower().replace(" ", "").replace("-", "")
    return slug

def convert_team_to_slug(team_name: str, liga_id: int = 1, is_international: bool = False) -> str:
    """Hauptfunktion: Konvertiert Team-Namen zu URL-Slugs"""
    if is_international:
        return convert_international_team_to_slug(team_name)
    else:
        return vereinfache_team_name_fuer_vergleich(team_name, liga_id)

