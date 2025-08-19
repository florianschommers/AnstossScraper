import java.io.*;
import java.net.*;
import java.util.*;
import java.util.regex.*;

public class AktuelleTeamsScraper {
    
    private static final String BASE_URL_1BL = "https://www.fussballdaten.de/bundesliga/";
    private static final String BASE_URL_2BL = "https://www.fussballdaten.de/2liga/";
    private static final String TABELLE_SUFFIX = "/tabelle/";
    private static final String OUTPUT_FILE = "aktuelle_teams_automatisch.txt";
    
    private static List<Team> allTeams = new ArrayList<>();
    
    public static void main(String[] args) {
        System.out.println("=== Aktueller Teams Scraper ===");
        
        int aktuellesSaison = findeAktuelleSaison();
        if (aktuellesSaison == -1) {
            System.err.println("Keine aktuelle Saison gefunden!");
            return;
        }
        
        System.out.println("Aktuelle Saison gefunden: " + (aktuellesSaison-1) + "/" + aktuellesSaison);
        
        // Scrape 1. Bundesliga
        System.out.println("\n--- Scrape 1. Bundesliga ---");
        List<Team> teams1BL = scrapeTabelle(BASE_URL_1BL + aktuellesSaison + TABELLE_SUFFIX, "1BL");
        
        // Scrape 2. Bundesliga  
        System.out.println("\n--- Scrape 2. Bundesliga ---");
        List<Team> teams2BL = scrapeTabelle(BASE_URL_2BL + aktuellesSaison + TABELLE_SUFFIX, "2BL");
        
        if (teams1BL.isEmpty() && teams2BL.isEmpty()) {
            System.err.println("Keine Teams gefunden!");
            return;
        }
        
        allTeams.addAll(teams1BL);
        allTeams.addAll(teams2BL);
        
        System.out.println("\n=== ERGEBNIS ===");
        System.out.println("1. Bundesliga: " + teams1BL.size() + " Teams");
        System.out.println("2. Bundesliga: " + teams2BL.size() + " Teams");
        System.out.println("Gesamt: " + allTeams.size() + " Teams");
        
        // Speichere Teams
        speichereTeams(aktuellesSaison);
        
        System.out.println("\nGespeichert in: " + OUTPUT_FILE);
    }
    
