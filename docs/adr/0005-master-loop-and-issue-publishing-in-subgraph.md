# 0005 - Master Loop and Issue Publishing inside Refinement Subgraph

* **Status**: Accepted
* **Datum**: 2026-07-03
* **Entscheidungsträger**: Luis Arteaga / Antigravity

## Kontext und Problemstellung
Mit der Implementierung des Master-Loops (`python -m planner refine`) und des GitHub Issue Publishers stellt sich die Frage, wo der Knoten für das Veröffentlichen (`publish_issue`) ausgeführt wird. Soll dieser Teil des Refinement-Subgraphen sein oder als separater Schritt im Master-Graphen erfolgen? 

Diese Entscheidung hat Auswirkungen auf das State-Schema von Master-Graph und Subgraph sowie auf die Fehlertoleranz und Kapselung der einzelnen Arbeitsschritte.

## Entscheidungsfaktoren (Drivers)
* **Kapselung & Isolation**: Der Lebenszyklus eines einzelnen Entwurfs-Issues (Recherche, Bewertung, Entscheidung, Upload, Löschen der Arbeitskopie) sollte möglichst in sich geschlossen sein.
* **Fehlertoleranz (Robustheit)**: Ein Ausfall (z. B. Rate Limiting oder LLM-Strukturfehler) bei einem einzelnen Issue darf nicht den gesamten Batch-Lauf abbrechen.
* **Architektur-Konformität (ADR-0001)**: Der Master-Graph soll sauber gehalten werden und sich primär auf die Schleifensteuerung konzentrieren.

## Betrachtete Optionen

### Option 1: Platzierung von `publish_issue` als letzter Knoten im Refinement Subgraph (Gewählt)
* **Vorteil**:
  * Jedes Draft-Issue durchläuft seinen kompletten Lebenszyklus am Stück isoliert im Subgraphen.
  * Das Fehlermanagement ist extrem robust: Der Master-Graph umschließt den gesamten Subgraph-Aufruf mit einem `try-except`, fängt jegliche Fehler (Recherche, LLM-Grading, API-Schreibfehler beim Veröffentlichen) ab und setzt die Schleife fort.
  * Der Master-Graph bleibt frei von Detail-Wissen über die GitHub-API.
* **Nachteil**:
  * Das Subgraph-State-Schema muss Felder für die Veröffentlichung verwalten (wie `draft_issue_path` zur Bereinigung der Datei nach dem Upload).

### Option 2: Ausführung von `publish_issue` im Master-Graphen nach dem Subgraphen
* **Vorteil**:
  * Strikte Trennung von rein lesendem/denkendem Refinement (im Subgraph) und schreibender GitHub-API-Aktion (im Master-Graph).
* **Nachteil**:
  * Komplexerer Datentransfer: Der Subgraph müsste die finalen verfeinerten Issue-Inhalte an den Master-Graphen zurückgeben, welcher diese akkumulieren und hochladen muss.
  * Erhöhte Komplexität der Fehlerbehandlung und des State-Managements im Master-Graphen.

## Entscheidung
Wir wählen **Option 1**. Die vollständige Kapselung des Issue-Lebenszyklus im Refinement-Subgraphen in Kombination mit einem einfachen, fehlerisolierten Master-Loop erfüllt unsere Design-Ziele (insbesondere Robustheit und Einhaltung von ADR-0001) am besten.

### Konsequenzen
* **Positiv**: Maximale Ausfallsicherheit durch Try-Except-Isolation auf Subgraph-Ebene im Master-Loop. Der Master-Graph bleibt schlank und wartbar.
* **Negativ**: Der Subgraph benötigt Zugriff auf Dateipfade der Arbeitskopien zur Bereinigung.
