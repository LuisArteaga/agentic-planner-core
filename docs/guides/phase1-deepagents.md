# Phase 1: LangChain deepagents Setup & Usage Guide

This guide describes how to integrate and run the **LangChain deepagents** framework to execute Phase 1 (Interactive Design) and Phase 2 (Draft Issue Generation) of the Agentic Planner workflow.

## Overview

In the Agentic Planner workflow, the planning phase is executed using a planning agent. For developers using Python, this is built on LangChain's `deepagents` harness.

The planning agent performs two primary roles:
1. **Interactive Design**: Collaborates with the human to write and refine the `PRD.md`, `CONTEXT.md` (Domain Glossary), and initial `docs/adr/` (Architecture Decision Records) in the target repository.
2. **Issue Splitting**: Reads the finalized `PRD.md` and context, applies the `draft-issues` skill, and outputs topologically sorted Draft Issues to `.planner/drafts/<repo_name>/`.

---

## Bootstrapping a Target Repository

To configure a new or existing target repository to work with `deepagents` and the `draft-issues` skill, run the setup script from the root of `agentic-planner-core`:

```bash
./scripts/setup-deepagents.sh /path/to/target-repository
```

### What the Setup Script Does:
1. Creates the `.python-version` file specifying the Python version (matching `agentic-planner-core`).
2. Configures `.gitignore` in the target repository to exclude the `.planner/` folder, `.env`, and `.venv`.
3. Copies the `draft-issues`, `grill-with-docs`, and `wise-teacher` skills into `.planner/skills/` inside the target repository.
4. Generates a template python runner script at `.planner/run_planner.py`.
5. Creates a local Python virtual environment (`.venv`) and installs `langchain-openai` and `langchain-core`.

---

## Runner Script Configuration (`.planner/run_planner.py`)

The generated `.planner/run_planner.py` script initializes the `deepagents` planner. It uses the `ChatOpenAI` class configured for OpenRouter.

### Critical OpenRouter Configuration

> [!IMPORTANT]
> When pointing `ChatOpenAI` to OpenRouter's API endpoint, you **must** set `use_responses_api=False` (or pass it via `model_kwargs` or constructor parameters depending on the package version). If this is not set, OpenRouter will fail with a `404/500` error because it does not support the OpenAI Responses API endpoint.

Example initialization from `.planner/run_planner.py`:

```python
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# 1. Initialize the LLM with OpenRouter and Responses API disabled
model_name = os.getenv("AGENT_MODEL", "google/gemini-2.5-flash")
llm = ChatOpenAI(
    model=model_name,
    temperature=0.0,
    openai_api_base="https://openrouter.ai/api/v1",
    openai_api_key=os.getenv("OPENROUTER_API_KEY"),
    use_responses_api=False  # CRITICAL for OpenRouter compatibility
)

# 2. Load the draft-issues skill prompt
skill_path = os.path.join(os.path.dirname(__file__), "skills", "draft-issues", "SKILL.md")
with open(skill_path, "r", encoding="utf-8") as f:
    draft_issues_prompt = f.read()

# 3. Bind tools and run the planning agent
model_with_tools = llm.bind_tools([save_draft_issue])
response = model_with_tools.invoke([
    SystemMessage(content=draft_issues_prompt),
    HumanMessage(content="Please split the PRD.")
])
```

---

## Using the `grill-with-docs` Skill (Interactive Design)

Before running the issue splitting (`draft-issues`), you can use the `grill-with-docs` skill in an interactive planning session to align on requirements, update the domain glossary (`CONTEXT.md`), and document architecture choices (`docs/adr/`).

To use the grilling skill in a custom deepagents setup, load the prompt from `.planner/skills/grill-with-docs/SKILL.md`:

```python
# Load the grill-with-docs skill
grill_skill_path = os.path.join(os.path.dirname(__file__), "skills", "grill-with-docs", "SKILL.md")
with open(grill_skill_path, "r", encoding="utf-8") as f:
    grill_prompt = f.read()

# Initialize planning model with the grill system prompt and file editing tools
model_with_tools = llm.bind_tools([edit_file])
response = model_with_tools.invoke([
    SystemMessage(content=grill_prompt),
    HumanMessage(content="Let's start the design session.")
])
```

---

## Using the `wise-teacher` Skill (Learning Verification)

After aligning on the requirements via `grill-with-docs`, you can run the `wise-teacher` skill as a learning verification phase (Phase 1b). The agent will review the changes in `CONTEXT.md` and `PRD.md` with the developer, run interactive quizzes (using `ask_question`), and populate a local `.teaching-checklist.md` log file to verify that the developer has a thorough understanding of the architecture decisions before proceeding to issue splitting.

To use the wise-teacher skill, load it in the runner:

```python
# Load the wise-teacher skill
teacher_skill_path = os.path.join(os.path.dirname(__file__), "skills", "wise-teacher", "SKILL.md")
with open(teacher_skill_path, "r", encoding="utf-8") as f:
    teacher_prompt = f.read()

# Initialize planning model with the wise-teacher system prompt and interactive tools
model_with_tools = llm.bind_tools([ask_question])
response = model_with_tools.invoke([
    SystemMessage(content=teacher_prompt),
    HumanMessage(content="Please start the review session and verify my understanding.")
])
```

---

## Running the Planning Agent

1. Navigate to your target repository:
   ```bash
   cd /path/to/target-repository
   ```
2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```
3. Export your API keys:
   ```bash
   export OPENROUTER_API_KEY="your-key-here"
   ```
4. Execute the planner runner:
   ```bash
   python .planner/run_planner.py
   ```

The agent will read the `PRD.md`, perform planning, and generate the draft issue files in `.planner/drafts/<repo_name>/` using the topological sequential naming convention (e.g. `0001-setup.md`, `0002-feature.md`).

Once the files are created, you can run Phase 3 from `agentic-planner-core` to refine and publish them:
```bash
python -m planner refine --config config/sources.yaml
```

---

## Troubleshooting

### Error: `404 Not Found` or `Unsupported endpoint`
This happens if `use_responses_api=False` is missing. Ensure the `ChatOpenAI` constructor contains `use_responses_api=False`.

### Setup Script Permission Errors
If the setup script fails due to permission errors (e.g., read-only filesystem or target folder write restrictions), verify that:
1. Your user has write permissions to the target repository directory.
2. You run the setup script with appropriate privileges.
