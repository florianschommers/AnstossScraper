import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.*;
import java.util.regex.*;

public class KaderScraper {

	private static final String BL1_CLUBS = "https://www.bundesliga.com/de/bundesliga/clubs";
	private static final String BL2_CLUBS = "https://www.bundesliga.com/de/2bundesliga/clubs";
	private static final String OUTPUT = "aktuelle_kader_bundesliga.txt";

	private static final int MAX_RETRIES = 3;
	private static final int RETRY_DELAY_MS = 1500;

	public static void main(String[] args) {
		System.out.println("=== KaderScraper (bundesliga.com) ===");
		try {
			long runStart = System.currentTimeMillis();
			// Schritt 0: Automatisch Teams und Spielpläne aktualisieren
			try {
				System.out.println("Starte AktuelleTeamsScraper (aktuelle_teams_automatisch.txt)...");
				AktuelleTeamsScraper.main(new String[0]);
				warteAufDatei("aktuelle_teams_automatisch.txt", 200, 60000, runStart);
			} catch (Throwable t) {
				System.out.println("Hinweis: AktuelleTeamsScraper konnte nicht automatisch gestartet werden: " + t.getMessage());
			}
			try {
				System.out.println("Starte TeamSpielplanScraper (team_spielplaene_letzte10.txt)...");
				TeamSpielplanScraper.main(new String[0]);
				warteAufDatei("team_spielplaene_letzte10.txt", 1000, 120000, runStart);
			} catch (Throwable t) {
				System.out.println("Hinweis: TeamSpielplanScraper konnte nicht automatisch gestartet werden: " + t.getMessage());
			}

			Map<String, String> teamLinks = new LinkedHashMap<>();
			System.out.println("Sammle Team-Links 1. Bundesliga...");
			teamLinks.putAll(sammleTeamLinks(BL1_CLUBS, "1. Bundesliga"));
			System.out.println("Sammle Team-Links 2. Bundesliga...");
			teamLinks.putAll(sammleTeamLinks(BL2_CLUBS, "2. Bundesliga"));
			System.out.println("Insgesamt Links: " + teamLinks.size());

			Map<String, Map<String, List<String>>> alleKader = new LinkedHashMap<>();
			int idx = 0;
			for (Map.Entry<String, String> e : teamLinks.entrySet()) {
				idx++;
				String team = e.getKey();
				String url = e.getValue();
				System.out.println("(" + idx + "/" + teamLinks.size() + ") Kader: " + team + " -> " + url);

				Map<String, List<String>> kader = scrapeTeamKader(team, url);
				alleKader.put(team, kader);
				try { Thread.sleep(200); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
			}
			schreibeAusgabe(alleKader);
			System.out.println("Fertig. Datei: " + OUTPUT);

			// NEU: AufstellungsAnalyzer ausführen und Empfehlungen generieren
			try {
				System.out.println("Starte AufstellungsAnalyzer für aktuelle Daten...");
				AufstellungsAnalyzer.main(new String[0]);
				warteAufDatei("mannschafts_aufstellungen_analyse.txt", 1000, 180000, runStart);
			} catch (Throwable t) {
				System.out.println("Hinweis: AufstellungsAnalyzer konnte nicht automatisch gestartet werden: " + t.getMessage());
			}

			try {
				Map<String, Map<String, Double>> analysePunkte = ladeAnalysePunkte("mannschafts_aufstellungen_analyse.txt");
				schreibeEmpfohleneKernspieler(alleKader, analysePunkte, "empfohlene_spieler_pro_team.txt");
				warteAufDatei("empfohlene_spieler_pro_team.txt", 100, 30000, runStart);
				System.out.println("Empfehlungen gespeichert in: empfohlene_spieler_pro_team.txt");

				// Nachbearbeitung: Fitness/Sperren prüfen direkt in Java
				try {
					FitnessChecker.markPlayersInTxt("empfohlene_spieler_pro_team.txt");
					warteAufDatei("empfohlene_spieler_pro_team.txt", 100, 30000, runStart);
					// NEU: Abgleich mit aktuellem Kader – Spieler, die nicht mehr im Verein sind, markieren
					FitnessChecker.markNotInSquad("empfohlene_spieler_pro_team.txt", "aktuelle_kader_bundesliga.txt");
					warteAufDatei("empfohlene_spieler_pro_team.txt", 100, 30000, runStart);
				} catch (Throwable t) {
					System.out.println("Hinweis: FitnessChecker konnte nicht ausgeführt werden: " + t.getMessage());
				}
			} catch (Exception ex) {
				System.out.println("Hinweis: Konnte Empfehlungen nicht erzeugen: " + ex.getMessage());
			}
		} catch (Exception ex) {
			System.err.println("FEHLER: " + ex.getMessage());
			ex.printStackTrace();
		}
	}

	private static Map<String, String> sammleTeamLinks(String clubsUrl, String ligaName) {
		Map<String, String> result = new LinkedHashMap<>();
		String html = fetchHtmlMitRetry(clubsUrl);
		if (html.isEmpty()) {
			System.out.println("WARNUNG: Clubs-Seite leer: " + clubsUrl);
			return result;
		}
		// Debug: entfernt

		Set<String> links = new LinkedHashSet<>();
		// 1) Standard: /de/(bundesliga|2bundesliga)/clubs/<slug>
		Pattern p1 = Pattern.compile("href=\"(/de/(?:bundesliga|2bundesliga)/clubs/[^\"]+)\"", Pattern.CASE_INSENSITIVE);
		Matcher m1 = p1.matcher(html);
		while (m1.find()) {
			links.add("https://www.bundesliga.com" + trimTrailingSpaces(m1.group(1)));
		}
		// 2) Ohne /de
		Pattern p2 = Pattern.compile("href=\"(/(?:bundesliga|2bundesliga)/clubs/[^\"]+)\"", Pattern.CASE_INSENSITIVE);
		Matcher m2 = p2.matcher(html);
		while (m2.find()) {
			links.add("https://www.bundesliga.com" + trimTrailingSpaces(m2.group(1)));
		}
		// 3) Absolut
		Pattern p3 = Pattern.compile("href=\"(https://www\\.bundesliga\\.com/(?:de/)?(?:bundesliga|2bundesliga)/clubs/[^\"]+)\"", Pattern.CASE_INSENSITIVE);
		Matcher m3 = p3.matcher(html);
		while (m3.find()) {
			links.add(trimTrailingSpaces(m3.group(1)));
		}

		// Debug: entfernt
		for (String link : links) {
			String teamName = rateTeamNameAusUrl(link);
			if (!teamName.isEmpty() && !result.containsKey(teamName)) {
				result.put(teamName, normalisiereUrl(link));
			}
		}
		System.out.println(ligaName + ": Teams erkannt: " + result.size());
		return result;
	}

	private static String normalisiereUrl(String url) {
		String u = url.trim();
		// Entferne trailing spaces und #fragmente
		u = u.replaceAll("\\s+$", "");
		// Falls kein Slash am Ende, füge optional für Fallback hinzu (wird erst bei Bedarf genutzt)
		return u;
	}

	private static String trimTrailingSpaces(String s) {
		return s == null ? "" : s.replaceAll("\\s+$", "");
	}

	private static String rateTeamNameAusUrl(String url) {
		Matcher m = Pattern.compile("/clubs/([^/?#]+)").matcher(url);
		if (m.find()) {
			String slug = m.group(1);
			slug = slug.replace('-', ' ');
			slug = slug.replace("1 ", "1. ");
			slug = capitalizeWords(slug);
			// Häufige Umlaute in Slugs
			slug = slug.replace("monchengladbach", "Mönchengladbach")
					.replace("koln", "Köln")
					.replace("dusseldorf", "Düsseldorf")
					.replace("munchen", "München");
			return slug;
		}
		return "";
	}

	private static String capitalizeWords(String s) {
		String[] parts = s.split(" ");
		StringBuilder b = new StringBuilder();
		for (String p : parts) {
			if (p.isEmpty()) continue;
			b.append(Character.toUpperCase(p.charAt(0))).append(p.length() > 1 ? p.substring(1) : "").append(' ');
		}
		return b.toString().trim();
	}

	private static Map<String, List<String>> scrapeTeamKader(String teamName, String teamUrl) {
		Map<String, List<String>> kader = new LinkedHashMap<>();
		kader.put("Torwart", new ArrayList<>());
		kader.put("Abwehr", new ArrayList<>());
		kader.put("Mittelfeld", new ArrayList<>());
		kader.put("Angriff", new ArrayList<>());

		// 1) Team-Seite holen (mit Fallback-Varianten)
		String htmlTeam = fetchTeamSeiteMitFallbacks(teamUrl);
		if (htmlTeam.isEmpty()) {
			System.out.println("WARNUNG: Keine Team-Seite ladbar: " + teamUrl);
			return kader;
		}
		// Debug-Datei entfernt

		// 2) Kader/Team-Unterseite ermitteln (falls Navigation vorhanden)
		String kaderUrl = findeKaderUnterseite(htmlTeam, teamUrl);
		String htmlKader = htmlTeam;
		if (!kaderUrl.isEmpty() && !kaderUrl.equals(teamUrl)) {
			htmlKader = fetchHtmlMitRetry(kaderUrl);
			if (htmlKader.isEmpty()) {
				System.out.println("WARNUNG: Kader-Unterseite leer: " + kaderUrl);
			}
		}

		// 3) Spieler aus HTML extrahieren
		parseSpielerAusHtml(htmlKader, kader);

		// 4) Wenn sehr wenige Spieler gefunden wurden -> Debug behalten
		int gesamt = kader.values().stream().mapToInt(List::size).sum();
		if (gesamt < 8) {
			// Debug-Hinweis entfernt
		}
		return kader;
	}

	private static String findeKaderUnterseite(String htmlTeam, String teamUrl) {
		// Suche nach Navigationslink, der Kader/Mannschaft/Team anzeigt
		// Beispiele, die wir versuchen: "Kader", "Team", "Mannschaft"
		Pattern nav = Pattern.compile("<a[^>]*href=\"([^\"]+)\"[^>]*>(?:\\s*<[^>]+>\\s*)*(Kader|Mannschaft|Team)(?:\\s*<|\\s*</a>)",
				Pattern.CASE_INSENSITIVE);
		Matcher m = nav.matcher(htmlTeam);
		while (m.find()) {
			String href = m.group(1);
			String abs = absolut(teamUrl, href);
			if (abs.contains("/clubs/") || abs.contains("/teams/") || abs.contains("/kader") || abs.contains("/team")) {
				return abs;
			}
		}
		return "";
	}

	private static void parseSpielerAusHtml(String html, Map<String, List<String>> kader) {
		if (html == null || html.isEmpty()) return;

		// Versuch 0: Eingebettete Bundesliga-API-JSON im HTML (players nach Rollen)
		parseBundesligaApiPlayersJson(html, kader);
		if (gesamtSpieler(kader) >= 8) return;

		// Versuch 1: Position-Container mit Überschriften (Torwart/Abwehr/Mittelfeld/Angriff)
		parseByPositionSections(html, kader);

		// Versuch 2: Generische Spieler-Card mit Positionstext in Nähe
		if (gesamtSpieler(kader) < 8) {
			parseGenericCards(html, kader);
		}
	}

	private static void parseBundesligaApiPlayersJson(String html, Map<String, List<String>> kader) {
		// In Debug-HTMLs sind API-Responses wie wapp.bapi.bundesliga.com/... mit "players":{"DEFENSE":[...],"ATTACK":...}
		String[] rollen = new String[]{"GOALKEEPER","DEFENSE","MIDFIELD","ATTACK"};
		for (String rolle : rollen) {
			Pattern block = Pattern.compile("\\\"" + rolle + "\\\"\\s*:\\s*\\[(.*?)\\]", Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
			Matcher bm = block.matcher(html);
			if (!bm.find()) continue;
			String array = bm.group(1);
			Pattern nameP = Pattern.compile("\\\"full\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"", Pattern.CASE_INSENSITIVE);
			Matcher nm = nameP.matcher(array);
			String kat = rolleToKategorie(rolle);
			List<String> liste = kader.get(kat);
			while (nm.find()) {
				String name = cleanName(nm.group(1));
				addIfMissing(liste, name);
			}
		}
	}

	private static String rolleToKategorie(String rolle) {
		String r = rolle.toUpperCase(Locale.ROOT);
		if (r.contains("GOAL")) return "Torwart";
		if (r.contains("DEF")) return "Abwehr";
		if (r.contains("MID")) return "Mittelfeld";
		return "Angriff";
	}

	private static void parseByPositionSections(String html, Map<String, List<String>> kader) {
		String[] sektionen = {"Torwart", "Torhüter", "Goalkeeper", "Abwehr", "Verteidigung", "Defense",
				"Mittelfeld", "Midfield", "Angriff", "Sturm", "Attack"};
		for (String sek : sektionen) {
			Pattern block = Pattern.compile("(" + Pattern.quote(sek) + ")([\\s\\S]{0,4000}?)</section>|(" + Pattern.quote(sek) + ")([\\s\\S]{0,4000}?)</div>", Pattern.CASE_INSENSITIVE);
			Matcher bm = block.matcher(html);
			while (bm.find()) {
				String chunk = bm.group(2) != null ? bm.group(2) : bm.group(4);
				String kat = mappeSektionZuKategorie(sek);
				// Spieler-Namen innerhalb dieses Blocks
				Pattern nameA = Pattern.compile("<a[^>]*class=\\\"[^\\\"]*(?:name|player|spieler)[^\\\"]*\\\"[^>]*>([^<]{2,})</a>", Pattern.CASE_INSENSITIVE);
				Matcher na = nameA.matcher(chunk);
				while (na.find()) {
					String name = cleanName(na.group(1));
					if (!name.isEmpty()) addIfMissing(kader.get(kat), name);
				}
				// Alternative: span class="name"
				Pattern nameSpan = Pattern.compile("<span[^>]*class=\\\"[^\\\"]*name[^\\\"]*\\\"[^>]*title=\\\"([^\\\"]+)\\\"[^>]*>", Pattern.CASE_INSENSITIVE);
				Matcher ns = nameSpan.matcher(chunk);
				while (ns.find()) {
					String name = cleanName(ns.group(1));
					if (!name.isEmpty()) addIfMissing(kader.get(kat), name);
				}
			}
		}
	}

	private static void parseGenericCards(String html, Map<String, List<String>> kader) {
		// Suche Karten mit Spielername + Positionstitle im title-Attribut
		Pattern card = Pattern.compile("<a[^>]*href=\\\"/de/(?:bundesliga|2bundesliga)/spieler/[^\\\"]+\\\"[^>]*title=\\\"([^\\\"]+)\\\"[^>]*>", Pattern.CASE_INSENSITIVE);
		Matcher m = card.matcher(html);
		while (m.find()) {
			String title = m.group(1);
			// Erwartet: "Name – Position" oder "Position: Name"
			String name = title;
			String pos = "";
			if (title.contains("–")) {
				String[] parts = title.split("–", 2);
				name = parts.length > 1 ? parts[0].trim() : title.trim();
				pos = parts.length > 1 ? parts[1].trim() : "";
			} else if (title.contains(":")) {
				String[] parts = title.split(":", 2);
				pos = parts[0].trim();
				name = parts.length > 1 ? parts[1].trim() : title.trim();
			}
			name = cleanName(name);
			String kat = mappePositionZuKategorie(pos);
			addIfMissing(kader.get(kat), name);
		}
	}

	private static String mappeSektionZuKategorie(String sek) {
		String s = sek.toLowerCase(Locale.ROOT);
		if (s.contains("tor")) return "Torwart";
		if (s.contains("abwehr") || s.contains("verteid")) return "Abwehr";
		if (s.contains("angriff") || s.contains("sturm") || s.contains("attack")) return "Angriff";
		return "Mittelfeld";
	}

	private static String mappePositionZuKategorie(String position) {
		if (position == null) return "Mittelfeld";
		String p = position.toLowerCase(Locale.ROOT);
		if (p.contains("tor")) return "Torwart";
		if (p.contains("abwehr") || p.contains("verteid") || p.contains("def")) return "Abwehr";
		if (p.contains("sturm") || p.contains("angriff") || p.contains("st") || p.contains("fw")) return "Angriff";
		return "Mittelfeld";
	}

	private static void addIfMissing(List<String> liste, String name) {
		if (name == null || name.isEmpty()) return;
		if (!liste.contains(name)) liste.add(name);
	}

	private static String cleanName(String s) {
		if (s == null) return "";
		String n = s.replaceAll("<[^>]+>", "").replace("&nbsp;", " ").replaceAll("\\s+", " ").trim();
		// Diakritik-normalisierung optional vermeiden – Originalschreibweise behalten
		return n;
	}

	private static int gesamtSpieler(Map<String, List<String>> kader) {
		int c = 0;
		for (List<String> l : kader.values()) c += l.size();
		return c;
	}

	private static void schreibeAusgabe(Map<String, Map<String, List<String>>> alleKader) {
		try (PrintWriter out = new PrintWriter(new OutputStreamWriter(new FileOutputStream(OUTPUT), StandardCharsets.UTF_8))) {
			out.println("=== AKTUELLE KADER (bundesliga.com) ===");
			out.println("Generiert am: " + new Date());
			out.println();
			for (Map.Entry<String, Map<String, List<String>>> e : alleKader.entrySet()) {
				out.println("=== " + e.getKey() + " ===");
				for (String kat : Arrays.asList("Torwart", "Abwehr", "Mittelfeld", "Angriff")) {
					out.println(kat + ":");
					List<String> spieler = e.getValue().getOrDefault(kat, Collections.emptyList());
					if (spieler.isEmpty()) {
						out.println("  (keine Spieler gefunden)");
					} else {
						for (String name : spieler) out.println("  - " + name);
					}
					out.println();
				}
				int total = e.getValue().values().stream().mapToInt(List::size).sum();
				out.println("Gesamt: " + total + " Spieler");
				out.println();
			}
		} catch (IOException ioe) {
			System.err.println("Schreibfehler: " + ioe.getMessage());
		}
	}

	private static String fetchTeamSeiteMitFallbacks(String baseUrl) {
		List<String> kandidaten = new ArrayList<>();
		kandidaten.add(baseUrl);
		if (!baseUrl.endsWith("/")) kandidaten.add(baseUrl + "/");
		// Variante ohne "/de"
		kandidaten.add(baseUrl.replace("https://www.bundesliga.com/de/", "https://www.bundesliga.com/"));
		if (!baseUrl.endsWith("/")) {
			kandidaten.add(baseUrl.replace("https://www.bundesliga.com/de/", "https://www.bundesliga.com/") + "/");
		}

		for (String u : kandidaten) {
			String html = fetchHtmlMitRetry(u);
			if (!html.isEmpty()) return html;
		}
		return "";
	}

	// === NEU: Analyse-Datei einlesen und Empfehlungen erzeugen ===

	// Warte-Helfer: wartet bis Datei existiert, Mindestgröße erreicht und neuer als Laufstart
	private static void warteAufDatei(String path, long minBytes, long timeoutMs, long runStart) {
		File f = new File(path);
		long deadline = System.currentTimeMillis() - 1 + timeoutMs;
		while (System.currentTimeMillis() <= deadline) {
			if (f.exists() && f.length() >= minBytes && f.lastModified() >= runStart) {
				return;
			}
			try { Thread.sleep(500); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
		}
		System.out.println("Warnung: Timeout beim Warten auf Datei: " + path + " (exists=" + f.exists() + ", size=" + f.length() + ", lastMod=" + f.lastModified() + ")");
	}

	private static Map<String, Map<String, Double>> ladeAnalysePunkte(String dateiPfad) throws IOException {
		Map<String, Map<String, Double>> teamZuSpielerPunkte = new LinkedHashMap<>();
		try (BufferedReader br = new BufferedReader(new InputStreamReader(new FileInputStream(dateiPfad), StandardCharsets.UTF_8))) {
			String line;
			String currentTeam = null;
			while ((line = br.readLine()) != null) {
				line = line.trim();
				if (line.startsWith("=== ") && line.endsWith(" ===")) {
					currentTeam = line.substring(4, line.length() - 4).trim();
					teamZuSpielerPunkte.putIfAbsent(currentTeam, new LinkedHashMap<>());
					continue;
				}
				if (currentTeam == null || line.isEmpty()) continue;
				// Erwartetes Format: "1. Name: 10,0 Punkte (..")
				int dotIdx = line.indexOf('.');
				int colonIdx = line.indexOf(':');
				if (dotIdx > -1 && colonIdx > dotIdx + 1) {
					String name = line.substring(dotIdx + 1, colonIdx).trim();
					String rest = line.substring(colonIdx + 1).trim();
					Double punkte = parsePunkte(rest);
					if (punkte != null && !name.isEmpty()) {
						teamZuSpielerPunkte.get(currentTeam).put(name, punkte);
					}
				}
			}
		}
		return teamZuSpielerPunkte;
	}

	private static Double parsePunkte(String s) {
		// findet Zahl vor dem Wort "Punkte"
		int idx = s.toLowerCase(Locale.ROOT).indexOf("punkte");
		String num = (idx > 0 ? s.substring(0, idx) : s).replaceAll("[^0-9, .]", "").trim();
		num = num.replace('.', ' ').replace(',', '.').trim();
		num = num.replaceAll("\n", " ").replaceAll("\\s+", " ").trim();
		try {
			if (num.isEmpty()) return null;
			return Double.parseDouble(num);
		} catch (Exception e) {
			return null;
		}
	}

	private static void schreibeEmpfohleneKernspieler(Map<String, Map<String, List<String>>> alleKader,
			Map<String, Map<String, Double>> analysePunkte, String zielDatei) throws IOException {
		Map<String, String> normAnalyseTeamToReal = new HashMap<>();
		for (String t : analysePunkte.keySet()) {
			normAnalyseTeamToReal.put(normalizeForCompare(t), t);
		}

		try (OutputStream fos = new FileOutputStream(zielDatei);
		     OutputStreamWriter osw = new OutputStreamWriter(fos, StandardCharsets.UTF_8);
		     PrintWriter out = new PrintWriter(osw)) {
			// UTF-8 BOM schreiben für bessere Anzeige in einigen Windows-Editoren
			fos.write(new byte[]{(byte)0xEF, (byte)0xBB, (byte)0xBF});
			out.println("# Empfohlene Kernspieler pro Team (basierend auf AufstellungsAnalyzer)");
			out.println("# Generiert am: " + new Date());
			out.println("# Format: Team | Torwart | Abwehr | Mittelfeld1 | Mittelfeld2 | Angriff1 | Angriff2");
			out.println();

			for (Map.Entry<String, Map<String, List<String>>> teamEntry : alleKader.entrySet()) {
				String teamName = teamEntry.getKey();
				String normTeam = normalizeForCompare(teamName);
				String analyseTeamName = normAnalyseTeamToReal.get(normTeam);
				if (analyseTeamName == null) {
					// kleiner Fallback: versuche partielle Matches
					for (String k : normAnalyseTeamToReal.keySet()) {
						if (k.contains(normTeam) || normTeam.contains(k)) { analyseTeamName = normAnalyseTeamToReal.get(k); break; }
					}
				}
				Map<String, Double> punkteMap = analyseTeamName != null ? analysePunkte.getOrDefault(analyseTeamName, Collections.emptyMap()) : Collections.emptyMap();

				List<String> tor = waehleTopSpieler(punkteMap, teamEntry.getValue().getOrDefault("Torwart", Collections.emptyList()), 1);
				List<String> abw = waehleTopSpieler(punkteMap, teamEntry.getValue().getOrDefault("Abwehr", Collections.emptyList()), 1);
				List<String> mid = waehleTopSpieler(punkteMap, teamEntry.getValue().getOrDefault("Mittelfeld", Collections.emptyList()), 2);
				List<String> ang = waehleTopSpieler(punkteMap, teamEntry.getValue().getOrDefault("Angriff", Collections.emptyList()), 2);

				String line = String.join(" | ", Arrays.asList(
					formatTeamNameForApi(teamName),
					firstOrEmpty(tor, 0),
					firstOrEmpty(abw, 0),
					firstOrEmpty(mid, 0),
					firstOrEmpty(mid, 1),
					firstOrEmpty(ang, 0),
					firstOrEmpty(ang, 1)
				));
				out.println(line);
			}
		}
	}

	private static String firstOrEmpty(List<String> list, int idx) {
		return (list != null && list.size() > idx) ? list.get(idx) : "";
	}

	private static List<String> waehleTopSpieler(Map<String, Double> punkteMap, List<String> kandidatenOriginal, int anzahl) {
		// Baue Lookup: normalized name -> punkte
		Map<String, Double> normNameToPunkte = new HashMap<>();
		for (Map.Entry<String, Double> e : punkteMap.entrySet()) {
			normNameToPunkte.put(normalizeForCompare(e.getKey()), e.getValue());
		}
		List<String> result = new ArrayList<>();
		List<String> fehlende = new ArrayList<>();
		// Bewertungsliste
		List<SpielerPunkte> bewertungen = new ArrayList<>();
		for (String name : kandidatenOriginal) {
			String norm = normalizeForCompare(name);
			double p = normNameToPunkte.getOrDefault(norm, 0.0);
			bewertungen.add(new SpielerPunkte(name, p));
			if (!normNameToPunkte.containsKey(norm)) fehlende.add(name);
		}
		// Sortiere nach Punkten absteigend, stabil
		bewertungen.sort((a, b) -> Double.compare(b.punkte, a.punkte));
		for (SpielerPunkte sp : bewertungen) {
			if (result.size() >= anzahl) break;
			if (!result.contains(sp.name)) result.add(sp.name);
		}
		// Falls immer noch zu wenig, fülle mit beliebigen restlichen Kandidaten (ohne Duplikate)
		if (result.size() < anzahl) {
			for (String n : kandidatenOriginal) {
				if (result.size() >= anzahl) break;
				if (!result.contains(n)) result.add(n);
			}
		}
		// Trimme auf gewünschte Länge
		if (result.size() > anzahl) return new ArrayList<>(result.subList(0, anzahl));
		return result;
	}

	private static class SpielerPunkte {
		final String name;
		final double punkte;
		SpielerPunkte(String name, double punkte) { this.name = name; this.punkte = punkte; }
	}

	private static String normalizeForCompare(String s) {
		if (s == null) return "";
		String x = Normalizer.normalize(s, Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
		x = x.replace("ß", "ss").toLowerCase(Locale.ROOT);
		x = x.replaceAll("[^a-z0-9]", "");
		return x;
	}

	// Teamnamen für API/weitere Programme konsistent formatieren
	private static String formatTeamNameForApi(String original) {
		if (original == null) return "";
		String name = original;
		// 1) Prozent-Codierung (z.B. Preu%C3%9Fen) entschlüsseln
		try { name = java.net.URLDecoder.decode(name, java.nio.charset.StandardCharsets.UTF_8); } catch (Exception ignore) {}
		// 2) Bekannte Fehlkodierungen (UTF-8 als ISO-8859-1 gelesen) bereinigen
		name = name
				.replace("Ã„", "Ä").replace("Ã–", "Ö").replace("Ãœ", "Ü")
				.replace("Ã¤", "ä").replace("Ã¶", "ö").replace("Ã¼", "ü")
				.replace("ÃŸ", "ß");
		// 3) HTML-Entities abfangen
		name = name
				.replace("&Auml;", "Ä").replace("&Ouml;", "Ö").replace("&Uuml;", "Ü")
				.replace("&auml;", "ä").replace("&ouml;", "ö").replace("&uuml;", "ü")
				.replace("&szlig;", "ß");
		// 4) Nur ß zu ss vereinheitlichen (API-gerecht), Umlaute bleiben erhalten
		name = name.replace("ß", "ss");
		// 5) Whitespace normalisieren
		name = name.replaceAll("\\s+", " ").trim();
		return name;
	}

	private static void aufrufFitnessTool(String zielTxt) {
		try {
			File script = new File("fitness_check_tm.py");
			if (!script.exists()) {
				System.out.println("Hinweis: fitness_check_tm.py nicht gefunden – überspringe Fitness-Check.");
				return;
			}
			List<String[]> kandidaten = Arrays.asList(
					new String[]{"py", "-3", script.getAbsolutePath(), zielTxt},
					new String[]{"python", script.getAbsolutePath(), zielTxt},
					new String[]{"python3", script.getAbsolutePath(), zielTxt}
			);
			boolean ok = false;
			for (String[] cmd : kandidaten) {
				try {
					ProcessBuilder pb = new ProcessBuilder(cmd);
					pb.redirectErrorStream(true);
					Process p = pb.start();
					try (BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
						String ln;
						while ((ln = r.readLine()) != null) {
							System.out.println(ln);
						}
					}
					int exit = p.waitFor();
					if (exit == 0) { ok = true; break; }
					System.out.println("Hinweis: Python-Aufruf fehlgeschlagen (Exit=" + exit + ") mit: " + String.join(" ", cmd));
				} catch (Throwable t) {
					System.out.println("Hinweis: Python nicht ausführbar mit: " + String.join(" ", cmd) + " -> " + t.getMessage());
				}
			}
			if (!ok) {
				System.out.println("Hinweis: Konnte fitness_check_tm.py nicht ausführen. Bitte Python installieren oder manuell starten: python fitness_check_tm.py " + zielTxt);
			}
		} catch (Exception e) {
			System.out.println("Hinweis: Fitness-Tool konnte nicht gestartet werden: " + e.getMessage());
		}
	}

	private static String absolut(String basis, String href) {
		if (href == null || href.isEmpty()) return basis;
		try {
			URL b = new URL(basis);
			URL a = new URL(b, href);
			return a.toString();
		} catch (MalformedURLException e) {
			return href; // Fallback
		}
	}

	// Debug-Schreiber entfernt

	// slugify wird nicht mehr benötigt (Debugdateien entfernt)

	private static String fetchHtmlMitRetry(String url) {
		for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
			HttpURLConnection conn = null;
			try {
				URL u = new URL(url);
				conn = (HttpURLConnection) u.openConnection();
				conn.setConnectTimeout(12000);
				conn.setReadTimeout(15000);
				conn.setInstanceFollowRedirects(true);
				conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36");
				conn.setRequestProperty("Accept-Language", "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7");
				// Domain-spezifische Header
				String host = u.getHost().toLowerCase(Locale.ROOT);
				if (host.contains("api.sofascore.com")) {
					conn.setRequestProperty("Accept", "application/json, text/plain, */*");
					conn.setRequestProperty("Origin", "https://www.sofascore.com");
					conn.setRequestProperty("Referer", "https://www.sofascore.com/");
					conn.setRequestProperty("Cache-Control", "no-cache");
					conn.setRequestProperty("Pragma", "no-cache");
					conn.setRequestProperty("Accept-Encoding", "identity");
				} else if (host.contains("sofascore.com")) {
					conn.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
					conn.setRequestProperty("Referer", "https://www.sofascore.com/");
					conn.setRequestProperty("Accept-Encoding", "identity");
				} else {
					// Standard für bundesliga.com u.ä.
					conn.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
					conn.setRequestProperty("Referer", "https://www.bundesliga.com/");
				}

				int code = conn.getResponseCode();
				if (code == 200) {
					try (BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
						StringBuilder sb = new StringBuilder();
						String line;
						while ((line = br.readLine()) != null) sb.append(line).append('\n');
						return sb.toString();
					}
				} else {
					System.out.println("HTTP " + code + " für URL: " + url);
				}
			} catch (Exception ex) {
				System.out.println("Fehler (Versuch " + attempt + "): " + ex.getMessage() + " -> " + url);
			} finally {
				if (conn != null) conn.disconnect();
			}
			try { Thread.sleep(RETRY_DELAY_MS); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
		}
		return "";
	}
}


