# Domain Glossary

Dieses Dokument definiert die fachliche Terminologie für diesen Kontext. Es darf keine technischen Implementierungsdetails (wie Datenbanken, Klassen oder Frameworks) enthalten.

## Begriffe

### Agentic Planner
* **Definition**: Der end-to-end Prozess, der ein vages Vorhaben in detaillierte, qualitätsgesicherte und architekturkonforme Aufgabenspezifikationen überführt. Der Prozess endet mit der Übergabe der Spezifikationen an das Ziel-Repository — die eigentliche Umsetzung (Codierung, Testing) liegt außerhalb des Scopes.
* **Geschäftsregeln**: Der Planner erzeugt freigegebene Aufgabenspezifikationen, die direkt von einem Ausführungssystem konsumiert werden können.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit dem *Autonomous Developer Loop*, welcher die Aufgaben tatsächlich umsetzt.

### Ziel-Repository (Target Repository)
* **Definition**: Das externe Softwareprojekt, für welches der Planner konzeptionelle Dokumente und Aufgabenspezifikationen erzeugt.
* **Geschäftsregeln**: Alle erzeugten Konzepte, Architekturentscheidungen und Aufgabenspezifikationen gehören fachlich zum Ziel-Repository. Der Planner selbst besitzt und verwaltet nur seinen eigenen Programmcode.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit dem Programmdatenbestand (Repository), in dem der Code des Planners selbst lebt.

### Entwurfs-Aufgabe (Draft Issue)
* **Definition**: Eine vorläufige, temporäre Arbeitskopie einer Aufgabenspezifikation, die ein einzelnes Arbeitspaket beschreibt. Sie wird in der interaktiven Planungsphase erstellt und in der autonomen Verfeinerungsphase veredelt, ohne im zentralen Versionsverlauf des Ziel-Repositories abgelegt zu werden.
* **Geschäftsregeln**: Jede Entwurfs-Aufgabe durchläuft die autonome Verfeinerungsphase (Recherche, Architekturabgleich, Umschreiben), bevor sie als offizielle Aufgabe freigegeben wird. Nach der Freigabe wird die temporäre Arbeitskopie entfernt.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit einer freigegebenen oder veröffentlichten Aufgabe.

### Implementierungsbereite Aufgabe (Implementation-Ready Issue)
* **Definition**: Eine verfeinerte, veröffentlichte Aufgabenspezifikation, die neben den ursprünglichen Abschnitten einen gewählten Lösungsansatz mit Begründung, einen dateipfadbezogenen Umsetzungsplan, geprüfte Code-Muster mit Quellenangaben sowie aufgelöste Mehrdeutigkeiten enthält — so dass das nachgelagerte Ausführungssystem ohne erneute Recherche oder Architekturentscheidungen implementieren kann.
* **Geschäftsregeln**: Die zusätzlichen Abschnitte werden in der autonomen Verfeinerungsphase injiziert und auf Basis der Rechercheergebnisse und der Kritiker-Bewertung befüllt. Die Spezifikation enthält kanonische Muster und Zielorte, keinen fertigen Code und keine Feature-Branches (ADR-0001, PRD AC1).
* **Synonyme / Abzugrenzende Begriffe**: Abzugrenzen von der schmaleren *Entwurfs-Aufgabe*, die nur die menschlich verfassten Basisabschnitte enthält.

### Interaktive Planungsphase (Interactive Planning Phase)
* **Definition**: Der interaktive Prozess mit menschlicher Beteiligung (HITL), in dem Anforderungen definiert (PRD, Glossary, ADRs) und in vorläufige Entwurfs-Aufgaben (Draft Issues) aufgeteilt werden.
* **Geschäftsregeln**: Wird durch den Benutzer in Kombination mit interaktiven Entwicklungs-Tools und Prompt-Skills ausgeführt. Die Phase endet, sobald die Entwurfs-Aufgaben auf der Festplatte abgelegt sind.
* **Synonyme / Abzugrenzende Begriffe**: Umfasst die Begriffe *PRD-Erstellung* und *Aufgabenspaltung (Issue Splitting)*.

### Autonome Verfeinerungsphase (Autonomous Refinement Phase)
* **Definition**: Der vollautomatische Prozess (ohne HITL), bei dem jede Entwurfs-Aufgabe einzeln durch gezielte Recherche, Prüfung gegen bestehende Architekturentscheidungen (ADRs) sowie Lösungsbewertung verfeinert und auf GitHub veröffentlicht wird.
* **Geschäftsregeln**: Die Verfeinerung jeder einzelnen Entwurfs-Aufgabe läuft kontextuell isoliert ab, damit Rechercheergebnisse einer Aufgabe nicht den Inhalt oder Kontext anderer Aufgaben beeinflussen. Die Phase läuft als zusammenhängender Batch-Prozess über die CLI ab.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der interaktiven Planungsphase. Beinhaltet den *Verfeinerungs-Prozess (Refinement Process)* für die einzelnen Entwurfs-Aufgaben.

