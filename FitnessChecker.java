import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.*;
import java.util.regex.*;

public class FitnessChecker {

	private static final String URL_BL1_VERLETZTE = "https://www.transfermarkt.de/bundesliga/verletztespieler/wettbewerb/L1";
	private static final String URL_BL2_VERLETZTE = "https://www.transfermarkt.de/2-bundesliga/verletztespieler/wettbewerb/L2";
	// Hinweis: Für BL1-Sperren wird oft die .com-Domain verwendet
	private static final String URL_BL1_SPERREN   = "https://www.transfermarkt.com/bundesliga/sperrenausfaelle/wettbewerb/L1";
	private static final String URL_BL2_SPERREN   = "https://www.transfermarkt.de/bundesliga/sperrenausfaelle/wettbewerb/L2";

	public static void main(String[] args) {
		if (args.length != 1) {
			System.out.println("Usage: java FitnessChecker <empfohlene_spieler_pro_team.txt>");
			return;
		}
		try {
			markPlayersInTxt(args[0]);
		} catch (Exception e) {
			System.err.println("FEHLER: " + e.getMessage());
			e.printStackTrace();
		}
	}

	public static void markPlayersInTxt(String inputTxt) throws IOException {
		Map<String, String> status = buildStatusDict();
		List<String> lines;
		try (BufferedReader br = new BufferedReader(new InputStreamReader(new FileInputStream(inputTxt), StandardCharsets.UTF_8))) {
			lines = new ArrayList<>();
			String line;
			while ((line = br.readLine()) != null) lines.add(line);
		}

		List<String> out = new ArrayList<>();
		Pattern stripFalse = Pattern.compile("\\s*\\(false(?::[a-z]+)?\\)$", Pattern.CASE_INSENSITIVE);
		for (String raw : lines) {
			if (raw == null || raw.isEmpty() || raw.startsWith("#")) {
				out.add(raw);
				continue;
			}
			String[] parts = raw.split("\\|");
			if (parts.length < 7) { out.add(raw); continue; }

			String team = parts[0].trim();
			List<String> players = new ArrayList<>();
			for (int i = 1; i <= 6; i++) {
				String p = parts[i].trim();
				p = stripFalse.matcher(p).replaceAll("");
				players.add(p);
			}

			List<String> updated = new ArrayList<>();
			for (String p : players) {
				if (p.isEmpty()) { updated.add(p); continue; }
				String s = null;
				for (String key : normVariants(p)) { s = status.get(key); if (s != null) break; }
				if (s == null) { updated.add(p); }
				else { updated.add(p + " (false:" + s + ")"); }
			}

			StringBuilder sb = new StringBuilder();
			sb.append(team);
			for (String v : updated) sb.append(" | ").append(v);
			out.add(sb.toString());
		}

		try (OutputStream fos = new FileOutputStream(inputTxt);
			 OutputStreamWriter osw = new OutputStreamWriter(fos, StandardCharsets.UTF_8);
			 PrintWriter pw = new PrintWriter(osw)) {
			// BOM für Windows-Editoren
			fos.write(new byte[]{(byte)0xEF, (byte)0xBB, (byte)0xBF});
			for (String l : out) pw.println(l);
		}
		System.out.println("✓ Fitness-Status aktualisiert in: " + inputTxt);
	}

