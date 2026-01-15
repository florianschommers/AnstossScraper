import java.io.*;
import java.net.*;
import java.util.*;
import java.text.Normalizer;
import java.util.regex.*;

/**
 * AufstellungsAnalyzer - Analysiert Aufstellungen aller Teams
 * 
 * Schritt 1: Sammelt Spieler aus letzten 10 Spielen
 * Punkte-System: Start-11 = 1 Punkt, Einwechslung = 0.5 Punkte, nur Ersatzbank = 0 Punkte
 */
public class AufstellungsAnalyzer {
    
    private static final String SPIELPLAN_DATEI = "team_spielplaene_letzte10.txt";
    private static final String OUTPUT_DATEI = "mannschafts_aufstellungen_analyse.txt";
    
    // Logging für Fehleranalyse
    private static List<String> logEntries = new ArrayList<>();
    
    public static void main(String[] args) {
        System.out.println("=== AufstellungsAnalyzer - Schritt 1 ===");
        
        // Schritt 1: Lade Team-Daten mit Aufstellungslinks
        Map<String, List<String>> teamAufstellungsLinks = ladeTeamAufstellungsLinks();
        
        if (teamAufstellungsLinks.isEmpty()) {
            System.err.println("FEHLER: Keine Team-Daten gefunden in " + SPIELPLAN_DATEI);
            System.err.println("Bitte zuerst TeamSpielplanScraper ausführen!");
            return;
        }
        
        System.out.println("Gefunden: " + teamAufstellungsLinks.size() + " Teams");
        
        // VOLLSTÄNDIGE ANALYSE: Alle Teams (oder optional nur ein bestimmtes Team über ENV NUR_TEAM)
        List<String> alleTeams = new ArrayList<>(teamAufstellungsLinks.keySet());
        String nurTeam = System.getenv("NUR_TEAM");
        if (nurTeam != null && !nurTeam.trim().isEmpty()) {
            String ziel = nurTeam.trim();
            alleTeams.removeIf(t -> !t.equalsIgnoreCase(ziel));
            System.out.println("Gefiltert auf Team per ENV NUR_TEAM='" + ziel + "' -> " + alleTeams.size() + " Team(s)");
        }
        
        System.out.println("VOLLANALYSE: Analysiere alle " + alleTeams.size() + " Teams");
        
        List<String> ergebnisse = new ArrayList<>();
        
        for (String teamName : alleTeams) {
            System.out.println("\n--- Analysiere " + teamName + " ---");
            
            List<String> links = teamAufstellungsLinks.get(teamName);
            Map<String, Double> spielerPunkte = analysiereTeamAufstellungen(teamName, links);
            
            if (!spielerPunkte.isEmpty()) {
                String teamErgebnis = formatiereTeamErgebnis(teamName, spielerPunkte);
                ergebnisse.add(teamErgebnis);
            }
        }
        
        // Speichere Ergebnisse
        speichereErgebnisse(ergebnisse);
        speichereLog();
        
        System.out.println("\n=== FERTIG ===");
        System.out.println("Gespeichert in: " + OUTPUT_DATEI);
        System.out.println("Logs in: aufstellungs_analyzer_log.txt");
    }
    
    /**
     * Lädt Team-Namen und deren Aufstellungslinks aus der TeamSpielplanScraper-Datei
     */
    private static Map<String, List<String>> ladeTeamAufstellungsLinks() {
        Map<String, List<String>> teamLinks = new HashMap<>();
        
        try (BufferedReader reader = new BufferedReader(new FileReader(SPIELPLAN_DATEI))) {
            String line;
            String currentTeam = null;
            
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                
                // Team-Header erkennen (=== Team Name ===)
                if (line.startsWith("=== ") && line.endsWith(" ===")) {
                    currentTeam = line.substring(4, line.length() - 4);
                    teamLinks.put(currentTeam, new ArrayList<>());
                    continue;
                }
                
                // Aufstellungslinks extrahieren
                if (currentTeam != null && line.contains("aufstellung/")) {
                    Pattern linkPattern = Pattern.compile("\\[Link: (https://[^\\]]+)\\]");
                    Matcher matcher = linkPattern.matcher(line);
                    if (matcher.find()) {
                        String link = matcher.group(1);
                        teamLinks.get(currentTeam).add(link);
                    }
                }
            }
            
        } catch (IOException e) {
            log("FEHLER beim Lesen der Spielplan-Datei: " + e.getMessage());
        }
        