    /**
     * Findet die aktuelle Saison durch Testen der URLs
     * Startet mit aktuellem Jahr + 2 um zukunftssicher zu sein
     * KRITISCHE ANFORDERUNG: Muss mindestens aktuelles Jahr oder aktuelles Jahr + 1 finden!
     */
    private static int findeAktuelleSaison() {
        int aktuellJahr = java.time.Year.now().getValue();
        int startJahr = aktuellJahr + 2;
        int mindestJahr = aktuellJahr; // ABSOLUTE MINDESTANFORDERUNG
        
        System.out.println("Aktuelles Jahr: " + aktuellJahr);
        System.out.println("KRITISCH: Mindestens Saison " + (mindestJahr-1) + "/" + mindestJahr + " MUSS gefunden werden!");
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
        System.err.println("System ist defekt - kann nicht fortfahren!");
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
     * ROBUSTE Validierung durch Zählung der Team-Links
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
        // Das berücksichtigt mögliche Parsing-Probleme bei 1-3 Teams
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
     * Scrapt eine Liga-Tabelle
     */
    private static List<Team> scrapeTabelle(String url, String liga) {
        List<Team> teams = new ArrayList<>();
        
        try {
            System.out.println("URL: " + url);
            String html = fetchHtml(url);
            
            if (html == null) {
                System.err.println("Konnte HTML nicht laden");
                return teams;
            }
            
            System.out.println("HTML-Länge: " + html.length() + " Zeichen");
            
            // ROBUSTE Tabellen-Suche mit mehreren Ansätzen
            int tabelleStart = html.indexOf("<table");
            int tabelleEnde = -1;
            
            if (tabelleStart != -1) {
                tabelleEnde = html.indexOf("</table>", tabelleStart);
                if (tabelleEnde != -1) {
                    tabelleEnde += 8; // "</table>" Länge
                    String tabelleHtml = html.substring(tabelleStart, Math.min(tabelleEnde, html.length()));
                    System.out.println("Tabelle gefunden (" + tabelleHtml.length() + " Zeichen)");
                    System.out.println("Tabelle-Inhalt: " + tabelleHtml.substring(0, Math.min(500, tabelleHtml.length())) + "...");
                } else {
                    System.out.println("Tabelle-Start gefunden, aber kein Ende - verwende ganzes HTML");
                }
            } else {
                System.out.println("Keine <table> gefunden - verwende ganzes HTML für Parsing");
            }
            
            // ZUSÄTZLICHE Validierung: Prüfe /vereine/ Links
            Pattern vereineLinkPattern = Pattern.compile("/vereine/[^/\"]+/\\d+/", Pattern.CASE_INSENSITIVE);
            Matcher vereineMatcher = vereineLinkPattern.matcher(html);
            int anzahlVereine = 0;
            while (vereineMatcher.find()) {
                anzahlVereine++;
            }
            System.out.println("Anzahl /vereine/ Links im HTML: " + anzahlVereine);
            
            teams = parseTeamsAusTabelle(html, liga);
            System.out.println("Gefunden: " + teams.size() + " Teams");
            
            for (Team team : teams) {
                System.out.println("  " + team.liga + ": " + team.anzeigeName + " -> " + team.urlName);
            }
            
        } catch (Exception e) {
            System.err.println("Fehler beim Scrapen: " + e.getMessage());
        }
        
        return teams;
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
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            
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
     * Parst Teams aus der Tabelle
     */
    private static List<Team> parseTeamsAusTabelle(String html, String liga) {
        List<Team> teams = new ArrayList<>();
        
        // Pattern für Team-Links in der Tabelle (basierend auf echtem HTML)
        // Beispiel: <a href="/vereine/1-fsv-mainz-05/2026/"><span>...</span> Mainz</a>
        Pattern[] patterns = {
            // HTML-Link mit Span (aktuelles Format)
            Pattern.compile("<a[^>]*href=\"/vereine/([^/]+)/\\d+/\"[^>]*>.*?</span>\\s*([^<]+)</a>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL),
            // Standard HTML-Link (Fallback)
            Pattern.compile("<a[^>]*href=\"/vereine/([^/]+)/\\d+/\"[^>]*>([^<]+)</a>", Pattern.CASE_INSENSITIVE),
            // Vereinfachtes Pattern für href und nachfolgenden Text
            Pattern.compile("href=\"/vereine/([^/]+)/\\d+/\"[^>]*>.*?>\\s*([A-Za-zÄÖÜäöüß\\s'.-]+)", Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
        };
        
        Set<String> bereitsGefunden = new HashSet<>(); // Duplikate vermeiden
        
        for (Pattern teamPattern : patterns) {
            Matcher matcher = teamPattern.matcher(html);
            int matches = 0;
            
            while (matcher.find()) {
                matches++;
                String urlName, anzeigeName;
                
                if (teamPattern.pattern().contains("\\[")) {
                    // Markdown pattern: [Name](/vereine/url/)
                    anzeigeName = matcher.group(1).trim();
                    urlName = matcher.group(2);
                } else {
                    // HTML pattern: href="/vereine/url/">Name
                    urlName = matcher.group(1);
                    anzeigeName = matcher.group(2).trim();
                }
                
                // Bereinige Anzeigenamen
                anzeigeName = anzeigeName.replaceAll("&amp;", "&")
                                       .replaceAll("&lt;", "<")
                                       .replaceAll("&gt;", ">")
                                       .replaceAll("&quot;", "\"")
                                       .replaceAll("\\s+", " ");
                
                // Überspringe Duplikate
                if (bereitsGefunden.contains(urlName)) {
                    continue;
                }
                bereitsGefunden.add(urlName);
                
                // Erstelle Team-Objekt
                Team team = new Team(anzeigeName, urlName, liga);
                teams.add(team);
                
                System.out.println("DEBUG: Gefunden - " + anzeigeName + " -> " + urlName);
            }
            
            System.out.println("DEBUG: Pattern " + (java.util.Arrays.asList(patterns).indexOf(teamPattern) + 1) + " fand " + matches + " Matches");
        }
        
        return teams;
    }
    
    /**
     * Speichert Teams in Datei
     */
    private static void speichereTeams(int saison) {
        try {
            FileWriter writer = new FileWriter(OUTPUT_FILE, false);
            
            writer.write("# Automatisch generierte Mannschaftsliste\n");
            writer.write("# Saison: " + (saison-1) + "/" + saison + "\n");
            writer.write("# Generiert am: " + new Date() + "\n");
            writer.write("# Format: Liga | Anzeigename | URL-Name\n");
            writer.write("\n");
            
            // Gruppiere nach Liga
            List<Team> teams1BL = new ArrayList<>();
            List<Team> teams2BL = new ArrayList<>();
            
            for (Team team : allTeams) {
                if ("1BL".equals(team.liga)) {
                    teams1BL.add(team);
                } else {
                    teams2BL.add(team);
                }
            }
            
            // 1. Bundesliga
            writer.write("## 1. Bundesliga (" + teams1BL.size() + " Teams)\n");
            for (Team team : teams1BL) {
                writer.write("1BL | " + team.anzeigeName + " | " + team.urlName + "\n");
            }
            writer.write("\n");
            
            // 2. Bundesliga
            writer.write("## 2. Bundesliga (" + teams2BL.size() + " Teams)\n");
            for (Team team : teams2BL) {
                writer.write("2BL | " + team.anzeigeName + " | " + team.urlName + "\n");
            }
            
            writer.close();
            
        } catch (IOException e) {
            System.err.println("Fehler beim Speichern: " + e.getMessage());
        }
    }
    
    /**
     * Gibt die aktuellen Teams als Map zurück (für Integration in andere Tools)
     */
    public static Map<String, String> ladeAktuelleTeams() {
        Map<String, String> teams = new HashMap<>();
        
        try {
            BufferedReader reader = new BufferedReader(new FileReader(OUTPUT_FILE));
            String line;
            
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                
                // Überspringe Kommentare und leere Zeilen
                if (line.startsWith("#") || line.isEmpty()) {
                    continue;
                }
                
                // Parse Team-Zeile: Liga | Anzeigename | URL-Name
                String[] parts = line.split("\\|");
                if (parts.length >= 3) {
                    String anzeigeName = parts[1].trim();
                    String urlName = parts[2].trim();
                    teams.put(anzeigeName, urlName);
                }
            }
            reader.close();
            
        } catch (IOException e) {
            System.err.println("Fehler beim Laden der Teams: " + e.getMessage());
        }
        
        return teams;
    }
    
    /**
     * Team-Klasse
     */
    static class Team {
        String anzeigeName;
        String urlName;
        String liga;
        
        Team(String anzeigeName, String urlName, String liga) {
            this.anzeigeName = anzeigeName;
            this.urlName = urlName;
            this.liga = liga;
        }
    }
}
