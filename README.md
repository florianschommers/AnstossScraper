# Anstoss Scraper

Dieses Repository enthält einen automatisierten Scraper für Anstoss-Daten.  
Die Scraper laufen **automatisch über GitHub Actions** und erzeugen Textdateien im Ordner [`data/`](data/).

---

## 📂 Ergebnisse abrufen

Die erzeugten Dateien liegen im Repo unter [`data/`](data/).  
Du kannst sie direkt per RAW-URL abrufen, z. B.:

https://raw.githubusercontent.com/florianschommers/anstoss-scraper/main/data/empfohlene_spieler_pro_team.txt


---

## ⚙️ Workflow starten

1. Gehe in deinem Repo auf den Reiter **Actions**.  
2. Wähle den Workflow **Scrape and publish data**.  
3. Klicke rechts oben auf **Run workflow** → der Scraper läuft.  
4. Nach erfolgreichem Lauf findest du die aktualisierten `.txt`-Dateien im Ordner `data/`.

Der Workflow läuft außerdem automatisch **jeden Tag um 06:00 UTC**.

---

## 📝 Hinweise

- Alle Dateien sind **UTF-8** kodiert (achte darauf beim Einlesen in deine App).  
- Falls eine Seite das Scraping blockt, kannst du später einen Self-Hosted Runner verwenden.  
- Der Workflow committet nur, wenn sich die Dateien tatsächlich geändert haben.  

---

## 📦 Struktur

anstoss-scraper/
├── data/ # erzeugte Textdateien (Output)
├── *.java # Scraper-Klassen (z. B. KaderScraper.java)
├── *.txt # Eingabedateien (Lookup-Tabellen etc.)
├── .github/workflows/ # GitHub Actions Workflow
└── README.md # diese Datei
