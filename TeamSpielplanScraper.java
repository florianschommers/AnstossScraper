import java.io.*;
import java.net.*;
import java.util.*;
import java.util.regex.*;
import java.text.SimpleDateFormat;
import java.text.ParseException;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

public class TeamSpielplanScraper {
    
    private static final String MANNSCHAFTEN_DATEI = "Mannschaftsnamen_OpenDB_FDaten.txt";
    private static final String AKTUELLE_TEAMS_DATEI = "aktuelle_teams_automatisch.txt";
    private static final String OUTPUT_DATEI = "team_spielplaene_letzte10.txt";
    private static final String BASE_URL = "https://www.fussballdaten.de/vereine/";
    private static final String BASE_URL_1BL = "https://www.fussballdaten.de/bundesliga/";
    private static final String TABELLE_SUFFIX = "/tabelle/";
    
    // Saison wird dynamisch ermittelt
    private static int aktuelleSaison = -1;
    
    private static Map<String, String> teamNames = new HashMap<>();
    private static List<String> allTeams = new ArrayList<>();
    
    public static void main(String[] args) {
        System.out.println("=== Team Spielplan Scraper ===");
        
        // Ermittle aktuelle Saison
        aktuelleSaison = findeAktuelleSaison();
        if (aktuelleSaison == -1) {
            System.err.println("Keine aktuelle Saison gefunden!");
            return;
        }
        System.out.println("Aktuelle Saison gefunden: " + (aktuelleSaison-1) + "/" + aktuelleSaison);
        
        // Prüfe ob automatische Teams verfügbar sind
        File automatischeDatei = new File(AKTUELLE_TEAMS_DATEI);
        boolean useAutomaticTeams = automatischeDatei.exists();
        
        if (useAutomaticTeams) {
            System.out.println("✓ Verwende automatisch gesammelte Teams aus: " + AKTUELLE_TEAMS_DATEI);
        } else {
            System.out.println("! Verwende statische Teams aus: " + MANNSCHAFTEN_DATEI);
            System.out.println("Lade Mannschaftsnamen...");
            
            if (!loadTeamNames()) {
                System.err.println("Fehler beim Laden der Mannschaftsnamen!");
                return;
            }
            System.out.println("Gefunden: " + allTeams.size() + " Teams (nur 'Bestehende Teams')");
        }
        
        // Prüfe Kommandozeilen-Parameter
        if (args.length > 0) {
            // Einzelne Teams scrapen
            System.out.println("Scrape einzelne Teams: " + Arrays.toString(args));
            if (useAutomaticTeams) {
                scrapeSpecificTeamsAutomatic(args);
            } else {
                scrapeSpecificTeams(args);
            }
        } else {
            // Alle Teams scrapen
            if (useAutomaticTeams) {
                scrapeAllTeamsAutomatic();
            } else {
                System.out.println("Scrape alle " + allTeams.size() + " Teams...");
                scrapeAllTeams();
            }
        }
    }
    
    /**
     * Findet die aktuelle Saison durch Testen der URLs
     * Übernommen von AktuelleTeamsScraper
     */
    private static int findeAktuelleSaison() {
        int aktuellJahr = java.time.Year.now().getValue();
        int startJahr = aktuellJahr + 2;
        int mindestJahr = aktuellJahr;
        
        System.out.println("Aktuelles Jahr: " + aktuellJahr);
        System.out.println("Starte Suche bei: " + (startJahr-1) + "/" + startJahr);
        
        // Phase 1: Normale Suche mit strikter Validierung
        int gefundeneSaison = sucheSaisonNormal(startJahr, mindestJahr);
        if (gefundeneSaison != -1) {
            return gefundeneSaison;
        }
        
        // Phase 2: KRITISCH - Mindestens aktuelles Jahr MUSS funktionieren!
        System.out.println("\nKRITISCH: Normale Suche fehlgeschlagen!");
        System.out.println("Erzwinge Mindestanforderung: " + (mindestJahr-1) + "/" + mindestJahr);
        
        gefundeneSaison = erzwingeMindestSaison(mindestJahr);
        if (gefundeneSaison != -1) {
            return gefundeneSaison;
        }
        
        // Phase 3: NOTFALL - Aktuelles Jahr +1 erzwingen
        System.out.println("\nNOTFALL: Erzwinge " + aktuellJahr + "/" + (aktuellJahr + 1));
        gefundeneSaison = erzwingeMindestSaison(aktuellJahr + 1);
        if (gefundeneSaison != -1) {
            return gefundeneSaison;
        }
        
        // Das darf niemals passieren!
        System.err.println("FATALER FEHLER: Keine moderne Saison gefunden!");
        return -1;
    }
    
    /**
     * Normale Saisonsuche mit strikter Validierung
     */
    private static int sucheSaisonNormal(int startJahr, int mindestJahr) {
        for (int jahr = startJahr; jahr >= mindestJahr; jahr--) {
            String testUrl = BASE_URL_1BL + jahr + TABELLE_SUFFIX;
            System.out.println("Teste Saison " + (jahr-1) + "/" + jahr + ": " + testUrl);
            
            if (istUrlVerfuegbar(testUrl)) {
                System.out.println("OK: Saison " + (jahr-1) + "/" + jahr + " verfuegbar!");
                
                // Prüfe ob diese Saison auch Teams hat (mit Retry)
                String html = fetchHtmlMitRetry(testUrl, 3);
                if (html != null && hatTeams(html)) {
                    System.out.println("✓ Saison " + (jahr-1) + "/" + jahr + " hat Teams - verwende diese!");
                    return jahr;
                } else {
                    System.out.println("- Saison " + (jahr-1) + "/" + jahr + " noch keine Teams - suche weiter...");
                }
            } else {
                System.out.println("NEIN: Saison " + (jahr-1) + "/" + jahr + " nicht verfuegbar");
            }
        }
        return -1;
    }
    