        return teamLinks;
    }
    
    /**
     * Analysiert Aufstellungen eines Teams
     */
    private static Map<String, Double> analysiereTeamAufstellungen(String teamName, List<String> aufstellungsLinks) {
        Map<String, Double> spielerPunkte = new HashMap<>();
        
        int spielZaehler = 0;
        for (String link : aufstellungsLinks) {
            spielZaehler++;
            log("Spiel " + spielZaehler + "/" + aufstellungsLinks.size() + " für " + teamName + ": " + link);
            
            try {
                String html = fetchHtml(link);
                if (html != null) {
                    analysiereEinzelAufstellung(html, spielerPunkte, teamName, spielZaehler, link);
                } else {
                    log("WARNUNG: Konnte HTML nicht laden für " + link);
                }
                
                // Pause zwischen Requests
                Thread.sleep(1000);
                
            } catch (Exception e) {
                log("FEHLER bei " + link + ": " + e.getMessage());
            }
        }
        
        return spielerPunkte;
    }
    
    /**
     * Analysiert eine einzelne Aufstellungsseite
     */
    private static void analysiereEinzelAufstellung(String html, Map<String, Double> spielerPunkte, String teamName, int spielNr, String aufstellungsUrl) {
        // Bestimme Heim/Gast zunächst aus HTML (vom Nutzer vorgegeben). Fallback: URL.
        Boolean istHeimteamHtml = bestimmeTeamPositionAusHtml(html, teamName);
        boolean istHeimteam = (istHeimteamHtml != null) ? istHeimteamHtml : bestimmeTeamPositionAusUrl(aufstellungsUrl, teamName);
        String cssClass = istHeimteam ? "heim-content" : "gast-content";

        log("Spiel " + spielNr + ": " + teamName + " spielt als " + (istHeimteam ? "Heimteam" : "Gastteam"));

        // Extrahiere nur den relevanten HTML-Bereich für das Team (heim-content/gast-content)
        String teamHtml = extrahiereTeamHtml(html, cssClass);
        if (teamHtml.isEmpty()) {
            log("WARNUNG: Kein Team-HTML gefunden für " + teamName + " (" + cssClass + ")");
            return;
        }

        // Nur Start-11 erfassen (Einwechslungen/Ersatzbank vorübergehend deaktiviert)
        int starters = analysiereStart11Robust(teamHtml, spielerPunkte, teamName, spielNr);

        // Absicherung: Es müssen immer 11 sein. Bei weniger: Debug-Infos und Fallbacks.
        if (starters < 11) {
            log("WARNUNG: Nur " + starters + " Start-11-Spieler erkannt für " + teamName + " in Spiel " + spielNr + ". Versuche Fallback-Methoden.");
            // Fallback 1: Schneide explizit bis zur Reservebank und parsere erneut
            String starterHtml = extrahiereStartElfBereich(teamHtml);
            if (!starterHtml.isEmpty()) {
                starters += analysiereStart11NurPersonLinks(starterHtml, spielerPunkte, teamName, spielNr, true /*nurFehlende*/);
            }

            // Fallback 2: Suche Anker in Nähe von circle-nr
            if (starters < 11) {
                starters += analysiereStart11UmCircleNr(teamHtml, spielerPunkte, teamName, spielNr);
            }

            // Fallback 3: Box-Aufstellung mit "Startelf"-Headline (class="text lineup")
            if (starters < 11) {
                starters += analysiereStart11BoxAufstellung(teamHtml, spielerPunkte, teamName, spielNr);
            }

            if (starters < 11) {
                log("FEHLER: Nach Fallbacks weiterhin nur " + starters + " Starter. Speichere Debug-HTML.");
                speichereDebugHtml(teamName, spielNr, cssClass, teamHtml);
            }
        }
    }
    
    /**
     * Bestimmt ob das Team Heim- oder Gastteam ist basierend auf der URL
     * 
     * URL-Format: /bundesliga/2025/34/mainz-leverkusen/
     * Erstes Team = Heimteam, Zweites Team = Gastteam
     */
    private static boolean bestimmeTeamPositionAusUrl(String url, String teamName) {
        try {
            // Extrahiere Team-Teil aus URL
            Pattern urlPattern = Pattern.compile(".*/([^/]*-[^/]*)/+$");
            Matcher matcher = urlPattern.matcher(url);
            
            if (matcher.find()) {
                String teamTeil = matcher.group(1);
                String[] teams = teamTeil.split("-");
                
                if (teams.length >= 2) {
                    String heimteam = teams[0];
                    String gastteam = teams[teams.length - 1]; // Letztes Team für den Fall von "hertha-bsc"
                    
                    // Vereinfache Team-Namen für Vergleich
                    String vereinfachterTeamName = vereinfacheTeamNameFuerVergleich(teamName);
                    
                    // Prüfe Heimteam
                    if (vereinfachterTeamName.contains(heimteam.toLowerCase()) || 
                        heimteam.toLowerCase().contains(vereinfachterTeamName)) {
                        return true;
                    }
                    
                    // Prüfe Gastteam 
                    if (vereinfachterTeamName.contains(gastteam.toLowerCase()) ||
                        gastteam.toLowerCase().contains(vereinfachterTeamName)) {
                        return false;
                    }
                    
                    log("WARNUNG: Team '" + teamName + "' nicht in URL '" + url + "' gefunden (Teams: " + heimteam + ", " + gastteam + ")");
                }
            }
        } catch (Exception e) {
            log("FEHLER bei Team-Positionsbestimmung: " + e.getMessage());
        }
        
        return true; // Fallback: Heimteam
    }

    // Neue Methode: Bestimme Heim/Gast aus HTML-Struktur
    private static Boolean bestimmeTeamPositionAusHtml(String vollHtml, String teamName) {
        try {
            String normalizedTarget = normalizeForCompare(teamName);

            // Heim-Header und nachfolgender Teamname
            Pattern heimHeader = Pattern.compile("<div[^>]*class=\"[^\"]*col-md-6[^\"]*heim[^\"]*\"[^>]*>([\\s\\S]*?)<div[^>]*class=\"[^\"]*heim-content", Pattern.CASE_INSENSITIVE);
            Matcher mHeim = heimHeader.matcher(vollHtml);
            if (mHeim.find()) {
                String heimBlock = mHeim.group(1);
                String heimText = stripTags(heimBlock);
                if (normalizeForCompare(heimText).contains(normalizedTarget)) {
                    return true;
                }
            }

            // Gast-Header und nachfolgender Teamname
            Pattern gastHeader = Pattern.compile("<div[^>]*class=\"[^\"]*col-md-6[^\"]*gast[^\"]*\"[^>]*>([\\s\\S]*?)<div[^>]*class=\"[^\"]*gast-content", Pattern.CASE_INSENSITIVE);
            Matcher mGast = gastHeader.matcher(vollHtml);
            if (mGast.find()) {
                String gastBlock = mGast.group(1);
                String gastText = stripTags(gastBlock);
                if (normalizeForCompare(gastText).contains(normalizedTarget)) {
                    return false;
                }
            }
        } catch (Exception e) {
            log("WARNUNG: Heim/Gast-Bestimmung aus HTML fehlgeschlagen: " + e.getMessage());
        }
        return null; // Unklar -> Fallback auf URL
    }
    
    /**
     * Vereinfacht Team-Namen für URL-Vergleich
     */
    private static String vereinfacheTeamNameFuerVergleich(String teamName) {
        if (teamName == null) return "";

        // Akzente entfernen (ø, ö, ü, ä, é, ...) und klein schreiben
        String normalized = Normalizer.normalize(teamName, Normalizer.Form.NFD)
                .replaceAll("\\p{M}+", "")
                .toLowerCase(Locale.ROOT)
                .replace("ß", "ss");

        // Häufige Präfixe/Suffixe und Vereinsbegriffe entfernen
        // Bewusst NICHT "bsc" entfernen, da die URL "herthabsc" nutzt
        normalized = normalized
                .replaceAll("\\b(1\\.)\\b", "")
                .replaceAll("\\b(fsv|sv|fc|vfl|tsg|sc|spvgg|borussia)\\b", "")
                .replaceAll("\\s+", ""); // Leerzeichen entfernen

        // Nur Buchstaben und Ziffern behalten
        normalized = normalized.replaceAll("[^a-z0-9]", "");

        // Spezialfälle für abweichende Slugs auf fussballdaten.de
        normalized = normalized
                .replace("monchengladbach", "mgladbach")
                .replace("st.", "st")
                .replace("stpauli", "stpauli");

        return normalized;
    }
    
    /**
     * Extrahiert nur den HTML-Bereich für das spezifische Team
     */
    private static String extrahiereTeamHtml(String html, String cssClass) {
        // Schneide zwischen den Containern heim-content bzw. gast-content und dem jeweils anderen
        String thisClass = cssClass;
        String otherClass = "heim-content".equals(cssClass) ? "gast-content" : "heim-content";

        Pattern startPattern = Pattern.compile("<div[^>]*class=\"[^\"]*" + Pattern.quote(thisClass) + "[^\"]*\"[^>]*>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
        Matcher startMatcher = startPattern.matcher(html);
        if (!startMatcher.find()) {
            return "";
        }
        int contentStart = startMatcher.end();

        Pattern endPattern = Pattern.compile("<div[^>]*class=\"[^\"]*" + Pattern.quote(otherClass) + "[^\"]*\"[^>]*>", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
        Matcher endMatcher = endPattern.matcher(html);
        int contentEnd = html.length();
        if (endMatcher.find(contentStart)) {
            contentEnd = endMatcher.start();
        }

        if (contentStart >= 0 && contentStart < contentEnd && contentEnd <= html.length()) {
            return html.substring(contentStart, contentEnd);
        }
        return "";
    }
    
    /**
     * Analysiert Start-11 Spieler (1 Punkt)
     */
    private static int analysiereStart11Robust(String teamHtml, Map<String, Double> spielerPunkte, String teamName, int spielNr) {
        String starterHtml = extrahiereStartElfBereich(teamHtml);
        if (starterHtml.isEmpty()) starterHtml = teamHtml; // Fallback

        // Primär: Nur die ersten 11 eindeutigen /person/-Anker vor der Reservebank
        int added = analysiereStart11NurPersonLinks(starterHtml, spielerPunkte, teamName, spielNr, false);
        log("Spiel " + spielNr + " Start-11 (primär): " + added + " Spieler gefunden");
        return added;
    }

    private static String extrahiereStartElfBereich(String teamHtml) {
        String[] splitter = {"Reservebank", "Ersatzbank", "Bank"};
        int cut = -1;
        for (String s : splitter) {
            int idx = teamHtml.indexOf(s);
            if (idx >= 0) { cut = (cut == -1) ? idx : Math.min(cut, idx); }
        }
        if (cut > 0) return teamHtml.substring(0, cut);
        return teamHtml; // Kein Marker gefunden
    }

    private static int analysiereStart11NurPersonLinks(String htmlSegment, Map<String, Double> spielerPunkte, String teamName, int spielNr, boolean nurFehlende) {
        // Nur Anker mit class="name" berücksichtigen, um Bank/Logos zu vermeiden
        Pattern aPattern = Pattern.compile("<a[^>]*class=\\\"[^\\\"]*name[^\\\"]*\\\"[^>]*href=\\\"/person/([^/]+)/\\\"[^>]*>([\\s\\S]*?)</a>", Pattern.CASE_INSENSITIVE);
        Matcher m = aPattern.matcher(htmlSegment);
        LinkedHashMap<String, String> slugToName = new LinkedHashMap<>();
        while (m.find() && slugToName.size() < 11) {
            String slug = m.group(1).trim();
            String inner = m.group(2);
            String titleName = null;
            Matcher t = Pattern.compile("title=\\\"([^\\\"]+)\\\"").matcher(inner);
            if (t.find()) titleName = t.group(1);
            String textName = stripTags(inner).trim();
            String bestName = (titleName != null && !titleName.isEmpty()) ? titleName : textName;
            bestName = vereinfacheSpielerName(bestName);
            if (!bestName.isEmpty() && !istTrainer(bestName)) {
                slugToName.putIfAbsent(slug, bestName);
            }
        }
        int count = 0;
        for (String name : slugToName.values()) {
            if (nurFehlende && spielerPunkte.containsKey(name)) continue;
            spielerPunkte.put(name, spielerPunkte.getOrDefault(name, 0.0) + 1.0);
            count++;
            log("Start-11 (" + spielNr + "): " + name + " (+1.0) -> " + spielerPunkte.get(name));
            if (count >= 11) break;
        }
        return count;
    }

    private static int analysiereStart11UmCircleNr(String teamHtml, Map<String, Double> spielerPunkte, String teamName, int spielNr) {
        // Suche Blöcke mit circle-nr und finde den nächsten /person/-Anker danach
        Pattern p = Pattern.compile("<span[^>]*class=\\\"[^\\\"]*circle-nr[^\\\"]*\\\"[^>]*>\\d+<[/]span>([\\s\\S]{0,600}?)<a[^>]*class=\\\"[^\\\"]*name[^\\\"]*\\\"[^>]*href=\\\"/person/([^/]+)/\\\"[^>]*>([\\s\\S]*?)</a>", Pattern.CASE_INSENSITIVE);
        Matcher m = p.matcher(teamHtml);
        int added = 0;
        while (m.find() && added < 11) {
            String inner = m.group(3);
            String titleName = null;
            Matcher t = Pattern.compile("title=\\\"([^\\\"]+)\\\"").matcher(inner);
            if (t.find()) titleName = t.group(1);
            String textName = stripTags(inner).trim();
            String bestName = (titleName != null && !titleName.isEmpty()) ? titleName : textName;
            bestName = vereinfacheSpielerName(bestName);
            if (!bestName.isEmpty() && !spielerPunkte.containsKey(bestName) && !istTrainer(bestName)) {
                spielerPunkte.put(bestName, spielerPunkte.getOrDefault(bestName, 0.0) + 1.0);
                added++;
                log("Start-11 Fallback circle-nr (" + spielNr + "): " + bestName + " (+1.0)");
            }
        }
        return added;
    }

    private static int analysiereStart11BoxAufstellung(String teamHtml, Map<String, Double> spielerPunkte, String teamName, int spielNr) {
        // Suche einen Block mit der Sub-Headline "Startelf" innerhalb einer box-aufstellung
        Pattern block = Pattern.compile("<div[^>]*class=\\\"[^\\\"]*box-aufstellung[^\\\"]*\\\"[^>]*>([\\s\\S]*?)</div>", Pattern.CASE_INSENSITIVE);
        Matcher bm = block.matcher(teamHtml);
        int added = 0;
        while (bm.find()) {
            String segment = bm.group(1);
            if (!segment.toLowerCase(Locale.ROOT).contains("startelf")) continue;

            // Finde Links class="text lineup" href="/person/.../"
            Pattern link = Pattern.compile("<a[^>]*class=\\\"[^\\\"]*text\\s+lineup[^\\\"]*\\\"[^>]*href=\\\"/person/([^/]+)/\\\"[^>]*>([^<]+)</a>", Pattern.CASE_INSENSITIVE);
            Matcher lm = link.matcher(segment);
            while (lm.find()) {
                String slug = lm.group(1).trim();
                String name = vereinfacheSpielerName(lm.group(2).trim());
                if (name.isEmpty() || istTrainer(name)) continue;
                if (!spielerPunkte.containsKey(name)) {
                    spielerPunkte.put(name, spielerPunkte.getOrDefault(name, 0.0) + 1.0);
                    added++;
                    log("Start-11 Fallback box-aufstellung (" + spielNr + "): " + name + " (+1.0)");
                    if (added >= 11) break;
                }
            }
            if (added >= 11) break;
        }
        return added;
    }
    
    /**
     * Analysiert Einwechslungen (0.5 Punkte) - VERBESSERT: Verwendet vollständiges HTML
     * 
     * Strategie: Suche alle Einwechslungen und filtere nach Team-Position (Heim/Gast)
     */
    private static void analysiereEinwechslungen(String vollHtml, Map<String, Double> spielerPunkte, String teamName, int spielNr, boolean istHeimteam) {
        // Strategie: Finde alle Einwechslungen und bestimme welche zu unserem Team gehören
        // KORRIGIERT: Spieler-Link kommt ZUERST, dann fa-exchange
        Pattern einwechslungPattern = Pattern.compile("<a class=\"text\\s+lineup\"[^>]*>([^<]+)</a>.*?<span class=\"fa fa-exchange\"[^>]*title=\"([^\"]*f[^\"]*r[^\"]*)\"");
        Matcher matcher = einwechslungPattern.matcher(vollHtml);
        
        int einwechslungCount = 0;
        while (matcher.find()) {
            String spielerName = matcher.group(1); // Spieler-Name  
            String wechselInfo = matcher.group(2); // "71' für Anthony Caci"
            
            spielerName = spielerName.trim();
            spielerName = vereinfacheSpielerName(spielerName);
            
            // Filtere Trainer heraus
            if (istTrainer(spielerName)) {
                continue;
            }
            
            // TEAM-SPEZIFISCHE FILTERUNG: 
            // Da wir das vollständige HTML verwenden, müssen wir prüfen, ob der Einwechslung
            // zum aktuellen Team gehört. Das machen wir durch Position im HTML.
            
            // Finde die Position der Einwechslung im HTML
            int wechselPosition = matcher.start();
            
            // Bestimme ob diese Einwechslung zum Heim- oder Gastteam gehört
            // Vereinfachung: Erste Hälfte des HTML = Heimteam, Zweite Hälfte = Gastteam
            boolean gehoertZuHeimteam = wechselPosition < (vollHtml.length() / 2);
            
            if (gehoertZuHeimteam == istHeimteam) {
                spielerPunkte.put(spielerName, spielerPunkte.getOrDefault(spielerName, 0.0) + 0.5);
                einwechslungCount++;
                
                log("Einwechslung (" + spielNr + "): " + spielerName + " (+0.5) -> " + spielerPunkte.get(spielerName) + " [" + wechselInfo + "]");
            }
        }
        
        log("Spiel " + spielNr + " Einwechslungen: " + einwechslungCount + " Spieler gefunden");
    }
    
    /**
     * Analysiert nur Ersatzbank (0 Punkte)
     */
    private static void analysiereErsatzbank(String teamHtml, Map<String, Double> spielerPunkte, String teamName, int spielNr) {
        // Suche alle Ersatzbank-Spieler (class="text lineup")
        Pattern ersatzbankPattern = Pattern.compile("<a class=\"text\\s+lineup\"[^>]*href=\"/person/[^/]+/\"[^>]*>([^<]+)</a>");
        Matcher matcher = ersatzbankPattern.matcher(teamHtml);
        
        int ersatzbankCount = 0;
        while (matcher.find()) {
            String spielerName = matcher.group(1).trim();
            spielerName = vereinfacheSpielerName(spielerName);
            
            // Filtere Trainer heraus
            if (istTrainer(spielerName)) {
                continue;
            }
            
            // Nur hinzufügen wenn noch nicht vorhanden (0 Punkte)
            if (!spielerPunkte.containsKey(spielerName)) {
                spielerPunkte.put(spielerName, 0.0);
                ersatzbankCount++;
                
                log("Nur Ersatzbank (" + spielNr + "): " + spielerName + " (+0.0)");
            }
        }
        
        log("Spiel " + spielNr + " nur Ersatzbank: " + ersatzbankCount + " neue Spieler gefunden");
    }
    
    /**
     * Prüft ob der Name ein Trainer ist
     */
    private static boolean istTrainer(String name) {
        if (name == null) return false;
        String lowerName = name.toLowerCase(Locale.ROOT);
        // Nur explizit markierte Trainer-Bezeichner filtern, keine Heuristiken nach Vornamen
        if (lowerName.contains("trainer") || lowerName.contains("head coach") || lowerName.contains("coach")) {
            return true;
        }
        return false;
    }
    
    /**
     * Vereinfacht Spielernamen für bessere Zuordnung
     */
    private static String vereinfacheSpielerName(String name) {
        if (name == null) return "";
        // Entferne HTML-Entities
        String cleaned = name.replace("&amp;", "&").replace("&quot;", "\"");
        // Diakritika entfernen (z.B. Rønnow -> Ronnow, Müller -> Muller)
        String deaccent = Normalizer.normalize(cleaned, Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
        deaccent = deaccent.replace("ß", "ss");
        // Whitespace normalisieren
        deaccent = deaccent.replaceAll("\\s+", " ").trim();
        return deaccent;
    }

    private static String normalizeForCompare(String s) {
        if (s == null) return "";
        String x = Normalizer.normalize(s, Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
        x = x.replace("ß", "ss").toLowerCase(Locale.ROOT);
        x = x.replaceAll("[^a-z0-9]", "");
        return x;
    }

    private static String stripTags(String html) {
        return html.replaceAll("<[^>]+>", " ").replaceAll("\\s+", " ").trim();
    }

    private static void speichereDebugHtml(String teamName, int spielNr, String cssClass, String teamHtml) {
        String safeTeam = normalizeForCompare(teamName);
        File f = new File("debug_startelf_" + safeTeam + "_" + spielNr + "_" + cssClass + ".html");
        try (FileWriter w = new FileWriter(f, false)) {
            w.write(teamHtml);
        } catch (IOException e) {
            log("Konnte Debug-HTML nicht speichern: " + e.getMessage());
        }
    }
    
    /**
     * Formatiert die Ergebnisse für ein Team
     */
    private static String formatiereTeamErgebnis(String teamName, Map<String, Double> spielerPunkte) {
        StringBuilder sb = new StringBuilder();
        sb.append("=== ").append(teamName).append(" ===\n");
        
        // Sortiere nach Punkten (absteigend)
        List<Map.Entry<String, Double>> sortierteSpieler = new ArrayList<>(spielerPunkte.entrySet());
        sortierteSpieler.sort(Map.Entry.<String, Double>comparingByValue().reversed());
        
        int position = 1;
        for (Map.Entry<String, Double> entry : sortierteSpieler) {
            String spieler = entry.getKey();
            double punkte = entry.getValue();
            
            // Formatiere Punkte-Info
            String punkteInfo = formatierePunkteInfo(punkte);
            
            sb.append(String.format("%2d. %s: %.1f Punkte %s\n", 
                position, spieler, punkte, punkteInfo));
            position++;
        }
        sb.append("\n");
        
        return sb.toString();
    }
    
    /**
     * Formatiert Punkte-Informationen
     */
    private static String formatierePunkteInfo(double punkte) {
        int startElf = (int) punkte;
        int einwechslungen = (int) ((punkte - startElf) * 2);
        
        StringBuilder info = new StringBuilder("(");
        
        if (startElf > 0) {
            info.append(startElf).append("x Start-11");
        }
        
        if (einwechslungen > 0) {
            if (startElf > 0) info.append(", ");
            info.append(einwechslungen).append("x Einwechslung");
        }
        
        if (punkte == 0.0) {
            info.append("nur Ersatzbank");
        }
        
        info.append(")");
        return info.toString();
    }
    
    /**
     * Lädt HTML von URL
     */
    private static String fetchHtml(String urlString) {
        try {
            URL url = new URL(urlString);
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36");
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(15000);
            
            int responseCode = connection.getResponseCode();
            if (responseCode != 200) {
                log("HTTP Error: " + responseCode + " für " + urlString);
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
            log("Netzwerk-Fehler für " + urlString + ": " + e.getMessage());
            return null;
        }
    }
    
    /**
     * Speichert die Ergebnisse
     */
    private static void speichereErgebnisse(List<String> ergebnisse) {
        try (FileWriter writer = new FileWriter(OUTPUT_DATEI, false)) {
            writer.write("=== AUFSTELLUNGSANALYSE - ALLE MANNSCHAFTEN ===\n");
            writer.write("Datum: " + new Date() + "\n");
            writer.write("Basis: Letzte 10 Spiele pro Mannschaft\n");
            writer.write("Punkte-System: Start-11 = 1 Punkt, Einwechslung = 0.5 Punkte, nur Ersatzbank = 0 Punkte\n\n");
            
            for (String ergebnis : ergebnisse) {
                writer.write(ergebnis);
            }
            
            System.out.println("✓ Ergebnisse gespeichert: " + ergebnisse.size() + " Teams");
            
        } catch (IOException e) {
            log("FEHLER beim Speichern der Ergebnisse: " + e.getMessage());
        }
    }
    
    /**
     * Logging-Funktion
     */
    private static void log(String message) {
        String logMessage = "[" + new Date() + "] " + message;
        System.out.println(logMessage);
        logEntries.add(logMessage);
    }
    
    /**
     * Speichert das Log
     */
    private static void speichereLog() {
        try (FileWriter writer = new FileWriter("aufstellungs_analyzer_log.txt", false)) {
            for (String logEntry : logEntries) {
                writer.write(logEntry + "\n");
            }
        } catch (IOException e) {
            System.err.println("Fehler beim Speichern des Logs: " + e.getMessage());
        }
    }
}
