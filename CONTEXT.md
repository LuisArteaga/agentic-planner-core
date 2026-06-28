# Domain Glossary

Dieses Dokument definiert die fachliche Terminologie für diesen Kontext. Es darf keine technischen Implementierungsdetails (wie Datenbanken, Klassen oder Frameworks) enthalten.

## Begriffe

### Agentic Planner
* **Definition**: Der end-to-end Prozess, der ein vages Vorhaben in fertige, recherchierte, ADR-konforme GitHub Issues überführt. Der Prozess endet mit der Veröffentlichung des Issues im Ziel-Repository — die Ausführung (Code schreiben, Tests, PRs) liegt außerhalb des Scope.
* **Geschäftsregeln**: Der Planner erzeugt Issues mit dem Label `agent-ready`, die direkt von einem Execution-System (z. B. agentic-developer-core) konsumiert werden können.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit dem *Autonomous Developer Loop*, der Issues ausführt.

### Target Repository
* **Definition**: Das fremde GitHub-Repository, für das der Planner Artefakte erzeugt (PRD.md, CONTEXT.md, ADRs, Draft Issues) und auf dem er Issues veröffentlicht. Der Planner schreibt lokal in das Verzeichnis `GITHUB_WORKSPACE` und interagiert remote über die GitHub API mit `GITHUB_REPOSITORY` (Slug im Format `owner/repo`).
* **Geschäftsregeln**: Alle erzeugten Planungsartefakte gehören dem Target Repository, nicht dem Planner. Der Planner selbst enthält nur seinen eigenen Code und seine Konfiguration.
* **Synonyme / Abzugrenzende Begriffe**: Identisch mit der Terminologie in agentic-developer-core. Nicht zu verwechseln mit dem Repository, in dem der Planner-Code selbst lebt.

### Draft Issue
* **Definition**: Eine lokale Markdown-Datei im Verzeichnis `.planner/drafts/<repo_name>/` des Target Repository, die ein einzelnes, granulares GitHub Issue beschreibt, bevor es veröffentlicht wird. Draft Issues sind temporär und werden per `.gitignore` vom Versionskontrollsystem ausgeschlossen. Der Unterordner `<repo_name>` ermöglicht die parallele Planung für mehrere Target Repositories.
* **Geschäftsregeln**: Ein Draft Issue durchläuft den Refinement-Prozess (Websuche, ADR-Abgleich, Umschreiben) bevor es als GitHub Issue veröffentlicht wird. Nach erfolgreicher Veröffentlichung kann es gelöscht werden.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit einem veröffentlichten GitHub Issue. Ein Draft Issue existiert ausschließlich lokal.

### Refinement Subgraph
* **Definition**: Ein isolierter LangGraph-Subgraph, der für ein einzelnes Draft Issue aufgerufen wird. Er durchläuft die Schritte Quellenanalyse, Websuche, Optionsgenerierung, Bewertung und Anwendung. Der Subgraph besitzt einen eigenen, vom Parent-Graph isolierten State, damit Websuchergebnisse den Kontext anderer Issues nicht beeinflussen.
* **Geschäftsregeln**: Pro Draft Issue wird genau ein Refinement Subgraph ausgeführt. Der Subgraph gibt als Ergebnis das verfeinerte Issue-Markdown und ggf. Pfade zu neu erstellten ADRs an den Parent-Graph zurück.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit dem übergeordneten Refinement Graph, der die Iteration über alle Draft Issues steuert.

### Solution Grading
* **Definition**: Die Bewertung von Lösungsansätzen innerhalb eines Refinement Subgraph durch einen separaten LLM-Call (Critic), der unabhängig vom generierenden LLM-Call (Generator) arbeitet. Der Critic bewertet jede Option anhand einer festen Rubrik gegen bestehende ADRs und gibt ein strukturiertes Ergebnis zurück (Wahl, Score, Begründung).
* **Geschäftsregeln**: Der Critic-Call kann ein anderes Modell verwenden als der Generator. Alle Bewertungsergebnisse werden in Langfuse geloggt, um nachvollziehbar zu machen, welche Optionen existierten und warum eine gewählt wurde.
* **Synonyme / Abzugrenzende Begriffe**: Folgt dem Generator-Critic-Pattern (auch LLM-as-Judge genannt). Nicht zu verwechseln mit HITL-Review — Solution Grading ist vollautomatisch.

### Draft Issues Skill
* **Definition**: Ein CLI-Harness-Skill, der ein PRD in granulare Draft Issues als lokale Markdown-Dateien zerlegt, analog zum bestehenden `create-issues` Skill. Er nutzt Tracer-Bullet Vertical Slices und enthält einen HITL-Feedback-Loop zur Granularitätsabstimmung. Im Gegensatz zu `create-issues` publiziert er nicht auf GitHub, sondern schreibt die Issues nach `.planner/drafts/<repo_name>/`.
* **Geschäftsregeln**: Der Skill wird über ein CLI-Harness (Aider/OpenCode) ausgeführt, nicht als LangGraph-Knoten. Das Issue-Template muss identisch sein mit dem, das der Refinement Subgraph und die spätere GitHub-Veröffentlichung erwarten.
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit `create-issues`, der direkt auf den GitHub Issue Tracker publiziert.

### Source Configuration
* **Definition**: Eine Konfigurationsdatei, die vertrauenswürdige Quellen (GitHub Repositories, Domains wie arxiv.org) und Basis-Keywords für die Websuche im Refinement Subgraph definiert. Enthält einen `strict`-Toggle: im Default-Modus erweitert der Subgraph die Liste dynamisch, im Strict-Modus werden ausschließlich die konfigurierten Quellen durchsucht.
* **Geschäftsregeln**: Im Strict-Modus werden keine dynamisch vom LLM generierten Quellen oder Domains akzeptiert — nur Keywords werden dynamisch erzeugt. Dies schützt gegen Prompt Injection über unkontrollierte Websuchergebnisse (siehe ADR-0002).
* **Synonyme / Abzugrenzende Begriffe**: Nicht zu verwechseln mit der allgemeinen Planner-Konfiguration (LLM-Modell, API-Keys etc.).
