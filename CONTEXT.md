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

### Interaktive Planungsphase (Interactive Planning Phase)
* **Definition**: Der interaktive Prozess mit menschlicher Beteiligung (HITL), in dem Anforderungen definiert (PRD, Glossary, ADRs) und in vorläufige Entwurfs-Aufgaben (Draft Issues) aufgeteilt werden.
* **Geschäftsregeln**: Wird durch den Benutzer in Kombination mit interaktiven Entwicklungs-Tools (z. B. Aider, OpenCode oder **LangChain deepagents**) und Prompt-Skills ausgeführt. Die Phase endet, sobald die Entwurfs-Aufgaben auf der Festplatte abgelegt sind.
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
  * Ist der Strict-Modus aktiviert, müssen zwingend erlaubte Quellen (Repositories oder Domains) definiert sein; andernfalls bricht das System den Start mit einem Fehler ab.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der allgemeinen Systemkonfiguration des Planners (wie Modellauswahl oder Zugriffsschlüssel).

### Agenten-Architekturentscheidung (Agent Decision Record - AgDR)
* **Definition**: Ein durch den autonomen Planungsprozess erstelltes Dokument zur Festhaltung wesentlicher technischer Richtungsentscheidungen. Es erweitert klassische ADRs um strukturierte Agenten-Metadaten und dient zukünftigen Entwicklungsschritten sowie menschlichen Entwicklern als historische Wissensbasis.
* **Geschäftsregeln**:
  * Jedes AgDR muss zwingend ein standardisiertes **Y-Statement** zur Kurzzusammenfassung der Entscheidung enthalten.
  * Das Dokument muss die evaluierten Alternativen (Optionen-Matrix) sowie die genauen Bewertungsgründe dokumentieren.
  * Zu den Pflicht-Metadaten gehören: das auswertende Kritik-Modell (`Model`), die Langfuse-Trace-ID (`Trace-ID`) sowie die auslösende Aufgabe (`Trigger-Issue`).
  * AgDR-Dokumente werden im Ziel-Repository im Verzeichnis `docs/agdr/` abgelegt.
* **Synonyme / Abzugrenzende Begriffe**: Abzugrenzen von klassischen, rein manuell durch menschliche Architekten erstellten Architekturentscheidungen (ADR).

