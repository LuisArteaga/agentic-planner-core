# 0001 - Separate Phasen statt eines monolithischen LangGraph

* **Status**: Accepted
* **Datum**: 2026-06-28
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung
Der Agentic Planner umfasst vier grundlegend verschiedene Aktivitäten: (1) interaktive PRD-Erstellung (grill), (1b) Lernprüfung (verify), (2) Issue-Generierung (draft), (3) iteratives Refinement (refine). Ein monolithischer Agenten-Steuerungsloop müsste den Zustand aller Phasen gleichzeitig verwalten, was zu State-Pollution führt und das Kontextfenster überlastet. Diese Entscheidung ist schwer umkehrbar, da die CLI-Schnittstellen und Ausführungsmodelle jeder Phase grundlegend anders verdrahtet sind.

## Entscheidungsfaktoren (Drivers)
* Kontextverlust bei langem, gemischtem State (beobachtes Problem in grill-with-docs-and-websearch)
* Natürlicher zeitlicher Bruch zwischen den Phasen (verschiedene Sessions, verschiedene Tage)
* Unabhängige Optimierbarkeit und Testbarkeit jeder Phase
* Nachvollziehbarkeit in Langfuse (isolierte Traces pro Phase)

## Betrachtete Optionen
* **Option 1**: Ein monolithischer LangGraph mit interrupt()-Breakpoints zwischen den Phasen
* **Option 2**: Separate Phasen mit je eigenem Entrypoint, die über Dateien im Dateisystem kommunizieren (PRD.md, CONTEXT.md, ADRs im Ziel-Repository; Draft Issues und Lernprüfungs-Logs zentralisiert im `.planner/drafts/` Verzeichnis des Planner-Cores)

## Entscheidung
Option 2 — vier separate Phasen mit vier CLI-Entrypoints (`grill`, `verify`, `draft`, `refine`). 
- Die interaktiven Planungsphasen 1, 1b und 2 (`python -m planner grill`, `python -m planner verify`, `python -m planner draft`) werden als eigenständige LangChain `deepagents`-Sessions im Planner-Core ausgeführt.
- Die autonome Verfeinerungsphase 3 (`python -m planner refine`) wird über einen kompilierten LangGraph-Orchestrator ausgeführt.
Die Kommunikation erfolgt entkoppelt über Dateien (PRD, Glossary, ADRs im Ziel-Repository; Draft Issues und Checklist-Logs unter `.planner/drafts/` im Planner-Core). Jede Phase hat isolierte Ausführungspfade und Traces.

### Konsequenzen
* **Positiv**: Jede Phase sieht nur ihren eigenen Zustand — kein Context Rot. Phasen können unabhängig optimiert, getestet und getracet werden. Ein Neustart einer Phase erfordert keinen Reset der anderen. Ziel-Repositories bleiben von Konfigurations- und Planungsdateien vollständig befreit.
* **Negativ**: Kein geteilter in-memory State zwischen Phasen. Das Dateisystem wird zum Kommunikationskanal, was ein klares Dateiformat-Kontrakt erfordert.

## Inspiration & Referenzen
* ADaPT (Prasad et al., 2024) — As-Needed Decomposition and Planning: +33% Erfolgsrate durch strikte Trennung von Planung und Ausführung
* LLMCompiler (Kim et al., 2024) — Planner-DAG + Executor-Architektur übertrifft monolithische ReAct-Loops
* Plan-Then-Execute (arxiv, 2024) — HITL-Variante mit separater Planungsphase erhöht User Trust signifikant
* LangGraph Production Best Practice — Subgraphs mit isoliertem State statt monolithischer Graphen ab mittlerer Komplexität
