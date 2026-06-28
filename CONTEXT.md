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
* **Definition**: Eine vorläufige, temporäre Arbeitskopie einer Aufgabenspezifikation, die ein einzelnes Arbeitspaket beschreibt. Sie existiert nur während der Planungs- und Verfeinerungsphase und wird nicht im zentralen Versionsverlauf des Ziel-Repositories abgelegt.
* **Geschäftsregeln**: Jede Entwurfs-Aufgabe durchläuft einen Verfeinerungsprozess (Recherche, Architekturabgleich, Umschreiben), bevor sie als offizielle Aufgabe freigegeben wird. Nach der Freigabe wird die temporäre Arbeitskopie entfernt.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit einer freigegebenen oder veröffentlichten Aufgabe.

### Verfeinerungs-Prozess (Refinement Process)
* **Definition**: Der isolierte Arbeitsablauf zur inhaltlichen Anreicherung und Validierung einer einzelnen Entwurfs-Aufgabe. Er beinhaltet die gezielte Recherche, die Prüfung der Vereinbarkeit mit bestehenden Architekturentscheidungen sowie die Bewertung von Umsetzungsoptionen.
* **Geschäftsregeln**: Die Verfeinerung einer Aufgabe läuft kontextuell isoliert ab, damit Rechercheergebnisse einer Aufgabe nicht den Inhalt oder Kontext anderer Aufgaben beeinflussen.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit dem übergeordneten Planungsprozess, welcher die Iteration über alle Entwurfs-Aufgaben steuert.

### Lösungsbewertung (Solution Grading)
* **Definition**: Das strukturierte Prüfverfahren zur Bewertung verschiedener technischer Lösungsansätze für eine Aufgabe. Ein unabhängiger Prüfer bewertet vorgeschlagene Optionen gegen bestehende Richtlinien und Architekturentscheidungen.
* **Geschäftsregeln**: Die Bewertung erfolgt vollautomatisch anhand einer vorgegebenen Bewertungsmatrix. Die Entscheidung über den gewählten Lösungsansatz wird begründet und protokolliert.
* **Synonyme / Abzugrenzende Begriffe**: Folgt dem Generator-Prüfer-Pattern. Nicht zu verwechseln mit dem manuellen Review-Prozess durch Personen.

### Aufgabenspaltung (Issue Splitting)
* **Definition**: Die Zerlegung eines fachlichen Gesamtanforderungsdokuments in kleinere, in sich geschlossene und unabhängig voneinander umsetzbare Entwurfs-Aufgaben.
* **Geschäftsregeln**: Die Spaltung erfolgt auf Basis von fachlich vertikalen Schnitten (Tracer-Bullet Vertical Slices) und beinhaltet eine Rückkopplungsschleife zur Abstimmung der Aufgabengranularität.
* **Synonyme / Abzugrenzende Begriffe**: Abzugrenzen von der inhaltlichen Verfeinerung, welche erst nach der Spaltung für jedes einzelne Element stattfindet.

### Quellen-Konfiguration (Source Configuration)
* **Definition**: Die Vorgabe von vertrauenswürdigen Informationsquellen und Rahmenbedingungen für die automatisierte Recherche. Sie enthält einen Sicherheitsmodus (Strict-Modus), um die Recherche streng auf die freigegebenen Quellen zu beschränken.
* **Geschäftsregeln**: 
  * Im Strict-Modus werden Recherchen ausschließlich innerhalb der konfigurierten Quellen durchgeführt, um die Einschleusung unkontrollierter oder verfälschter Fremdinformationen zu verhindern.
  * Ist der Strict-Modus aktiviert, müssen zwingend erlaubte Quellen (Repositories oder Domains) definiert sein; andernfalls bricht das System den Start mit einem Fehler ab.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der allgemeinen Systemkonfiguration des Planners (wie Modellauswahl oder Zugriffsschlüssel).
