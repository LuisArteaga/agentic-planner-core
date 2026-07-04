# Agentic Planner Core

**agentic-planner-core** is an autonomous planning and issue refinement orchestrator. It bridges the gap between high-level project goals and well-defined, researched, ADR-compliant GitHub issues.

By separating the planning and refinement phases, it prevents context rot and isolates web searches to short-lived single-issue workflows.

---

## Workflow Overview

The system operates in three distinct phases, all executed centrally from the `agentic-planner-core` project:

### Phase 1: Interactive Design
Uses **LangChain deepagents** in Python with the `grill-with-docs` skill. The agent interviews the developer to create/refine `PRD.md`, `CONTEXT.md` (Domain Glossary), and initial `docs/adr/` (Architecture Decision Records) directly in the target repository.

### Phase 1b: Learning Verification
Uses the `wise-teacher` skill to perform an interactive learning session with the developer to confirm deep understanding of the problem, design decisions, and wider context, saving a checklist log centrally to `drafts/<repo_name>/.teaching-checklist.md`.

### Phase 2: Draft Issue Generation
The `draft-issues` skill splits the `PRD.md` requirements into topologically sorted, tracer-bullet vertical slice files called **Draft Issues** (saved centrally under `drafts/<repo_name>/####-slug.md`).

### Phase 3: Autonomous Refinement & Publish
A master LangGraph orchestrator iterates over all Draft Issues, executing isolated refinement subgraphs to perform targeted searches, grade technical solutions against ADRs, and publish them to GitHub as official `agent-ready` issues.

---

## Setup & Configuration

### 1. Requirements
* Python `>= 3.12` (locked via `.python-version`)
* A target repository to plan (where `PRD.md`, `CONTEXT.md`, and `docs/adr/` will live).
* An OpenRouter API Key (for LLM orchestration) and a GitHub Personal Access Token (for publishing).

### 2. Install Dependencies
Run from the `agentic-planner-core` root directory:
```bash
uv pip install -e ".[dev]"
```

### 3. Environment Variables
Export these environment variables to configure the target repository:
```bash
export OPENROUTER_API_KEY="your-openrouter-key"
export GH_PAT="your-github-token"
export GITHUB_REPOSITORY="owner/target-repo"
export GITHUB_WORKSPACE="/absolute/path/to/target-repo"
```

---

## Execution Guide

### Phase 1: Grilling Session
Start the interactive interview to align requirements and generate/update PRD, Glossary, and ADRs in the target repo:
```bash
python -m planner grill
```
*(Grill agent will modify files directly in your target repository path specified by `GITHUB_WORKSPACE`)*.

### Phase 1b: Learning Verification
Verify understanding and log the checklist centrally:
```bash
python -m planner verify
```

### Phase 2: Draft Issue Generation
Decompose the requirements into topologically sorted draft issue files:
```bash
python -m planner draft
```
*(Generates issue files centrally under `drafts/<repo_name>/`)*.

### Phase 3: Autonomous Refinement & Publishing
Before running refinement, configure your search sources:
```bash
cp config/sources.example.yaml config/sources.yaml
```
Define your allowed search domains/repositories in `config/sources.yaml`. Then run refinement:
```bash
python -m planner refine
```
*(Refines the issues, checks grades against ADRs, and publishes them as issues to GitHub)*.

---

## Quality Assurance & Development

Run checks locally:
```bash
make verify
```
This runs style checking, linting via `ruff`, and pytest tests.