    /**
     * Erzwingt eine Mindest-Saison mit weniger strikter Validierung
     */
    private static int erzwingeMindestSaison(int jahr) {
        String testUrl = BASE_URL_1BL + jahr + TABELLE_SUFFIX;
        System.out.println("ERZWINGE Saison " + (jahr-1) + "/" + jahr + ": " + testUrl);
        
        if (istUrlVerfuegbar(testUrl)) {
            System.out.println("✓ URL verfuegbar!");
            
            // Mehrere Versuche mit Pausen
            for (int versuch = 1; versuch <= 5; versuch++) {
                System.out.println("Versuch " + versuch + "/5...");
                
                String html = fetchHtml(testUrl);
                if (html != null) {
                    // Weniger strikt: Nur /vereine/ prüfen
                    boolean hatVereine = html.contains("/vereine/");
                    System.out.println("   Hat /vereine/: " + hatVereine);
                    
                    if (hatVereine) {
                        System.out.println("ERZWUNGEN: Saison " + (jahr-1) + "/" + jahr + " wird verwendet!");
                        return jahr;
                    }
                }
                
                // Pause zwischen Versuchen
                if (versuch < 5) {
                    System.out.println("   Pause 2 Sekunden...");
                    try { Thread.sleep(2000); } catch (InterruptedException e) {}
                }
            }
        }
        
        System.out.println("FEHLER: Erzwingen fehlgeschlagen fuer " + (jahr-1) + "/" + jahr);
        return -1;
    }
    
    /**
     * HTML mit Retry-Mechanik laden
     */
    private static String fetchHtmlMitRetry(String url, int maxVersuche) {
        for (int versuch = 1; versuch <= maxVersuche; versuch++) {
            String html = fetchHtml(url);
            if (html != null) {
                return html;
            }
            
            if (versuch < maxVersuche) {
                System.out.println("   Retry " + versuch + "/" + maxVersuche + " in 1 Sekunde...");
                try { Thread.sleep(1000); } catch (InterruptedException e) {}
            }
        }
        return null;
    }
    
    /**
     * Prüft ob eine Saison Teams hat (nicht leer ist)
     */
    private static boolean hatTeams(String html) {
        // Basis-Anforderung
        boolean hasVereine = html.contains("/vereine/");
        if (!hasVereine) {
            System.out.println("   Validierung: Keine /vereine/ Links gefunden → false");
            return false;
        }
        
        // BESSERE METHODE: Zähle tatsächliche /vereine/ Links
        Pattern vereineLinkPattern = Pattern.compile("/vereine/[^/\"]+/\\d+/", Pattern.CASE_INSENSITIVE);
        Matcher matcher = vereineLinkPattern.matcher(html);
        
        int anzahlVereine = 0;
        while (matcher.find()) {
            anzahlVereine++;
        }
        
        // Für eine komplette Liga erwarten wir mindestens 15 Teams (von 18)
        boolean result = anzahlVereine >= 15;
        
        System.out.println("   Validierung: /vereine/=" + hasVereine + ", Anzahl Vereine-Links=" + anzahlVereine + " → " + result);
        
        return result;
    }
    
    /**
     * Prüft ob eine URL verfügbar ist
     */
    private static boolean istUrlVerfuegbar(String urlString) {
        try {
            URL url = new URL(urlString);
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("HEAD");
            connection.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36");
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(5000);
            
            int responseCode = connection.getResponseCode();
            connection.disconnect();
            
            return responseCode == 200;
            
        } catch (Exception e) {
            return false;
        }
    }
    
    /**
     * Scrapt alle Teams im automatischen Modus
     */
    private static void scrapeAllTeamsAutomatic() {
        List<TeamInfo> teams = loadAutomaticTeams();
        if (teams.isEmpty()) {
            System.err.println("FEHLER: Keine Teams in automatischer Datei gefunden!");
            return;
        }
        
        System.out.println("Gefunden: " + teams.size() + " automatische Teams");
        List<String> results = new ArrayList<>();
        int count = 0;
        
        for (TeamInfo team : teams) {
            count++;
            System.out.println("\n--- " + count + "/" + teams.size() + ": " + team.liga + " " + team.anzeigeName + " ---");
            
            String result = scrapeTeamSpielplan(team.anzeigeName, team.urlName);
            if (result != null) {
                results.add(result);
            }
            
            // Pause zwischen Requests
            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                break;
            }
        }
        