### Lösungsbewertung (Solution Grading)
* **Definition**: Das strukturierte Prüfverfahren zur Bewertung verschiedener technischer Lösungsansätze für eine Aufgabe. Ein unabhängiger Prüfer bewertet vorgeschlagene Optionen gegen bestehende Richtlinien und Architekturentscheidungen.
* **Geschäftsregeln**: Die Bewertung erfolgt vollautomatisch anhand einer vorgegebenen Bewertungsmatrix. Die Entscheidung über den gewählten Lösungsansatz wird begründet und protokolliert.
* **Synonyme / Abzugrenzende Begriffe**: Folgt dem Generator-Prüfer-Pattern. Nicht zu verwechseln mit dem manuellen Review-Prozess durch Personen.

### Quellen-Konfiguration (Source Configuration)
* **Definition**: Die Vorgabe von vertrauenswürdigen Informationsquellen und Rahmenbedingungen für die automatisierte Recherche. Sie enthält einen Sicherheitsmodus (Strict-Modus), um die Recherche streng auf die freigegebenen Quellen zu beschränken.
* **Geschäftsregeln**: 
  * Im Strict-Modus werden Recherchen ausschließlich innerhalb der konfigurierten Quellen durchgeführt, um die Einschleusung unkontrollierter oder verfälschter Fremdinformationen zu verhindern.
  * Ist der Strict-Modus aktiviert, müssen zwingend erlaubte Quellen (Domains oder Direkt-URLs) definiert sein; andernfalls bricht das System den Start mit einem Fehler ab.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der allgemeinen Systemkonfiguration des Planners (wie Modellauswahl oder Zugriffsschlüssel).

### Agenten-Architekturentscheidung (Agent Decision Record - AgDR)
* **Definition**: Ein durch den autonomen Planungsprozess erstelltes Dokument zur Festhaltung wesentlicher technischer Richtungsentscheidungen. Es erweitert klassische ADRs um strukturierte Agenten-Metadaten und dient zukünftigen Entwicklungsschritten sowie menschlichen Entwicklern als historische Wissensbasis.
* **Geschäftsregeln**:
  * Jedes AgDR muss zwingend ein standardisiertes **Y-Statement** zur Kurzzusammenfassung der Entscheidung enthalten.
  * Das Dokument muss die evaluierten Alternativen (Optionen-Matrix) sowie die genauen Bewertungsgründe dokumentieren.
  * Zu den Pflicht-Metadaten gehören: das auswertende Kritik-Modell (`Model`), die Langfuse-Trace-ID (`Trace-ID`) sowie die auslösende Aufgabe (`Trigger-Issue`).
  * AgDR-Dokumente werden im Ziel-Repository im Verzeichnis `docs/agdr/` abgelegt.
* **Synonyme / Abzugrenzende Begriffe**: Abzugrenzen von klassischen, rein manuell durch menschliche Architekten erstellten Architekturentscheidungen (ADR).

### Grill-Session (Grill Session)
* **Definition**: Die interaktive Fragerunde (grill-with-docs) zwischen der Person und dem Planner-Agenten zur Abstimmung des Designs eines Ziel-Repositories. Sie dient der Veredelung des PRD, der Glossareinträge und der Architekturentscheidungen.
* **Geschäftsregeln**:
  * Die Grill-Session wird lokal serialisiert und bei jedem Interaktionsschritt (nach jedem Agentenschritt und jeder Benutzereingabe) automatisch unter einem zeitstempelbasierten Dateinamen gesichert, um den Sitzungszustand abzusichern.
  * Eine unvollständige Grill-Session kann beim Start der CLI fortgesetzt werden. Hierbei wird der gespeicherte Nachrichtenverlauf deserialisiert und die Interaktion an der Stelle des letzten Beitrags wieder aufgenommen.
  * Die Grill-Session kann optional aufgezeichnet und für Analysezwecke übermittelt werden, wobei alle zugehörigen Interaktionen der jeweiligen Sitzung zugeordnet werden.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der autonomen Verfeinerungsphase.

### Sitzungs-Serialisierung (Session Serialization)
* **Definition**: Der Prozess, bei dem der Verlauf einer Grill-Session inklusive aller Benutzer- und Agenten-Nachrichten in einem standardisierten JSON-Format persistiert wird.
* **Geschäftsregeln**: Jede Nachricht wird mit ihrem Typ (`human`, `ai`, `system`, `tool`) und Inhalt serialisiert. Tool-Aufrufe (`tool_calls`) und Tool-Antworten werden mitgesichert, um die Interaktionshistorie vollständig abzubilden.

