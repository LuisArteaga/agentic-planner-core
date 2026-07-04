# Phase 1 & 2: Centralized LangChain deepagents Guide

This guide describes how to run the **LangChain deepagents** planning commands centrally from `agentic-planner-core` to execute Phase 1 (Interactive Design), Phase 1b (Learning Verification), and Phase 2 (Draft Issue Generation) targeting any local codebase.

By running everything from the planner core repository, the target repository remains 100% clean of `.planner/` folders, runner scripts, copied skills, and python environments.

---

## Architecture Overview

In this centralized execution model:
1. **Target Repository**: Contains only the core project files (`PRD.md`, `CONTEXT.md` glossary, and `docs/adr/` design decisions).
2. **Planner Core (`agentic-planner-core`)**: Holds the deepagents framework, prompt skills, virtual environment, and stores the intermediate draft issue files centrally under `drafts/<repo_name>/` (which is gitignored in the planner-core repo).

---

## Setup & Configuration

### 1. Define Environment Variables
Configure your terminal to point to the target repository path and repository slug:
```bash
# Absolute path to the local target repository directory
export GITHUB_WORKSPACE="/home/larteaga/projects/my-target-repo"

# The target repository slug
export GITHUB_REPOSITORY="MyGitHubOrg/my-target-repo"

# OpenRouter API Key for orchestration
export GITHUB_TOKEN="your-github-pat"  # Or export GH_PAT/GH_TOKEN
export OPENROUTER_API_KEY="your-openrouter-key"
```

---

## Execution Instructions

### Phase 1: Interactive Grilling Session (`grill`)
Run the grill session to align requirements. The agent will read `PRD.md` and `CONTEXT.md` from the target workspace and update them directly:
```bash
python -m planner grill
```
The agent uses `grill-with-docs` skill and is equipped with file read/write tools that are securely restricted within your `GITHUB_WORKSPACE` boundary.

### Phase 1b: Learning Verification (`verify`)
Verify your understanding of the architecture decisions before splitting. The agent quizzes you and writes a local log centrally to `drafts/<repo_name>/.teaching-checklist.md`:
```bash
python -m planner verify
```

### Phase 2: Draft Issue Generation (`draft`)
Decompose the finalized `PRD.md` into topologically sorted draft issue files:
```bash
python -m planner draft
```
This generates Markdown draft issues centrally in the `drafts/<repo_name>/` folder of `agentic-planner-core`. The naming convention uses a 4-digit sequential prefix (e.g. `0001-setup.md`, `0002-implement-auth.md`).

---

## Path Traversal Security
To protect your local filesystem, all file reading/writing tools check that resolved paths remain strictly within the `GITHUB_WORKSPACE` boundary. Path traversal attempts (such as using `../` segments) will throw a PermissionError:
```python
# Contained path resolving check used in tools
target_file = (workspace_root / relative_path).resolve()
try:
    target_file.relative_to(workspace_root)
except ValueError:
    raise PermissionError("Access denied: path is outside GITHUB_WORKSPACE.")
```
Similarly, draft issue saving is constrained to the `agentic-planner-core/drafts/<repo_name>/` folder.

---

## Next Steps: Refinement (Phase 3)
Once draft issues are created under `drafts/<repo_name>/`, you can run the refinement subgraph directly:
```bash
python -m planner refine --config config/sources.yaml
```
This will read the draft issues, run deep-search validations, and publish them as official GitHub issues on the target repository.
