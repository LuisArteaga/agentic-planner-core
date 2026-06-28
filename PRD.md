# Product Requirement Document (PRD) — Agentic Planner Core

This document specifies the architecture and requirements for **agentic-planner-core**, an autonomous planning and issue refinement orchestrator. It bridges the gap between high-level project goals and well-defined, researched, ADR-compliant GitHub issues.

---

## 1. Objective & High-Level Summary

The goal of **agentic-planner-core** is to automate the upstream phase of software development:
1. **Interactive Design**: Guide humans in generating robust PRDs, Glossaries (`CONTEXT.md`), and Architecture Decision Records (ADRs) using existing CLI harnesses (Aider or OpenCode) and custom skills.
2. **Issue Splitting**: Decompose the PRD and constraints into local, granular, temporary Markdown files (**Draft Issues**).
3. **Autonomous Refinement**: Execute a LangGraph orchestrator that iterates over each Draft Issue, performs targeted web/GitHub searches, evaluates solutions against existing ADRs, proposes/generates new ADRs if necessary, rewrites the draft issue markdown, and publishes them to the target GitHub repository.

By separating this planning phase from code execution:
* **Context Preservation**: Avoids "context rot" by isolating web search results into short-lived, single-issue LangGraph subgraphs.
* **Separation of Concerns**: Planning-time dependencies and telemetry (Langfuse) remain decoupled from execution-time sandboxing constraints.

---

## 2. Architectural Decisions & Phases

### Phase 1: Interactive PRD/ADR Guide
* **No Code**: Instead of building a custom chat CLI, Phase 1 uses **Aider** or **OpenCode** with the `grill-with-docs` skill.
* **PRD Template**: The planner repository provides a standard PRD template that the human and CLI harness populate during their design session.
* **Outputs**: `PRD.md`, `CONTEXT.md` (Domain Glossary), and initial ADRs (written directly into the target project's `GITHUB_WORKSPACE`).

### Phase 2: Draft Issue Generation
* **Skill-Driven**: Executed via the CLI harness using a new `draft-issues` skill.
* **Granular Decomposition**: Splitting follows **tracer-bullet vertical slices** (narrow, end-to-end verifiable paths) and resolves dependencies.
* **Output Location**: Writes draft issues to `.planner/drafts/<repo_name>/` (added to `.gitignore` of the target project) in Markdown format following the standard issue template.

### Phase 3: LangGraph Refinement & Publish
* **Execution**: Triggered via `python -m planner refine`.
* **State Isolation**: A master graph loads the target repository's current state and iterates over all local Draft Issues. Each issue is processed inside an isolated **Refinement Subgraph** to keep web search context from leaking.
* **Web Search**: Uses OpenRouter's server-side tool calling `openrouter:web_search` with strict domain restrictions (`allowed_domains`). Native model-level search grounding is disabled to prevent conflicts and errors.
* **Solution Grading**: Employs a **Generator-Critic** pattern. The generator lists design options. A separate LLM-as-a-Judge (Critic) evaluates options against a local `config/grading_rubric.md` and existing ADRs, outputting structured Pydantic grades.
* **ADR & Issue Writing**: If the chosen solution demands a hard-to-reverse design shift, the orchestrator writes a new ADR. It then rewrites the Draft Issue to incorporate search findings, Pydantic grades, and ADR links.
* **Publishing**: Automatically creates the issue on the target GitHub repository (specified by `GITHUB_REPOSITORY`) with the `agent-ready` label.

---

## 3. Component Breakdown

```
agentic-planner-core/
├── CONTEXT.md                          # Glossary of the planner tool
├── PRD.md                              # This document
├── README.md
├── docs/
│   └── adr/                            # Architecture Decision Records
│       ├── 0001-drei-separate-graphen.md
│       └── 0002-strict-modus-quelleneinschraenkung.md
├── docs/guides/
│   ├── phase1-aider.md                 # Setup guide for Aider
│   └── phase1-opencode.md              # Setup guide for OpenCode
├── scripts/
│   ├── setup-aider.sh                  # Setup script for Aider skills
│   ├── setup-opencode.sh               # Setup script for OpenCode skills
│   └── telemetry.py                    # Custom OTel tracing module
├── config/
│   ├── grading_rubric.md               # Critic grading criteria
│   └── sources.example.yaml            # Config structure for web search
├── skills/
│   └── draft-issues/
│       └── SKILL.md                    # Prompt skill for splitting PRDs
├── planner/
│   ├── __init__.py
│   ├── __main__.py                     # Entrypoint (refine command)
│   ├── refine_graph.py                 # Master and Subgraph compilation
│   ├── state.py                        # TypedDict states for graphs
│   ├── nodes/                          # Isolated node logic functions
│   │   ├── analyze_sources.py
│   │   ├── web_search.py
│   │   ├── propose_options.py
│   │   ├── evaluate_grade.py
│   │   ├── apply_decision.py
│   │   └── publish_issue.py
│   └── tools/                          # Exposes search and git tools
│       ├── github_api.py
│       └── search.py
├── .env.example
├── pyproject.toml
└── .gitignore
```

---

## 4. Configuration & Telemetry

### Telemetry (Langfuse via OTLP)
* Fully adopts the OpenTelemetry (OTel) instrumentation framework implemented in `agentic-developer-core`.
* Registers the OTel TracerProvider. Spans are created natively for the `refinement_loop` and each active node (`analyze_sources`, `web_search`, `evaluate_grade`, etc.).
* Exporting is routed to Langfuse via OTLP integration using the standard `OTEL_EXPORTER_OTLP_ENDPOINT`.
* Traces are logged locally to `.agent_logs/otel_traces_<date>.jsonl` for crash resilience, exporting at the end of execution.

### Search & Strict Mode Configuration
Configuration resides in a local `sources.yaml` file (copied from `sources.example.yaml`):
```yaml
strict: true                      # Force search to ONLY use allowed domains
repositories:
  - langchain-ai/langgraph
  - SWE-agent/SWE-agent
domains:
  - arxiv.org
  - dl.acm.org
```

---

## 5. Acceptance Criteria

* **AC1. Separation of Concerns**: The tool does not perform code execution or testing on the target repository. It only generates, refines, and publishes issues and ADRs.
* **AC2. Subgraph Isolation**: Each Draft Issue's web search history and grading details are contained within its own Subgraph execution state, avoiding token limits and prompt decay in the parent loop.
* **AC3. Strict Search Enforcement**: When `strict: true` is configured, searches only target predefined domains and repositories.
* **AC4. Generator-Critic Grading**: Solutions are generated and graded using Pydantic schemas via a distinct Critic LLM prompt against the grading rubric and existing ADRs.
* **AC5. OpenTelemetry Logging**: Spans are recorded natively and are compatible with Langfuse's OTLP ingestion, logging to local JSONL files on failure.
* **AC6. Standard Template Match**: Outputs match the predefined issue template syntax required by the execution agent.
