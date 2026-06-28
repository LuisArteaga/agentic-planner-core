# 0001 - Drei separate Graphen statt eines monolithischen LangGraph

* **Status**: Accepted
* **Datum**: 2026-06-28
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung
Der Agentic Planner umfasst drei grundlegend verschiedene Aktivitäten: (1) interaktive PRD-Erstellung mit HITL, (2) Issue-Generierung aus Dokumenten, (3) iteratives Refinement mit Websuche und ADR-Abgleich. Ein einzelner LangGraph müsste den Zustand aller drei Phasen gleichzeitig verwalten, was zu State-Pollution führt und das Kontextfenster des LLM überlastet — ein Problem, das bereits beim Skill `grill-with-docs-and-websearch` beobachtet wurde, wo Websuchergebnisse den Kontext verdrängen und ADRs nie erstellt werden. Diese Entscheidung ist schwer umkehrbar, da die State-Schemata, Checkpointer und CLI-Schnittstellen jeder Phase grundlegend anders verdrahtet sind.

## Entscheidungsfaktoren (Drivers)
* Kontextverlust bei langem, gemischtem State (beobachtes Problem in grill-with-docs-and-websearch)
* Natürlicher zeitlicher Bruch zwischen den Phasen (verschiedene Sessions, verschiedene Tage)
* Unabhängige Optimierbarkeit und Testbarkeit jeder Phase
* Nachvollziehbarkeit in Langfuse (isolierte Traces pro Phase)

## Betrachtete Optionen
* **Option 1**: Ein monolithischer LangGraph mit interrupt()-Breakpoints zwischen den Phasen
* **Option 2**: Drei separate, kompilierte LangGraphen mit je eigenem Entrypoint und State-Schema, die über Dateien im Dateisystem kommunizieren (PRD.md, CONTEXT.md, ADRs, Draft Issues)

## Entscheidung
Option 2 — drei separate Graphen mit drei CLI-Entrypoints (z. B. `python -m planner prd`, `python -m planner split`, `python -m planner refine`). Die Kommunikation zwischen den Phasen erfolgt ausschließlich über Dateien im Ziel-Repository. Jede Phase hat ein eigenes State-Schema, einen eigenen Checkpointer und eigene Langfuse-Traces.

### Konsequenzen
* **Positiv**: Jede Phase sieht nur ihren eigenen Zustand — kein Context Rot. Phasen können unabhängig optimiert, getestet und getracet werden. Ein Neustart einer Phase erfordert keinen Reset der anderen.
* **Negativ**: Kein geteilter in-memory State zwischen Phasen. Das Dateisystem wird zum Kommunikationskanal, was ein klares Dateiformat-Kontrakt erfordert.

## Inspiration & Referenzen
* ADaPT (Prasad et al., 2024) — As-Needed Decomposition and Planning: +33% Erfolgsrate durch strikte Trennung von Planung und Ausführung
* LLMCompiler (Kim et al., 2024) — Planner-DAG + Executor-Architektur übertrifft monolithische ReAct-Loops
* Plan-Then-Execute (arxiv, 2024) — HITL-Variante mit separater Planungsphase erhöht User Trust signifikant
* LangGraph Production Best Practice — Subgraphs mit isoliertem State statt monolithischer Graphen ab mittlerer Komplexität
