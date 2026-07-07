# 0010 - Direkte URL- und GitHub-API-Werkzeuge für Verifikation und Verfeinerung

* **Status**: Accepted
* **Datum**: 2026-07-07
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung
Während der Verifikationsphase (`verify` / `wise-teacher`) und der autonomen Verfeinerung (`refine` / Refinement Graph) müssen LLM-Agenten externe Dokumentationen oder Code-Referenzen abfragen.
Bislang verlässt sich das System primär auf Websuchen (z. B. via `openrouter:web_search`). Dies hat jedoch erhebliche Nachteile:
1. **Token- und API-Kosten**: Die Nutzung externer Websuch-APIs erzeugt zusätzliche Latenz und Kosten.
2. **Aktualität und Präzision**: Websuch-Indizes für GitHub-Repositories hinken oft Tage hinterher. Exakte Code-Referenzen, Issues oder Releases können per Websuche nur unpräzise abgefragt werden.
3. **Effizienz bei bekannten Quellen**: Wenn der Benutzer in der Quellen-Konfiguration (`sources.yaml`) bereits exakte URLs oder Repositories hinterlegt hat, ist ein direkter API- oder HTTP-Abruf weitaus effizienter.

## Entscheidungsfaktoren (Drivers)
* **Kosten- und Token-Reduktion**: Vermeidung unnötiger Websuchen.
* **Präzision**: Exakte Code- und Issue-Validierung in Ziel- und Dritt-Repositories.
* **Sicherheit im Strict-Modus**: Zuverlässiges Whitelisting von Zugriffen basierend auf Benutzer-Konfigurationen.
* **Einfache Konfiguration**: Schlanke `sources.yaml` ohne redundante Struktur.

## Betrachtete Optionen

### Option 1: Automatisches Pre-fetching aller Direkt-URLs
Alle in der Konfiguration definierten URLs werden beim Start heruntergeladen und als statischer Kontext in das System-Prompt injiziert.
* **Vorteil**: Keine Tool-Nutzung durch das LLM erforderlich.
* **Nachteil**: Bläht das Kontext-Fenster drastisch auf (erhöhte Token-Kosten), selbst wenn die Informationen für die Aufgabe irrelevant sind.

### Option 2: Statische Whitelist-Aufteilung in `sources.yaml`
Beibehaltung einer separaten `repositories`-Kategorie für GitHub-Repositories und `domains` für allgemeines Whitelisting.
* **Vorteil**: Strukturierte Unterscheidung auf Konfigurationsebene.
* **Nachteil**: Redundanz, wenn der Benutzer bereits GitHub-URLs in einer URL-Whitelist pflegt.

### Option 3: On-Demand Micro-Tools mit dynamischer Repository-Extraktion (Gewählt)
Wir statten das LLM mit fokussierten Werkzeugen für den bedarfsgerechten Abruf aus:
1. **`Fetch_URL_Tool`**: Holt Inhalte einer spezifischen URL per HTTP-GET.
2. **GitHub API Micro-Tools**:
   * `read_github_file(repo, path, ref)`
   * `list_github_issues(repo, state, per_page)`
   * `get_github_releases(repo, limit)`

In der `sources.yaml` wird die redundante `repositories`-Kategorie entfernt und durch eine flexiblere `urls`-Kategorie ergänzt. Erlaubte Repositories für die GitHub-API-Tools werden im Strict-Modus dynamisch abgeleitet:
* Das aktuelle Ziel-Repository (`GITHUB_REPOSITORY`) ist immer erlaubt.
* Jedes Repository, das in einer der in `urls` konfigurierten GitHub-URLs vorkommt (z. B. `https://github.com/owner/repo/...`), wird extrahiert und als erlaubt eingestuft.

## Entscheidung
Wir wählen **Option 3**. Dies bietet dem Agenten maximale Flexibilität bei minimalem Kontext-Verbrauch. Die Verwaltung der Zugriffsrechte im Strict-Modus erfolgt sicher und dynamisch anhand der Benutzerkonfiguration.

### Umsetzung nach Phase

#### Verifikationsphase (`verify` / `wise-teacher`)
Die vier On-Demand Micro-Tools (`Fetch_URL_Tool`, `read_github_file`, `list_github_issues`,
`get_github_releases`) werden dem `wise-teacher`-Agenten in `run_verify` direkt als ausführbare
Werkzeuge übergeben. Der Agent ruft sie bei Bedarf eigenständig auf.

#### Verfeinerungsphase (`refine` / Refinement Graph)
Der Refinement-Graph läuft autonom (ohne interaktive Tool-Calls) und nutzt den `web_search_node`
als einzigen Recherche-Kanal. Für diesen Kanal wird ein **begrenztes Pre-fetching** eingesetzt:

- Konfigurierte `sources.urls` werden beim Einstieg in `web_search_node` direkt abgerufen
  (`fetch_allowed_url`).
- Die Ergebnisse werden als erste Einträge in `search_results` **vorangestellt** (nicht ins
  System-Prompt injiziert).
- `search_results` ist auf maximal 10 Einträge gekappt.
- **Snippet-Limits nach Quelle:** Direkt-URL-Inhalte (via `fetch_allowed_url`) werden auf
  2000 Zeichen gekürzt — diese Quellen sind gezielt konfigurierte Dokumentations-URLs, die
  einen längeren Auszug rechtfertigen. Web-Suchergebnis-Snippets werden auf 300 Zeichen
  gekürzt (flüchtige Treffer, nur Orientierung nötig).

**Abgrenzung zu Option 1 (abgelehnt):** Option 1 injizierte alle URL-Inhalte statisch ins
System-Prompt bei jedem LLM-Call — unabhängig von Relevanz und ohne Größenbeschränkung.
Das bounded Pre-fetching im `web_search_node` ist grundsätzlich verschieden: es ist auf den
Refinement-Schritt begrenzt, durch die 10er-Gesamtgrenze kontrolliert, differenziert nach
Quellentyp begrenzt (2000 Zeichen für konfigurierte Direkt-URLs, 300 Zeichen für
Websuch-Treffer) und wird nur ausgeführt, wenn `sources.urls` konfiguriert sind.

### Konsequenzen
* **Positiv**:
  * Massive Token- und Latenzersparnis bei bekannten Dokumentations-URLs und Code-Referenzen.
  * Hohe Präzision der Agenten-Antworten auf Code-Ebene.
  * Geringere Komplexität der Konfiguration (`sources.yaml` enthält nur noch `domains` und `urls`).
* **Negativ**:
  * Agenten müssen Tool-Calls korrekt absetzen. Dies erfordert saubere Beschreibungen im System-Prompt.
  * Benutzer müssen sicherstellen, dass ihr `GH_PAT` die nötigen Leserechte (Code, Issues, Releases) besitzt.

## Inspiration & Referenzen
* GitHub REST-API Dokumentation für Repository-Inhalte, Issues und Releases.
* LangChain Tool-Binding Best Practices für bedarfsgerechten Informationsabruf.

