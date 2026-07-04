#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# Get the directory of the setup script and resolve the root of agentic-planner-core
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLANNER_CORE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Target directory defaults to current working directory
TARGET_DIR="${1:-.}"
TARGET_DIR_ABS="$(cd "$TARGET_DIR" && pwd)"

echo "=== Bootstrapping LangChain deepagents in Target Repository ==="
echo "Target Repository Path: $TARGET_DIR_ABS"

# 1. Verify that target directory exists and is writable
if [ ! -d "$TARGET_DIR_ABS" ]; then
    echo "Error: Target directory '$TARGET_DIR_ABS' does not exist." >&2
    exit 1
fi

if [ ! -w "$TARGET_DIR_ABS" ]; then
    echo "Error: Target directory '$TARGET_DIR_ABS' is not writable." >&2
    exit 1
fi

# 2. Add python version file to Target Repo (matching core repo)
PYTHON_VERSION_FILE="$PLANNER_CORE_ROOT/.python-version"
TARGET_PYTHON_VERSION_FILE="$TARGET_DIR_ABS/.python-version"

if [ -f "$PYTHON_VERSION_FILE" ]; then
    cp "$PYTHON_VERSION_FILE" "$TARGET_PYTHON_VERSION_FILE"
    echo "Created .python-version file."
else
    echo "3.12" > "$TARGET_PYTHON_VERSION_FILE"
    echo "Created default .python-version file (3.12)."
fi

# 3. Create .planner structure in target repository
PLANNER_DIR="$TARGET_DIR_ABS/.planner"
DRAFTS_DIR="$PLANNER_DIR/drafts"
SKILLS_TARGET_DIR="$PLANNER_DIR/skills"

mkdir -p "$DRAFTS_DIR"
mkdir -p "$SKILLS_TARGET_DIR"

# Copy the skills directories
cp -r "$PLANNER_CORE_ROOT/skills/draft-issues" "$SKILLS_TARGET_DIR/"
echo "Copied draft-issues skill directory to target .planner directory."
cp -r "$PLANNER_CORE_ROOT/skills/grill-with-docs" "$SKILLS_TARGET_DIR/"
echo "Copied grill-with-docs skill directory to target .planner directory."
cp -r "$PLANNER_CORE_ROOT/skills/wise-teacher" "$SKILLS_TARGET_DIR/"
echo "Copied wise-teacher skill directory to target .planner directory."

# 4. Append to target .gitignore
GITIGNORE="$TARGET_DIR_ABS/.gitignore"
touch "$GITIGNORE"

for entry in ".planner/" ".venv/" ".env"; do
    if ! grep -qxF "$entry" "$GITIGNORE"; then
        echo "$entry" >> "$GITIGNORE"
        echo "Added $entry to .gitignore."
    fi
done

# 5. Create the runner script template at .planner/run_planner.py
RUNNER_SCRIPT="$PLANNER_DIR/run_planner.py"
cat << 'EOF' > "$RUNNER_SCRIPT"
import os
import sys
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from deepagents import create_deep_agent

# 1. Retrieve the target repository name for draft issue subdirectory
# We fetch it from environment variable or fall back to directory name
repo_name = os.getenv("GITHUB_REPOSITORY")
if not repo_name:
    # Use parent directory's name
    repo_name = Path(__file__).resolve().parents[1].name

print(f"Target Repository Name: {repo_name}")

# 2. Check for required OpenRouter API key
api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    print("Error: OPENROUTER_API_KEY environment variable is not set.", file=sys.stderr)
    sys.exit(1)

# 3. Verify that PRD.md exists in target repository root
workspace_root = Path(__file__).resolve().parents[1]
prd_path = workspace_root / "PRD.md"
context_path = workspace_root / "CONTEXT.md"

if not prd_path.exists():
    print(f"Error: PRD.md not found at {prd_path}.", file=sys.stderr)
    print("Please create a PRD.md before running the planning agent.", file=sys.stderr)
    sys.exit(1)

with open(prd_path, "r", encoding="utf-8") as f:
    prd_content = f.read()

context_content = ""
if context_path.exists():
    with open(context_path, "r", encoding="utf-8") as f:
        context_content = f.read()

# 4. Load the draft-issues skill prompt
skill_path = Path(__file__).resolve().parent / "skills" / "draft-issues" / "SKILL.md"
if not skill_path.exists():
    print(f"Error: Skill file not found at {skill_path}.", file=sys.stderr)
    sys.exit(1)

with open(skill_path, "r", encoding="utf-8") as f:
    draft_issues_prompt = f.read()

# 5. Define local tool to write draft issues to disk
@tool
def save_draft_issue(filename: str, markdown_content: str) -> str:
    """Save a generated draft issue markdown file.
    
    The filename must follow the format '####-slug.md' (e.g., '0001-setup-db.md') topologically sorted.
    """
    drafts_base = Path(__file__).resolve().parent / "drafts" / repo_name
    drafts_base.mkdir(parents=True, exist_ok=True)
    
    # Path traversal protection (ADR-0004/0005 compliant containment check)
    target_file = (drafts_base / filename).resolve()
    try:
        target_file.relative_to(drafts_base.resolve())
    except ValueError:
        return "Error: File path traversal detected. Access denied to write outside drafts directory."
        
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        return f"Successfully saved draft issue to {target_file.name}"
    except Exception as e:
        return f"Failed to save draft issue: {e}"

# 6. Initialize ChatOpenAI configured for OpenRouter
# CRITICAL: We pass use_responses_api=False to avoid 404/500 errors on OpenRouter
model_name = os.getenv("AGENT_MODEL", "google/gemini-2.5-flash")
print(f"Initializing model {model_name}...")
llm = ChatOpenAI(
    model=model_name,
    temperature=0.0,
    openai_api_base="https://openrouter.ai/api/v1",
    openai_api_key=api_key,
    use_responses_api=False  # CRITICAL: OpenRouter compatibility flag
)

# 7. Create deepagents planner
print("Initializing deepagents planner...")
agent = create_deep_agent(
    model=llm,
    tools=[save_draft_issue],
    system_prompt=draft_issues_prompt
)

# 8. Run the planning agent
print("Running planning agent to split PRD into draft issues...")
try:
    result = agent.invoke({
        "messages": [
            HumanMessage(content=f"PRD Content:\n{prd_content}\n\nDomain Glossary (CONTEXT.md):\n{context_content}")
        ]
    })
    print("Draft issues generation complete.")
except Exception as e:
    print(f"Error during execution: {e}", file=sys.stderr)
    sys.exit(1)
EOF

chmod +x "$RUNNER_SCRIPT"
echo "Created runner script template at .planner/run_planner.py."

# 6. Setup Python virtual environment
VENV_DIR="$TARGET_DIR_ABS/.venv"
echo "Setting up virtual environment at $VENV_DIR..."

if command -v uv &> /dev/null; then
    echo "Found 'uv' package manager. Using 'uv' for virtualenv setup..."
    uv venv "$VENV_DIR" --python 3.12
    source "$VENV_DIR/bin/activate"
    uv pip install langchain-openai langchain-core deepagents
else
    echo "'uv' not found. Using standard 'python3 -m venv'..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install langchain-openai langchain-core deepagents
fi

echo "Virtual environment ready and packages installed successfully."
echo "=== Bootstrapping Complete ==="
echo "To get started:"
echo "1. cd $TARGET_DIR_ABS"
echo "2. source .venv/bin/activate"
echo "3. export OPENROUTER_API_KEY=\"<your-api-key>\""
echo "4. python .planner/run_planner.py"