### Direkt-URL-Abruf (Direct URL Fetch)
* **Definition**: Der gezielte Abruf von Inhalten einer konkreten, vertrauenswürdigen Webadresse ohne die Einbindung externer Suchmaschinen.
* **Geschäftsregeln**: Der Abruf erfolgt on-demand und wird im Sicherheitsmodus streng auf die vom Benutzer konfigurierten Ziel-Webadressen beschränkt.

### Repository-API-Abruf (Repository API Retrieval)
* **Definition**: Die Abfrage von Code-Dateien, Fehlerberichten (Issues) oder Produktveröffentlichungen (Releases) eines Softwareprojekts direkt über die Programmierschnittstelle der Hosting-Plattform.
* **Geschäftsregeln**: Dient der präzisen und verzögerungsfreien Überprüfung des aktuellen Entwicklungsstands und von Code-Inhalten im Ziel-Repository oder in freigegebenen Fremdprojekten. Im Sicherheitsmodus wird der Zugriff streng auf das Ziel-Repository sowie auf die aus den freigegebenen Webadressen abgelitteneten Repositories beschränkt.

### Judge-Evaluierungssuite (Judge Evaluation Suite)
* **Definition**: Die Regressionstest-Suite, die jeden binären PR-Judge (`syntax_lint`, `test_coverage`, `architecture`, `security`) gegen einen menschlich annotierten Gold-Standard ausführt und statistische Übereinstimmungskennzahlen berechnet, um Modellwechsel in der zentralen Konfiguration quantifizierbar zu machen.
* **Geschäftsregeln**: Jeder Judge wird isoliert evaluiert. Die Suite erzeugt keine automatische Blockade (Gate), sondern liefert Kennzahlen (Cohen's Kappa, MAE, Hard Flips, Verbosity Bias) sowie OpenRouter-Kosten und Time-to-First-Token zur menschlichen Bewertung. Alle Judge-Aufrufe erfolgen deterministisch (`temperature = 0.0`).
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der *Lösungsbewertung (Solution Grading)*, die numerische 0–10-Noten für Lösungs-Optionen vergibt (`evaluate_grade`), und nicht mit dem Laufzeit-PR-Review-Prozess selbst.

### Gold-Standard (Gold Standard)
* **Definition**: Ein Datensatz menschlich annotierter Beispiele (Diffs mit erwartetem Verdict und Score), gegen den ein Judge-Modell kalibriert wird.
* **Geschäftsregeln**: Jedes Sample enthält ein erwartetes binäres `passed`-Urteil und einen erwarteten Score (0.0/1.0 für binäre PR-Judges). Die Samples liegen als Fixtures unter `tests/eval/fixtures/<judge_type>/` vor.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit *Entwurfs-Aufgaben (Draft Issues)*, die zu veredelnde Arbeitspakete sind.

### Hard Flip
* **Definition**: Ein Sample, bei dem das `passed`-Urteil des Judge-Modells vom `passed`-Urteil des Gold-Standards abweicht — also der Modellwechsel das Verdict gekippt hat.
* **Geschäftsregeln**: Hard Flips werden unabhängig vom MAE separat ausgewiesen, da ein gekipptes Pass/Fail-Urteil (Merge-Blockade vs. Freigabe) geschäftlich folgenreicher ist als eine numerische Abweichung.
* **Synonyme / Abzugrenzende Begriffe**: Abzugrenzen vom MAE, der die mittlere absolute Score-Differenz misst.

### Verbosity Bias
* **Definition**: Die Korrelation zwischen der Diff-Länge (Token) und der Score-Differenz zwischen Judge und Gold-Standard. Er zeigt an, ob ein Judge-Modell längere Diffs systematisch anders bewertet.
* **Geschäftsregeln**: Bei einem Pearson-Korrelationskoeffizienten r > 0.3 wird der Bias als flagriert markiert.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der allgemeinen Modellqualität; ein Verbosity Bias ist ein Kalibrierungs-Artefakt, kein inhaltliches Urteil.

### Time-to-First-Token (TTFT)
* **Definition**: Die Zeitspanne zwischen dem Absenden einer OpenRouter-Anfrage und dem Empfang des ersten generierten Token.
* **Geschäftsregeln**: Wird client-seitig über Streaming (SSE) direkt gegen OpenRouter gemessen. Wenn ein Judge-Modell kein Streaming unterstützt, ist TTFT undefiniert und wird als `null` (nicht 0) protokolliert.
* **Synonyme / Abzugrenzende Begriffe**: Abzugrenzen von der Gesamtlatenz; TTFT erfasst ausschließlich den First-Byte-Anteil.