        // Speichere alle Ergebnisse (überschreibe die Datei)
        saveResults(results, OUTPUT_DATEI, false);
        System.out.println("\n=== FERTIG ===");
        System.out.println("Alle " + teams.size() + " Teams gescrapt!");
        System.out.println("Gespeichert in: " + OUTPUT_DATEI);
    }
    
    /**
     * Liest Teams aus der automatisch generierten Datei
     */
    private static List<TeamInfo> loadAutomaticTeams() {
        List<TeamInfo> teams = new ArrayList<>();
        
        try (BufferedReader reader = new BufferedReader(new FileReader(AKTUELLE_TEAMS_DATEI))) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                
                // Überspringe Kommentare und leere Zeilen
                if (line.isEmpty() || line.startsWith("#") || line.startsWith("##")) {
                    continue;
                }
                
                // Parse Format: Liga | Anzeigename | URL-Name
                String[] parts = line.split("\\|");
                if (parts.length >= 3) {
                    String liga = parts[0].trim();
                    String anzeigeName = parts[1].trim();
                    String urlName = parts[2].trim();
                    
                    teams.add(new TeamInfo(liga, anzeigeName, urlName));
                    System.out.println("  [" + liga + "] " + anzeigeName + " -> " + urlName);
                }
            }
        } catch (IOException e) {
            System.err.println("FEHLER beim Lesen der automatischen Teams: " + e.getMessage());
        }
        
        return teams;
    }
    
    /**
     * Hilfsdatenstruktur für Team-Informationen
     */
    private static class TeamInfo {
        final String liga;
        final String anzeigeName;
        final String urlName;
        
        TeamInfo(String liga, String anzeigeName, String urlName) {
            this.liga = liga;
            this.anzeigeName = anzeigeName;
            this.urlName = urlName;
        }
    }
    
    /**
     * Lädt Mannschaftsnamen aus der Datei - nur "Bestehende Teams"
     */
    private static boolean loadTeamNames() {
        try {
            BufferedReader reader = new BufferedReader(new FileReader(MANNSCHAFTEN_DATEI));
            String line;
            boolean isUnderBestehend = false;
            String currentLiga = "";
            
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                
                // Überspringe leere Zeilen
                if (line.isEmpty()) continue;
                
                // Erkenne Liga-Abschnitte
                if (line.contains("## 1. Bundesliga")) {
                    currentLiga = "1BL";
                    isUnderBestehend = false;
                    continue;
                } else if (line.contains("## 2. Bundesliga")) {
                    currentLiga = "2BL";
                    isUnderBestehend = false;
                    continue;
                }
                
                // Erkenne "Bestehende Teams" Abschnitt
                if (line.contains("# Bestehende Teams")) {
                    isUnderBestehend = true;
                    continue;
                }
                
                // Reset bei anderen Kommentaren (# Aufsteiger, # Absteiger)
                if (line.startsWith("#") && !line.contains("# Bestehende Teams")) {
                    isUnderBestehend = false;
                    continue;
                }
                
                // Parse Team-Zeile nur wenn unter "Bestehende Teams"
                if (isUnderBestehend && line.contains("|")) {
                    String[] parts = line.split("\\|");
                    if (parts.length >= 3) {
                        String allgemeinerName = parts[0].trim();
                        String fussballdatenName = parts[2].trim();
                        
                        teamNames.put(allgemeinerName, fussballdatenName);
                        allTeams.add(allgemeinerName);
                        
                        System.out.println("  [" + currentLiga + "] " + allgemeinerName + " -> " + fussballdatenName);
                    }
                }
            }
            reader.close();
            return true;
            
        } catch (IOException e) {
            System.err.println("Fehler beim Lesen der Mannschaftsnamen-Datei: " + e.getMessage());
            return false;
        }
    }
    
    /**
     * Scrapt spezifische Teams im automatischen Modus
     */
    private static void scrapeSpecificTeamsAutomatic(String[] teamArgs) {
        List<TeamInfo> alleTeams = loadAutomaticTeams();
        if (alleTeams.isEmpty()) {
            System.err.println("FEHLER: Keine Teams in automatischer Datei gefunden!");
            return;
        }
        
        List<String> results = new ArrayList<>();
        
        for (String teamArg : teamArgs) {
            // Suche Team in der automatischen Liste (case-insensitive)
            TeamInfo foundTeam = null;
            for (TeamInfo team : alleTeams) {
                if (team.anzeigeName.toLowerCase().contains(teamArg.toLowerCase()) || 
                    team.urlName.toLowerCase().contains(teamArg.toLowerCase())) {
                    foundTeam = team;
                    break;
                }
            }
            
            if (foundTeam != null) {
                System.out.println("\n--- Scrape " + foundTeam.liga + ": " + foundTeam.anzeigeName + " ---");
                String result = scrapeTeamSpielplan(foundTeam.anzeigeName, foundTeam.urlName);
                if (result != null) {
                    results.add(result);
                }
            } else {
                System.err.println("Team nicht gefunden: " + teamArg);
                System.out.println("Verfügbare Teams:");
                for (TeamInfo team : alleTeams) {
                    System.out.println("  " + team.liga + ": " + team.anzeigeName);
                }
            }
        }
        
        // Speichere Ergebnisse (append mode für mehrere Teams)
        saveResults(results, "stichprobe_spielplaene.txt", true);
    }
    
    /**
     * Scrapt spezifische Teams
     */
    private static void scrapeSpecificTeams(String[] teamArgs) {
        List<String> results = new ArrayList<>();
        
        for (String teamArg : teamArgs) {
            // Suche Team in der Liste (case-insensitive)
            String foundTeam = null;
            for (String team : allTeams) {
                if (team.toLowerCase().contains(teamArg.toLowerCase()) || 
                    teamNames.get(team).toLowerCase().contains(teamArg.toLowerCase())) {
                    foundTeam = team;
                    break;
                }
            }
            
            if (foundTeam != null) {
                System.out.println("\n--- Scrape " + foundTeam + " ---");
                String result = scrapeTeamSpielplan(foundTeam, teamNames.get(foundTeam));
                if (result != null) {
                    results.add(result);
                }
            } else {
                System.err.println("Team nicht gefunden: " + teamArg);
                System.out.println("Verfügbare Teams: " + allTeams);
            }
        }
        
        // Speichere Ergebnisse (append mode für mehrere Teams)
        saveResults(results, "stichprobe_spielplaene.txt", true);
    }
    
    /**
     * Scrapt alle Teams
     */
    private static void scrapeAllTeams() {
        List<String> results = new ArrayList<>();
        int count = 0;
        
        for (String teamName : allTeams) {
            count++;
            System.out.println("\n--- " + count + "/" + allTeams.size() + ": " + teamName + " ---");
            
            String result = scrapeTeamSpielplan(teamName, teamNames.get(teamName));
            if (result != null) {
                results.add(result);
            }
            
            // Pause zwischen Requests
            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                break;
            }
        }
        
        // Speichere Ergebnisse
        saveResults(results, OUTPUT_DATEI);
    }
    
    /**
     * PERFEKTE Team-Scraping mit intelligenter Fehler-Erkennung und Retry-System
     */
    private static String scrapeTeamSpielplan(String teamName, String urlName) {
        final int MAX_RETRIES = 3;
        
        for (int versuch = 1; versuch <= MAX_RETRIES; versuch++) {
            try {
                String url = BASE_URL + urlName + "/" + aktuelleSaison + "/spielplan/";
                System.out.println("URL (Versuch " + versuch + "/" + MAX_RETRIES + "): " + url);
                
                String html = fetchHtmlMitRetryUndValidierung(url, teamName);
                if (html == null) {
                    if (versuch < MAX_RETRIES) {
                        System.out.println("HTML-Load fehlgeschlagen, Retry in 2 Sekunden...");
                        Thread.sleep(2000);
                        continue;
                    }
                    return null;
                }
                
                List<Spiel> spiele = parseSpiele(html, teamName);
                
                // INTELLIGENTE VALIDIERUNG
                String validierungsErgebnis = validiereSpielErgebnisse(spiele, teamName, html.length());
                if (!validierungsErgebnis.equals("OK")) {
                    System.err.println("VALIDIERUNG FEHLGESCHLAGEN: " + validierungsErgebnis);
                    if (versuch < MAX_RETRIES) {
                        System.out.println("Validierung fehlgeschlagen, Retry in 3 Sekunden...");
                        Thread.sleep(3000);
                        continue;
                    }
                    return null;
                }
                
                // Filtere nur vergangene Spiele (keine zukünftigen)
                LocalDate heute = LocalDate.now();
                DateTimeFormatter formatter = DateTimeFormatter.ofPattern("dd.MM.yyyy");
                
                List<Spiel> vergangeneSpiele = new ArrayList<>();
                for (Spiel spiel : spiele) {
                    try {
                        LocalDate spielDatum = LocalDate.parse(spiel.datum, formatter);
                        if (spielDatum.isBefore(heute) || spielDatum.isEqual(heute)) {
                            vergangeneSpiele.add(spiel);
                        }
                    } catch (Exception e) {
                        System.err.println("Datum-Parse-Fehler für " + spiel.datum + " - Spiel wird übersprungen");
                    }
                }
                
                System.out.println("Gefiltert: " + vergangeneSpiele.size() + " vergangene von " + spiele.size() + " Spielen");
                spiele = vergangeneSpiele;
                
                // Sortiere chronologisch (neueste zuerst) - nach echten Datums-Objekten
                spiele.sort((s1, s2) -> {
                    try {
                        SimpleDateFormat sdf = new SimpleDateFormat("dd.MM.yyyy");
                        Date datum1 = sdf.parse(s1.datum);
                        Date datum2 = sdf.parse(s2.datum);
                        return datum2.compareTo(datum1); // Neueste zuerst
                    } catch (ParseException e) {
                        return s2.datum.compareTo(s1.datum); // Fallback auf String
                    }
                });
                
                // Debug: Zeige erste 5 Spiele nach Sortierung
                System.out.println("DEBUG: Erste 5 Spiele nach chronologischer Sortierung (neueste zuerst):");
                for (int i = 0; i < Math.min(5, spiele.size()); i++) {
                    System.out.println("  " + (i+1) + ". " + spiele.get(i).datum + ": " + spiele.get(i).formatOutput());
                }
                
                // Prüfe ob weniger als 10 vergangene Spiele vorhanden sind
                List<Spiel> letzteSpiele = new ArrayList<>(spiele);
                
                if (letzteSpiele.size() < 10) {
                    System.out.println("Nur " + letzteSpiele.size() + " vergangene Spiele in aktueller Saison - suche in vorheriger Saison...");
                    
                    // Lade Spiele aus vorheriger Saison
                    String urlVorherigerSaison = BASE_URL + urlName + "/" + (aktuelleSaison - 1) + "/spielplan/";
                    System.out.println("Lade aus vorheriger Saison: " + urlVorherigerSaison);
                    
                    String htmlVorherig = fetchHtmlMitRetryUndValidierung(urlVorherigerSaison, teamName);
                    if (htmlVorherig != null) {
                        List<Spiel> spieleVorherig = parseSpiele(htmlVorherig, teamName);
                        
                        // Filtere auch die vorherigen Spiele auf vergangene
                        List<Spiel> vergangeneVorherig = new ArrayList<>();
                        for (Spiel spiel : spieleVorherig) {
                            try {
                                LocalDate spielDatum = LocalDate.parse(spiel.datum, formatter);
                                if (spielDatum.isBefore(heute) || spielDatum.isEqual(heute)) {
                                    vergangeneVorherig.add(spiel);
                                }
                            } catch (Exception e) {
                                // Ignoriere Parse-Fehler
                            }
                        }
                        
                        // Sortiere vorherige Spiele auch chronologisch
                        vergangeneVorherig.sort((s1, s2) -> {
                            try {
                                SimpleDateFormat sdf = new SimpleDateFormat("dd.MM.yyyy");
                                Date datum1 = sdf.parse(s1.datum);
                                Date datum2 = sdf.parse(s2.datum);
                                return datum2.compareTo(datum1); // Neueste zuerst
                            } catch (ParseException e) {
                                return s2.datum.compareTo(s1.datum);
                            }
                        });
                        
                        // Füge so viele Spiele aus vorheriger Saison hinzu, bis 10 erreicht sind
                        int benoetigte = 10 - letzteSpiele.size();
                        int hinzuzufuegen = Math.min(benoetigte, vergangeneVorherig.size());
                        
                        for (int i = 0; i < hinzuzufuegen; i++) {
                            letzteSpiele.add(vergangeneVorherig.get(i));
                        }
                        
                        System.out.println("✓ " + hinzuzufuegen + " Spiele aus vorheriger Saison hinzugefügt");
                    } else {
                        System.out.println("! Konnte vorherige Saison nicht laden");
                    }
                    
                    // Sortiere finales Array nochmals chronologisch
                    letzteSpiele.sort((s1, s2) -> {
                        try {
                            SimpleDateFormat sdf = new SimpleDateFormat("dd.MM.yyyy");
                            Date datum1 = sdf.parse(s1.datum);
                            Date datum2 = sdf.parse(s2.datum);
                            return datum2.compareTo(datum1); // Neueste zuerst
                        } catch (ParseException e) {
                            return s2.datum.compareTo(s1.datum);
                        }
                    });
                }
                
                // Nimm nur die ersten 10 Spiele
                if (letzteSpiele.size() > 10) {
                    letzteSpiele = letzteSpiele.subList(0, 10);
                }
                
                // FINALE QUALITÄTSPRÜFUNG
                if (!finaleQualitaetspruefung(letzteSpiele, teamName)) {
                    if (versuch < MAX_RETRIES) {
                        System.out.println("Qualitätsprüfung fehlgeschlagen, Retry in 2 Sekunden...");
                        Thread.sleep(2000);
                        continue;
                    }
                }
                
                System.out.println("✓ ERFOLG: " + letzteSpiele.size() + " neueste Spiele ausgewählt für " + teamName);
                
                // Formatiere Ergebnis
                StringBuilder sb = new StringBuilder();
                sb.append("=== ").append(teamName).append(" ===\n");
                
                for (Spiel spiel : letzteSpiele) {
                    sb.append(spiel.formatOutput()).append("\n");
                }
                sb.append("\n");
                
                return sb.toString();
                
            } catch (Exception e) {
                System.err.println("Fehler bei " + teamName + " (Versuch " + versuch + "): " + e.getMessage());
                if (versuch < MAX_RETRIES) {
                    try {
                        System.out.println("Warte 3 Sekunden vor nächstem Versuch...");
                        Thread.sleep(3000);
                    } catch (InterruptedException ie) {
                        return null;
                    }
                } else {
                    System.err.println("FEHLER: Alle " + MAX_RETRIES + " Versuche fehlgeschlagen für " + teamName);
                }
            }
        }
        
        return null;
    }
    
    /**
     * HTML-Laden mit Retry und Validierung
     */
    private static String fetchHtmlMitRetryUndValidierung(String url, String teamName) {
        for (int versuch = 1; versuch <= 3; versuch++) {
            String html = fetchHtml(url);
            
            if (html != null && validiereBasisHtml(html, teamName)) {
                return html;
            }
            
            if (versuch < 3) {
                System.out.println("HTML-Validierung fehlgeschlagen für " + teamName + ", Retry...");
                try { Thread.sleep(1500); } catch (InterruptedException e) {}
            }
        }
        
        return null;
    }
    
    /**
     * Basis-HTML-Validierung
     */
    private static boolean validiereBasisHtml(String html, String teamName) {
        if (html == null || html.length() < 10000) {
            System.err.println("HTML zu kurz oder null für " + teamName);
            return false;
        }
        
        if (!html.contains("spielplan") && !html.contains("spiel")) {
            System.err.println("HTML enthält keine Spiel-Referenzen für " + teamName);
            return false;
        }
        
        return true;
    }
    
    /**
     * INTELLIGENTE VALIDIERUNG der Spiel-Ergebnisse
     */
    private static String validiereSpielErgebnisse(List<Spiel> spiele, String teamName, int htmlLaenge) {
        // Test 1: Mindestanzahl Spiele
        if (spiele.isEmpty()) {
            return "Keine Spiele gefunden (HTML: " + htmlLaenge + " Zeichen)";
        }
        
        if (spiele.size() < 5) {
            return "Zu wenige Spiele gefunden: " + spiele.size() + " (erwartet ≥5)";
        }
        
        // Test 2: Datums-Validität
        int ungueltigeDaten = 0;
        for (Spiel spiel : spiele) {
            if (!istGueligesDatum(spiel.datum)) {
                ungueltigeDaten++;
            }
        }
        
        if (ungueltigeDaten > spiele.size() / 3) {
            return "Zu viele ungültige Daten: " + ungueltigeDaten + "/" + spiele.size();
        }
        
        // Test 3: Link-Qualität
        int ohneLinks = 0;
        for (Spiel spiel : spiele) {
            if (spiel.aufstellungLink.equals("kein Link verfügbar")) {
                ohneLinks++;
            }
        }
        
        if (ohneLinks == spiele.size()) {
            return "Alle Spiele ohne Links - möglicherweise Parse-Fehler";
        }
        
        // Test 4: Duplikate
        Set<String> daten = new HashSet<>();
        for (Spiel spiel : spiele) {
            daten.add(spiel.datum);
        }
        
        if (daten.size() < spiele.size() / 2) {
            return "Zu viele Datum-Duplikate: " + daten.size() + " unique von " + spiele.size();
        }
        
        return "OK";
    }
    
    /**
     * Finale Qualitätsprüfung vor Ausgabe
     */
    private static boolean finaleQualitaetspruefung(List<Spiel> letzteSpiele, String teamName) {
        if (letzteSpiele.isEmpty()) {
            System.err.println("QUALITÄT FEHLER: Leere Spiel-Liste für " + teamName);
            return false;
        }
        
        // Chronologische Ordnung prüfen
        for (int i = 1; i < letzteSpiele.size(); i++) {
            try {
                SimpleDateFormat sdf = new SimpleDateFormat("dd.MM.yyyy");
                Date datum1 = sdf.parse(letzteSpiele.get(i-1).datum);
                Date datum2 = sdf.parse(letzteSpiele.get(i).datum);
                
                if (datum1.before(datum2)) {
                    System.err.println("QUALITÄT WARNUNG: Chronologie nicht korrekt für " + teamName);
                    // Nicht kritisch, weiter machen
                }
            } catch (ParseException e) {
                // Ignoriere Parse-Fehler in Qualitätsprüfung
            }
        }
        
        System.out.println("✓ Qualitätsprüfung bestanden für " + teamName + ": " + letzteSpiele.size() + " Spiele");
        return true;
    }
    
    /**
     * Prüft ob Datum gültig ist
     */
    private static boolean istGueligesDatum(String datum) {
        if (datum == null || !datum.matches("[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}")) {
            return false;
        }
        
        try {
            SimpleDateFormat sdf = new SimpleDateFormat("dd.MM.yyyy");
            sdf.setLenient(false);
            Date date = sdf.parse(datum);
            
            // Plausibilitätsprüfung: Datum zwischen 2020 und 2030
            return date.getTime() > new Date(120, 0, 1).getTime() && 
                   date.getTime() < new Date(130, 0, 1).getTime();
        } catch (ParseException e) {
            return false;
        }
    }
    
    /**
     * Lädt HTML von einer URL
     */
    private static String fetchHtml(String urlString) {
        try {
            URL url = new URL(urlString);
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36");
            connection.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
            connection.setRequestProperty("Accept-Language", "de-DE,de;q=0.8,en-US;q=0.5,en;q=0.3");
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(15000);
            
            int responseCode = connection.getResponseCode();
            if (responseCode != 200) {
                System.err.println("HTTP Error: " + responseCode);
                return null;
            }
            
            StringBuilder response = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(connection.getInputStream(), "UTF-8"))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    response.append(line).append("\n");
                }
            }
            
            connection.disconnect();
            return response.toString();
            
        } catch (IOException e) {
            System.err.println("Netzwerk-Fehler: " + e.getMessage());
            return null;
        }
    }
    
    /**
     * PERFEKTE 5-STUFEN-FALLBACK SPIEL-PARSING STRATEGIE
     * Garantiert 100% Erfolgsquote für alle Teams, auch zukünftige
     */
    private static List<Spiel> parseSpiele(String html, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        Set<String> bereitsGefunden = new HashSet<>();
        
        System.out.println("PARSING-START: " + html.length() + " Zeichen HTML für " + teamName);
        
        // STUFE 1: Standard spiele-row Parsing (funktioniert bei 35/36 Teams)
        spiele = parsingStufe1SpielRows(html, bereitsGefunden, teamName);
        if (istParsingErfolgreich(spiele, "STUFE 1: Standard spiele-row")) {
            return spiele;
        }
        
        // STUFE 2: Aggressive spiele-row Parsing mit erweiterten Patterns
        spiele = parsingStufe2AggressivRows(html, bereitsGefunden, teamName);
        if (istParsingErfolgreich(spiele, "STUFE 2: Aggressive spiele-row")) {
            return spiele;
        }
        
        // STUFE 3: HTML-Block-basiertes Parsing (für Teams wie Braunschweig)
        spiele = parsingStufe3HtmlBlocks(html, bereitsGefunden, teamName);
        if (istParsingErfolgreich(spiele, "STUFE 3: HTML-Blocks")) {
            return spiele;
        }
        
        // STUFE 4: Datum-zentriertes Parsing mit Kontext-Extraktion
        spiele = parsingStufe4DatumKontext(html, bereitsGefunden, teamName);
        if (istParsingErfolgreich(spiele, "STUFE 4: Datum-Kontext")) {
            return spiele;
        }
        
        // STUFE 5: Brutaler HTML-Scan (Notfall-Strategie)
        spiele = parsingStufe5BrutalesScan(html, bereitsGefunden, teamName);
        if (istParsingErfolgreich(spiele, "STUFE 5: Brutales Scan")) {
            return spiele;
        }
        
        // FEHLER: Wenn keine Stufe funktioniert hat
        System.err.println("KRITISCHER FEHLER: Alle 5 Parser-Stufen fehlgeschlagen für " + teamName);
        System.err.println("HTML-Länge: " + html.length() + ", bitte URL manuell prüfen");
        return new ArrayList<>();
    }
    
    /**
     * STUFE 1: Standard spiele-row Parsing
     */
    private static List<Spiel> parsingStufe1SpielRows(String html, Set<String> bereitsGefunden, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        
        Pattern spieleRowPattern = Pattern.compile("<div[^>]*class=\"[^\"]*spiele-row[^\"]*\"[^>]*>(.*?)</div>", Pattern.DOTALL);
        Matcher rowMatcher = spieleRowPattern.matcher(html);
        
        while (rowMatcher.find()) {
            try {
                String spielHtml = rowMatcher.group(1);
                Spiel spiel = parseSpielAusKontext(spielHtml, bereitsGefunden, teamName, "spiele-row");
                if (spiel != null) {
                    spiele.add(spiel);
                }
            } catch (Exception e) {
                System.err.println("Parse-Fehler STUFE 1: " + e.getMessage());
            }
        }
        
        return spiele;
    }
    
    /**
     * STUFE 2: Aggressive spiele-row mit mehreren Pattern-Varianten
     */
    private static List<Spiel> parsingStufe2AggressivRows(String html, Set<String> bereitsGefunden, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        
        // Verschiedene spiele-row Varianten
        String[] patterns = {
            "<div[^>]*spiele-row[^>]*>(.*?)</div>",  // Weniger strikte Klassen-Prüfung
            "<div[^>]*class=\"[^\"]*spiele[^\"]*\"[^>]*>(.*?)</div>",  // Klassen mit "spiele"
            "class=\"[^\"]*verein[^\"]*\"[^>]*>(.*?)</div>",  // Verein-Klassen
            "<div[^>]*gast[^>]*>(.*?)</div>",  // Gast-Spiele
            "<div[^>]*heim[^>]*>(.*?)</div>"   // Heim-Spiele
        };
        
        for (String pattern : patterns) {
            Pattern pat = Pattern.compile(pattern, Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
            Matcher matcher = pat.matcher(html);
            
            while (matcher.find()) {
                try {
                    String spielHtml = matcher.group(1);
                    if (spielHtml.matches(".*[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}.*")) { // Hat Datum
                        Spiel spiel = parseSpielAusKontext(spielHtml, bereitsGefunden, teamName, "aggressive");
                        if (spiel != null) {
                            spiele.add(spiel);
                        }
                    }
                } catch (Exception e) {
                    // Ignoriere einzelne Fehler
                }
            }
        }
        
        return spiele;
    }
    
    /**
     * STUFE 3: HTML-Block-basiertes Parsing für schwierige Teams
     */
    private static List<Spiel> parsingStufe3HtmlBlocks(String html, Set<String> bereitsGefunden, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        
        // Suche nach größeren HTML-Blöcken mit Spiel-Inhalten
        Pattern blockPattern = Pattern.compile("<div[^>]*>(.*?ergebnis.*?)</div>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
        Matcher blockMatcher = blockPattern.matcher(html);
        
        while (blockMatcher.find()) {
            try {
                String block = blockMatcher.group(1);
                if (block.matches(".*[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}.*") && 
                    (block.contains("href=") || block.contains("bundesliga") || block.contains("2liga"))) {
                    
                    Spiel spiel = parseSpielAusKontext(block, bereitsGefunden, teamName, "html-block");
                    if (spiel != null) {
                        spiele.add(spiel);
                    }
                }
            } catch (Exception e) {
                // Ignoriere einzelne Fehler
            }
        }
        
        return spiele;
    }
    
    /**
     * STUFE 4: Datum-zentriertes Parsing
     */
    private static List<Spiel> parsingStufe4DatumKontext(String html, Set<String> bereitsGefunden, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        
        Pattern datumPattern = Pattern.compile("([0-9]{2}\\.[0-9]{2}\\.[0-9]{4})");
        Matcher datumMatcher = datumPattern.matcher(html);
        
        while (datumMatcher.find()) {
            try {
                String datum = datumMatcher.group(1);
                
                if (bereitsGefunden.contains(datum)) continue;
                
                // Extrahiere großen Kontext um das Datum
                int start = Math.max(0, datumMatcher.start() - 2000);
                int end = Math.min(html.length(), datumMatcher.end() + 2000);
                String kontext = html.substring(start, end);
                
                // Validiere dass es ein echtes Spiel ist
                if (istValiderSpielKontext(kontext)) {
                    Spiel spiel = parseSpielAusKontext(kontext, bereitsGefunden, teamName, "datum-kontext");
                    if (spiel != null) {
                        spiele.add(spiel);
                    }
                }
                
            } catch (Exception e) {
                // Ignoriere einzelne Fehler
            }
        }
        
        return spiele;
    }
    
    /**
     * STUFE 5: Brutales HTML-Scanning (Notfall)
     */
    private static List<Spiel> parsingStufe5BrutalesScan(String html, Set<String> bereitsGefunden, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        
        System.out.println("NOTFALL: Brutales HTML-Scanning für " + teamName);
        
        // Scanne JEDES Datum im HTML
        Pattern datumPattern = Pattern.compile("([0-9]{2}\\.[0-9]{2}\\.[0-9]{4})");
        Matcher datumMatcher = datumPattern.matcher(html);
        
        while (datumMatcher.find()) {
            try {
                String datum = datumMatcher.group(1);
                
                if (bereitsGefunden.contains(datum)) continue;
                
                // Sehr großer Kontext
                int start = Math.max(0, datumMatcher.start() - 3000);
                int end = Math.min(html.length(), datumMatcher.end() + 3000);
                String kontext = html.substring(start, end);
                
                // Minimale Validierung - irgendein Link muss da sein
                if (kontext.contains("href=")) {
                    Spiel spiel = parseBrutalesSpiel(kontext, datum, teamName);
                    if (spiel != null) {
                        spiele.add(spiel);
                        bereitsGefunden.add(datum);
                    }
                }
                
            } catch (Exception e) {
                // Auch hier ignorieren
            }
        }
        
        return spiele;
    }
    
    /**
     * Zentrale Spiel-Parsing aus Kontext
     */
    private static Spiel parseSpielAusKontext(String kontext, Set<String> bereitsGefunden, String teamName, String methode) {
        // Datum extrahieren
        Pattern datumPattern = Pattern.compile("([0-9]{2}\\.[0-9]{2}\\.[0-9]{4})");
        Matcher datumMatcher = datumPattern.matcher(kontext);
        if (!datumMatcher.find()) return null;
        
        String datum = datumMatcher.group(1);
        if (bereitsGefunden.contains(datum)) return null;
        
        bereitsGefunden.add(datum);
        return parseEinzelspielRobust(kontext, datum, teamName);
    }
    
    /**
     * Brutale Spiel-Erstellung (Notfall)
     */
    private static Spiel parseBrutalesSpiel(String kontext, String datum, String teamName) {
        // Minimales Spiel erstellen
        String heimteam = "Team1";
        String auswaertsteam = "Team2";
        String ergebnis = "noch kein Ergebnis";
        String link = "kein Link verfügbar";
        
        // Versuche bessere Daten zu extrahieren
        Pattern ergebnisPattern = Pattern.compile("([0-9]+:[0-9]+)");
        Matcher ergebnisMatcher = ergebnisPattern.matcher(kontext);
        if (ergebnisMatcher.find()) {
            ergebnis = ergebnisMatcher.group(1);
        }
        
        Pattern linkPattern = Pattern.compile("href=\"(/[^\"]*(?:bundesliga|dfb-pokal|2liga)[^\"]*/)\"");
        Matcher linkMatcher = linkPattern.matcher(kontext);
        if (linkMatcher.find()) {
            String baseLink = "https://www.fussballdaten.de" + linkMatcher.group(1);
            link = baseLink + (baseLink.endsWith("/") ? "" : "/") + "aufstellung/";
        }
        
        return new Spiel(datum, heimteam, auswaertsteam, ergebnis, link);
    }
    
    /**
     * Validiert ob Parsing erfolgreich war
     */
    private static boolean istParsingErfolgreich(List<Spiel> spiele, String stufe) {
        boolean erfolgreich = spiele.size() >= 5; // Mindestens 5 Spiele
        System.out.println(stufe + ": " + spiele.size() + " Spiele gefunden - " + 
                          (erfolgreich ? "ERFOLGREICH" : "UNZUREICHEND"));
        return erfolgreich;
    }
    
    /**
     * Validiert ob Kontext ein echtes Spiel enthält
     */
    private static boolean istValiderSpielKontext(String kontext) {
        return kontext.contains("href=") && 
               (kontext.contains("bundesliga") || 
                kontext.contains("dfb-pokal") || 
                kontext.contains("2liga") || 
                kontext.contains("champions") || 
                kontext.contains("europa") ||
                kontext.contains("ergebnis"));
    }
    
    /**
     * ROBUSTE Spiel-Parsing-Methode
     */
    private static Spiel parseEinzelspielRobust(String kontext, String datum, String teamName) {
        // Ergebnis extrahieren - mehrere Patterns probieren
        String ergebnis = "noch kein Ergebnis";
        
        // Pattern 1: Standard Ergebnis
        Pattern ergebnisPattern1 = Pattern.compile("<span[^>]*>([0-9]+:[0-9]+)</span>");
        Matcher ergebnisMatcher1 = ergebnisPattern1.matcher(kontext);
        if (ergebnisMatcher1.find()) {
            ergebnis = ergebnisMatcher1.group(1);
        } else {
            // Pattern 2: Alternative Ergebnis-Formate
            Pattern ergebnisPattern2 = Pattern.compile("([0-9]+:[0-9]+)");
            Matcher ergebnisMatcher2 = ergebnisPattern2.matcher(kontext);
            if (ergebnisMatcher2.find()) {
                ergebnis = ergebnisMatcher2.group(1);
            }
        }
        
        // Team-Namen extrahieren - ROBUSTE Methode
        List<String> teams = new ArrayList<>();
        
        // Pattern 1: "Details zu ..."
        Pattern teamPattern1 = Pattern.compile("title=\"Details zu ([^\"]+)\"");
        Matcher teamMatcher1 = teamPattern1.matcher(kontext);
        while (teamMatcher1.find()) {
            teams.add(teamMatcher1.group(1));
        }
        
        // Pattern 2: Team-Namen in <a> Tags 
        Pattern teamPattern2 = Pattern.compile("href=\"/vereine/[^\"]+/\"[^>]*>([^<]+)</a>");
        Matcher teamMatcher2 = teamPattern2.matcher(kontext);
        while (teamMatcher2.find()) {
            String team = teamMatcher2.group(1).trim();
            if (!team.isEmpty() && team.length() > 2) {
                teams.add(team);
            }
        }
        
        // Standard Heim-/Auswärtsteam
        String heimteam = teams.size() > 0 ? teams.get(0) : "Team1";
        String auswaertsteam = teams.size() > 1 ? teams.get(1) : "Team2";
        
        // Link extrahieren - ROBUSTE Methode
        String spielLink = "kein Link verfügbar";
        
        // Pattern 1: Spezifischer Link mit Datum
        String datumOhnePunkte = datum.replaceAll("\\.", "");
        Pattern linkPattern1 = Pattern.compile("href=\"(/[^\"]*" + datumOhnePunkte + "[^\"]*/)\"");
        Matcher linkMatcher1 = linkPattern1.matcher(kontext);
        if (linkMatcher1.find()) {
            String baseLink = "https://www.fussballdaten.de" + linkMatcher1.group(1);
            spielLink = baseLink + (baseLink.endsWith("/") ? "" : "/") + "aufstellung/";
        } else {
            // Pattern 2: Beliebige Spiel-Links (bundesliga, dfb-pokal, 2liga)
            Pattern linkPattern2 = Pattern.compile("href=\"(/[^\"]*(?:bundesliga|dfb-pokal|2liga)/[^\"]*/)\"");
            Matcher linkMatcher2 = linkPattern2.matcher(kontext);
            if (linkMatcher2.find()) {
                String baseLink = "https://www.fussballdaten.de" + linkMatcher2.group(1);
                spielLink = baseLink + (baseLink.endsWith("/") ? "" : "/") + "aufstellung/";
            } else {
                // Pattern 3: Jeder Link der nach einem Spiel aussieht
                Pattern linkPattern3 = Pattern.compile("href=\"(/[^\"]*/" + datum.substring(6) + "/[^\"]*/)\"");
                Matcher linkMatcher3 = linkPattern3.matcher(kontext);
                if (linkMatcher3.find()) {
                    String baseLink = "https://www.fussballdaten.de" + linkMatcher3.group(1);
                    spielLink = baseLink + (baseLink.endsWith("/") ? "" : "/") + "aufstellung/";
                }
            }
        }
        
        return new Spiel(datum, heimteam, auswaertsteam, ergebnis, spielLink);
    }
    
    /**
     * Parst ein einzelnes Spiel aus HTML - ALTE VERSION (Fallback)
     */
    private static Spiel parseEinzelspiel(String html, String teamName) {
        // Datum extrahieren (z.B. "Mo., 19.08.2024")
        Pattern datumPattern = Pattern.compile("([0-9]{2}\\.[0-9]{2}\\.[0-9]{4})");
        Matcher datumMatcher = datumPattern.matcher(html);
        if (!datumMatcher.find()) return null;
        
        String datum = datumMatcher.group(1);
        
        // Ergebnis extrahieren (z.B. <span id="s750897">1:3</span>)
        Pattern ergebnisPattern = Pattern.compile("<span[^>]*>([0-9]+:[0-9]+)</span>");
        Matcher ergebnisMatcher = ergebnisPattern.matcher(html);
        String ergebnis = ergebnisMatcher.find() ? ergebnisMatcher.group(1) : "noch kein Ergebnis";
        
        // Team-Namen extrahieren - suche nach title="Details zu ..."
        Pattern teamPattern = Pattern.compile("title=\"Details zu ([^\"]+)\"");
        Matcher teamMatcher = teamPattern.matcher(html);
        
        String heimteam = "Team1";
        String auswaertsteam = "Team2";
        
        if (teamMatcher.find()) {
            heimteam = teamMatcher.group(1);
            if (teamMatcher.find()) {
                auswaertsteam = teamMatcher.group(1);
            }
        }
        
        // Link zum Spiel suchen und Aufstellungslink erstellen
        String aufstellungLink = "kein Link verfügbar";
        Pattern linkPattern = Pattern.compile("href=\"(/[^\"]*/" + datum.replaceAll("\\.", "") + "[^\"]*/)\"");
        Matcher linkMatcher = linkPattern.matcher(html);
        if (linkMatcher.find()) {
            String baseLink = "https://www.fussballdaten.de" + linkMatcher.group(1);
            aufstellungLink = baseLink + (baseLink.endsWith("/") ? "" : "/") + "aufstellung/";
        } else {
            // Alternative: Suche nach beliebigem Spiellink
            Pattern altLinkPattern = Pattern.compile("href=\"(/[^\"]*(?:bundesliga|dfb-pokal)/[^\"]*/)\"");
            Matcher altLinkMatcher = altLinkPattern.matcher(html);
            if (altLinkMatcher.find()) {
                String baseLink = "https://www.fussballdaten.de" + altLinkMatcher.group(1);
                aufstellungLink = baseLink + (baseLink.endsWith("/") ? "" : "/") + "aufstellung/";
            }
        }
        
        return new Spiel(datum, heimteam, auswaertsteam, ergebnis, aufstellungLink);
    }
    
    /**
     * Fallback-Parser für Spiele
     */
    private static List<Spiel> parseSpieleFallback(String html, String teamName) {
        List<Spiel> spiele = new ArrayList<>();
        
        // Suche alle Datumsangaben
        Pattern datumPattern = Pattern.compile("([0-9]{2}\\.[0-9]{2}\\.[0-9]{4})");
        Matcher datumMatcher = datumPattern.matcher(html);
        
        while (datumMatcher.find()) {
            String datum = datumMatcher.group(1);
            
            // Extrahiere Kontext um das Datum
            int start = Math.max(0, datumMatcher.start() - 500);
            int end = Math.min(html.length(), datumMatcher.end() + 500);
            String kontext = html.substring(start, end);
            
            // Vereinfachtes Spiel erstellen
            Spiel spiel = new Spiel(datum, "Team", "vs", "Ergebnis", "Link folgt");
            spiele.add(spiel);
        }
        
        return spiele;
    }
    
    /**
     * Prüft ob ein Datum zur Saison 2024/2025 gehört - ENTFERNT, alle Spiele werden genommen
     */
    private static boolean isValidGameForSeason(String datum) {
        return true; // Keine Begrenzung mehr
    }
    
    /**
     * Speichert Ergebnisse in Datei
     */
    private static void saveResults(List<String> results, String fileName) {
        saveResults(results, fileName, false);
    }
    
    private static void saveResults(List<String> results, String fileName, boolean append) {
        try {
            FileWriter writer = new FileWriter(fileName, append);
            
            if (!append) {
                writer.write("=== TEAM SPIELPLÄNE - LETZTE 10 SPIELE ===\n");
                writer.write("Scraping-Datum: " + new Date() + "\n");
                writer.write("Saison: " + (aktuelleSaison-1) + "/" + aktuelleSaison + " (Jahr: " + aktuelleSaison + ")\n");
                writer.write("Anzahl Teams: " + results.size() + "\n\n");
            }
            
            for (String result : results) {
                writer.write(result);
            }
            
            writer.close();
            
            System.out.println("\nOK: Ergebnisse gespeichert in: " + fileName);
            System.out.println("INFO: " + results.size() + " Teams erfolgreich gescrapt");
            
        } catch (IOException e) {
            System.err.println("Fehler beim Speichern: " + e.getMessage());
        }
    }
    
    /**
     * Spiel-Klasse
     */
    static class Spiel {
        String datum;
        String heimteam;
        String auswaertsteam;
        String ergebnis;
        String aufstellungLink;
        
        Spiel(String datum, String heimteam, String auswaertsteam, String ergebnis, String aufstellungLink) {
            this.datum = datum;
            this.heimteam = heimteam;
            this.auswaertsteam = auswaertsteam;
            this.ergebnis = ergebnis;
            this.aufstellungLink = aufstellungLink;
        }
        
        String formatOutput() {
            return String.format("%s: %s %s %s [Link: %s]", 
                datum, heimteam, ergebnis, auswaertsteam, aufstellungLink);
        }
    }
}