	// NEU: Prüft, ob Spieler noch im aktuellen Kader des Teams stehen, sonst markieren
	public static void markNotInSquad(String recFile, String squadFile) throws IOException {
		Map<String, Set<String>> teamKeyToPlayerKeys = buildSquadIndex(squadFile);
		List<String> lines;
		try (BufferedReader br = new BufferedReader(new InputStreamReader(new FileInputStream(recFile), StandardCharsets.UTF_8))) {
			lines = new ArrayList<>();
			String line;
			while ((line = br.readLine()) != null) lines.add(line);
		}

		Pattern falseTail = Pattern.compile("\\s*\\(false:([^)]*)\\)\\s*$", Pattern.CASE_INSENSITIVE);
		List<String> out = new ArrayList<>();
		for (String raw : lines) {
			if (raw == null || raw.isEmpty() || raw.startsWith("#")) { out.add(raw); continue; }
			String[] parts = raw.split("\\|");
			if (parts.length < 7) { out.add(raw); continue; }
			String team = parts[0].trim();
			Set<String> teamKeys = normTeamKeys(team);
			Set<String> squadKeys = new LinkedHashSet<>();
			for (String tk : teamKeys) {
				Set<String> s = teamKeyToPlayerKeys.get(tk);
				if (s != null) squadKeys.addAll(s);
			}

			List<String> updated = new ArrayList<>();
			for (int i = 1; i <= 6; i++) {
				String p = parts[i].trim();
				if (p.isEmpty()) { updated.add(p); continue; }
				Matcher m = falseTail.matcher(p);
				String existing = null;
				String base = p;
				if (m.find()) { existing = m.group(1); base = p.substring(0, m.start()).trim(); }
				boolean inSquad = false;
				for (String v : normVariants(base)) { if (squadKeys.contains(v)) { inSquad = true; break; } }
				if (inSquad) {
					updated.add(p);
				} else {
					String newMark = (existing == null || existing.isEmpty()) ? "nicht_im_kader" : (existing + ",nicht_im_kader");
					updated.add(base + " (false:" + newMark + ")");
				}
			}

			StringBuilder sb = new StringBuilder();
			sb.append(team);
			for (String v : updated) sb.append(" | ").append(v);
			out.add(sb.toString());
		}

		try (OutputStream fos = new FileOutputStream(recFile);
		     OutputStreamWriter osw = new OutputStreamWriter(fos, StandardCharsets.UTF_8);
		     PrintWriter pw = new PrintWriter(osw)) {
			fos.write(new byte[]{(byte)0xEF, (byte)0xBB, (byte)0xBF});
			for (String l : out) pw.println(l);
		}
		System.out.println("✓ Kader-Status aktualisiert in: " + recFile);
	}

	private static Map<String, Set<String>> buildSquadIndex(String squadFile) throws IOException {
		Map<String, Set<String>> idx = new HashMap<>();
		try (BufferedReader br = new BufferedReader(new InputStreamReader(new FileInputStream(squadFile), StandardCharsets.UTF_8))) {
			String line;
			Set<String> currentTeamKeys = null;
			while ((line = br.readLine()) != null) {
				String li = line.trim();
				if (li.startsWith("=== ") && li.endsWith(" ===")) {
					String team = li.substring(4, li.length() - 4).trim();
					currentTeamKeys = normTeamKeys(team);
					for (String tk : currentTeamKeys) idx.computeIfAbsent(tk, k -> new LinkedHashSet<>());
					continue;
				}
				if (currentTeamKeys == null) continue;
				if (li.startsWith("- ")) {
					String name = li.substring(2).trim();
					for (String key : normVariants(name)) {
						for (String tk : currentTeamKeys) idx.get(tk).add(key);
					}
				}
			}
		}
		return idx;
	}

	private static Set<String> normTeamKeys(String team) {
		Set<String> s = new LinkedHashSet<>();
		String t = decodeWeird(team);
		String base = norm(t);
		s.add(base);
		s.add(collapseUmlautFallbacks(base)); // z.B. muenster -> munster
		return s;
	}

	private static String decodeWeird(String s) {
		if (s == null) return "";
		String x = s;
		try { x = java.net.URLDecoder.decode(x, StandardCharsets.UTF_8); } catch (Exception ignore) {}
		x = x.replace("Ã„", "Ä").replace("Ã–", "Ö").replace("Ãœ", "Ü")
				.replace("Ã¤", "ä").replace("Ã¶", "ö").replace("Ã¼", "ü")
				.replace("ÃŸ", "ß");
		return x;
	}

	private static String collapseUmlautFallbacks(String s) {
		return s.replace("ae", "a").replace("oe", "o").replace("ue", "u");
	}

	private static Map<String, String> buildStatusDict() {
		Set<String> injured = new LinkedHashSet<>();
		Set<String> p1 = fetchPlayers(URL_BL1_VERLETZTE); System.out.println("Verletzte BL1: " + p1.size()); injured.addAll(p1);
		Set<String> p2 = fetchPlayers(URL_BL2_VERLETZTE); System.out.println("Verletzte BL2: " + p2.size()); injured.addAll(p2);
		Set<String> suspended = new LinkedHashSet<>();
		Set<String> p3 = fetchPlayers(URL_BL1_SPERREN); System.out.println("Sperren BL1: " + p3.size()); suspended.addAll(p3);
		Set<String> p4 = fetchPlayers(URL_BL2_SPERREN); System.out.println("Sperren BL2: " + p4.size()); suspended.addAll(p4);

		Map<String, String> map = new HashMap<>();
		for (String p : injured) {
			for (String key : normVariants(p)) map.putIfAbsent(key, "verletzt");
		}
		for (String p : suspended) {
			for (String key : normVariants(p)) map.putIfAbsent(key, "gesperrt");
		}
		return map;
	}

