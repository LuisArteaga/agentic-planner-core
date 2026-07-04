# Agentic Planner Core

**agentic-planner-core** is an autonomous planning and issue refinement orchestrator. It bridges the gap between high-level project goals and well-defined, researched, ADR-compliant GitHub issues.

By separating the planning and refinement phases, it prevents context rot and isolates web searches to short-lived single-issue workflows.

---

## Workflow Overview

The system operates in three distinct phases:

### Phase 1: Interactive Design
Uses **LangChain deepagents** in Python with the `grill-with-docs` skill. The agent interviews the developer to create/refine `PRD.md`, `CONTEXT.md` (Domain Glossary), and initial `docs/adr/` (Architecture Decision Records) directly in the target repository.

### Phase 2: Draft Issue Generation
The `draft-issues` skill splits the `PRD.md` requirements into topologically sorted, tracer-bullet vertical slice files called **Draft Issues** (saved under `.planner/drafts/<repo_name>/####-slug.md`).

### Phase 3: Autonomous Refinement & Publish
Triggered via `python -m planner refine`. A master LangGraph orchestrator iterates over all Draft Issues, executing isolated refinement subgraphs to perform targeted searches, grade technical solutions against ADRs, and publish them to GitHub as official `agent-ready` issues.

---

## Setup Guide

### 1. Requirements
* Python `>= 3.12` (locked via `.python-version`)
* A target repository to plan.
* An OpenRouter API Key (for LLM orchestration) and a GitHub Personal Access Token (for publishing).

### 2. Bootstrapping a Target Repository
To prepare a target repository to work with the planner:
```bash
./scripts/setup-deepagents.sh /path/to/target-repository
```
This script:
- Creates the local `.planner/` structure and copies the prompt skills (`draft-issues`, `grill-with-docs`, `wise-teacher`).
- Configures `.gitignore` to ignore local planner config and environments.
- Generates a template python runner at `.planner/run_planner.py`.
- Sets up a virtual environment (`.venv`) and installs LangChain/OpenRouter dependencies.

### 3. Detailed Integration Guide
For a full walkthrough of setting up and running Phase 1 and 2 with deepagents, see [docs/guides/phase1-deepagents.md](./docs/guides/phase1-deepagents.md).

---

## Autonomous Refinement (Phase 3)

Once Draft Issues are populated, run the refinement orchestrator from the `agentic-planner-core` directory:

1. Copy the example source config:
   ```bash
   cp config/sources.example.yaml config/sources.yaml
   ```
2. Configure your allowed domains/repositories in `config/sources.yaml`.
3. Set your environment variables:
   ```bash
   export OPENROUTER_API_KEY="your-key"
   export GH_PAT="your-github-token"
   export GITHUB_REPOSITORY="owner/target-repo"
   export GITHUB_WORKSPACE="/path/to/target-repo"
   ```
4. Run the master loop:
   ```bash
   python -m planner refine
   ```

---

## Quality Assurance & Development

Run checks locally:
```bash
make verify
```
This runs style checking, linting via `ruff`, and pytest tests.