	private static Set<String> fetchPlayers(String url) {
		String html = fetchHtml(url);
		Set<String> players = new LinkedHashSet<>();
		if (html.isEmpty()) return players;
		// Strategie 1: Klassischer Link mit Klasse spielprofil_tooltip
		Pattern a1 = Pattern.compile("<a[^>]*class=\\\"[^\\\"]*spielprofil_tooltip[^\\\"]*\\\"[^>]*>([^<]+)</a>", Pattern.CASE_INSENSITIVE);
		Matcher m1 = a1.matcher(html);
		while (m1.find()) { String name = clean(m1.group(1)); if (!name.isEmpty()) players.add(name); }
		// Strategie 2: Profil-Link ohne Klasse, aber mit Profil-URL
		Pattern a2 = Pattern.compile("<a[^>]*href=\\\"/[^\\\"]*/profil/spieler/\\d+[^>]*>([^<]+)</a>", Pattern.CASE_INSENSITIVE);
		Matcher m2 = a2.matcher(html);
		while (m2.find()) { String name = clean(m2.group(1)); if (!name.isEmpty()) players.add(name); }
		// Strategie 3: Titel-Attribut wie title=\"Profil von X\"
		Pattern a3 = Pattern.compile("title=\\\"Profil von ([^\\\"]+)\\\"", Pattern.CASE_INSENSITIVE);
		Matcher m3 = a3.matcher(html);
		while (m3.find()) { String name = clean(m3.group(1)); if (!name.isEmpty()) players.add(name); }
		// Strategie 4: IMG alt=\"Name\"
		Pattern img = Pattern.compile("<img[^>]*alt=\\\"([^\\\"]+)\\\"[^>]*>", Pattern.CASE_INSENSITIVE);
		Matcher m4 = img.matcher(html);
		while (m4.find()) { String name = clean(m4.group(1)); if (!name.isEmpty()) players.add(name); }
		return players;
	}

	private static String fetchHtml(String url) {
		for (int attempt = 1; attempt <= 3; attempt++) {
			HttpURLConnection conn = null;
			try {
				URL u = new URL(url);
				conn = (HttpURLConnection) u.openConnection();
				conn.setConnectTimeout(12000);
				conn.setReadTimeout(15000);
				conn.setInstanceFollowRedirects(true);
				conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36");
				conn.setRequestProperty("Accept-Language", "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7");
				conn.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
				conn.setRequestProperty("Referer", "https://www.transfermarkt.de/");
				int code = conn.getResponseCode();
				if (code == 200) {
					try (BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
						StringBuilder sb = new StringBuilder();
						String line;
						while ((line = br.readLine()) != null) sb.append(line).append('\n');
						return sb.toString();
					}
				}
				System.out.println("HTTP " + code + " bei " + url);
			} catch (Exception e) {
				System.out.println("Fehler beim Laden: " + e.getMessage());
			} finally {
				if (conn != null) conn.disconnect();
			}
			try { Thread.sleep(1200); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
		}
		return "";
	}

	private static String clean(String s) {
		if (s == null) return "";
		return s.replaceAll("<[^>]+>", " ").replace("&nbsp;", " ").replaceAll("\\s+", " ").trim();
	}

	private static String norm(String s) {
		if (s == null) return "";
		String x = s.replace("&amp;", "&").toLowerCase(Locale.ROOT).trim();
		x = Normalizer.normalize(x, Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
		x = x.replace("ß", "ss");
		x = x.replaceAll("[^a-z0-9]", "");
		return x;
	}

	private static String lastName(String name) {
		if (name == null) return "";
		String n = name.trim().replaceAll("\\s+", " ");
		String[] parts = n.split("[ -]");
		return parts.length == 0 ? n : parts[parts.length - 1];
	}

	private static String firstName(String name) {
		if (name == null) return "";
		String n = name.trim().replaceAll("\\s+", " ");
		String[] parts = n.split("[ -]");
		return parts.length > 0 ? parts[0] : n;
	}

	private static Set<String> normVariants(String name) {
		Set<String> keys = new LinkedHashSet<>();
		String base = norm(name);
		keys.add(base);
		String ln = norm(lastName(name));
		String fn = norm(firstName(name));
		if (!ln.isEmpty() && !fn.isEmpty()) keys.add(ln + fn);
		if (ln.length() >= 4) keys.add(ln);
		return keys;
	}
}


