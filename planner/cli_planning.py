import os
import sys
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from deepagents import create_deep_agent
from planner.config import AppConfig


# Helper to get the target repo short name
def get_repo_name(config: AppConfig) -> str:
    repo_name = config.github_repository
    if repo_name and "/" in repo_name:
        repo_name = repo_name.split("/")[-1]
    if not repo_name:
        repo_name = Path(config.github_workspace).name
    return repo_name


def get_target_path(config: AppConfig, relative_path: str) -> Path:
    """Resolves and validates that a path is within the target workspace boundary."""
    workspace_root = Path(config.github_workspace).resolve()
    target_file = (workspace_root / relative_path).resolve()

    # Containment check to prevent path traversal
    try:
        target_file.relative_to(workspace_root)
    except ValueError:
        raise PermissionError(
            f"Access denied: {relative_path} is outside the target workspace."
        )
    return target_file


@tool
def read_target_file(path: str) -> str:
    """Read the content of a file in the target repository.

    The path must be relative to the target repository root (e.g. 'PRD.md', 'CONTEXT.md', 'docs/adr/0001-setup.md').
    """
    config = AppConfig()
    try:
        target_file = get_target_path(config, path)
        if not target_file.exists():
            return f"Error: File '{path}' does not exist."
        with open(target_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file '{path}': {e}"


@tool
def write_target_file(path: str, content: str) -> str:
    """Write or overwrite the content of a file in the target repository.

    The path must be relative to the target repository root (e.g. 'PRD.md', 'CONTEXT.md', 'docs/adr/0001-setup.md').
    Directories will be created if they do not exist.
    """
    config = AppConfig()
    try:
        target_file = get_target_path(config, path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote file '{path}'."
    except Exception as e:
        return f"Error writing file '{path}': {e}"


@tool
def save_draft_issue(filename: str, markdown_content: str) -> str:
    """Save a generated draft issue markdown file in the central planner core repository.

    The filename must follow the format '####-slug.md' (e.g., '0001-setup-db.md') topologically sorted.
    """
    config = AppConfig()
    repo_name = get_repo_name(config)

    planner_core_root = Path(__file__).resolve().parents[1]
    drafts_base = (planner_core_root / "drafts" / repo_name).resolve()
    drafts_base.mkdir(parents=True, exist_ok=True)

    # Path traversal protection
    target_file = (drafts_base / filename).resolve()
    try:
        target_file.relative_to(drafts_base)
    except ValueError:
        return "Error: File path traversal detected. Access denied to write outside drafts directory."

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        return f"Successfully saved draft issue to central drafts: drafts/{repo_name}/{filename}"
    except Exception as e:
        return f"Failed to save draft issue: {e}"


def get_llm(config: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("AGENT_MODEL", "google/gemini-2.5-flash"),
        temperature=0.0,
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=config.openrouter_api_key,
        use_responses_api=False,  # CRITICAL: OpenRouter compatibility flag
    )


def run_grill(config: AppConfig):
    """Runs the interactive PRD/ADR design session (grill-with-docs) from planner-core."""
    print("=== Starting Phase 1: Interactive Design Session (grill-with-docs) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    llm = get_llm(config)

    # Load skill
    planner_core_root = Path(__file__).resolve().parents[1]
    skill_path = planner_core_root / "skills" / "grill-with-docs" / "SKILL.md"
    if not skill_path.exists():
        print(
            f"Error: grill-with-docs skill prompt not found at {skill_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(skill_path, "r", encoding="utf-8") as f:
        grill_prompt = f.read()

    # Read initial PRD/CONTEXT files if they exist to bootstrap the context
    prd_path = Path(config.github_workspace) / "PRD.md"
    context_path = Path(config.github_workspace) / "CONTEXT.md"

    initial_user_message = "Let's start the design session."
    if prd_path.exists():
        with open(prd_path, "r", encoding="utf-8") as f:
            initial_user_message += f"\n\nExisting PRD.md content:\n{f.read()}"
    if context_path.exists():
        with open(context_path, "r", encoding="utf-8") as f:
            initial_user_message += (
                f"\n\nExisting CONTEXT.md glossary content:\n{f.read()}"
            )

    agent = create_deep_agent(
        model=llm,
        tools=[read_target_file, write_target_file],
        system_prompt=grill_prompt,
    )

    # Run interactive console chat loop
    messages = [HumanMessage(content=initial_user_message)]
    print(
        "\n[Grill Agent]: Initializing the grilling session... (Type 'exit' or 'quit' to end the session)\n"
    )

    while True:
        try:
            result = agent.invoke({"messages": messages})
            # Print the agent's response
            print(f"\n[Grill Agent]: {result.content}\n")

            # Read developer input
            user_input = input("[You]: ")
            if user_input.strip().lower() in ["exit", "quit"]:
                print("Ending grilling session.")
                break

            messages.append(HumanMessage(content=user_input))
        except KeyboardInterrupt:
            print("\nSession interrupted.")
            break
        except Exception as e:
            print(f"Error in grill loop: {e}", file=sys.stderr)
            break


def run_verify(config: AppConfig):
    """Runs the learning verification session (wise-teacher) from planner-core."""
    print("=== Starting Phase 1b: Learning Verification Session (wise-teacher) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    llm = get_llm(config)

    # Load skill
    planner_core_root = Path(__file__).resolve().parents[1]
    skill_path = planner_core_root / "skills" / "wise-teacher" / "SKILL.md"
    if not skill_path.exists():
        print(
            f"Error: wise-teacher skill prompt not found at {skill_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(skill_path, "r", encoding="utf-8") as f:
        teacher_prompt = f.read()

    # Read PRD/CONTEXT files
    prd_path = Path(config.github_workspace) / "PRD.md"
    context_path = Path(config.github_workspace) / "CONTEXT.md"

    initial_user_message = (
        "Please start the review session and verify my understanding."
    )
    if prd_path.exists():
        with open(prd_path, "r", encoding="utf-8") as f:
            initial_user_message += f"\n\nPRD.md content:\n{f.read()}"
    if context_path.exists():
        with open(context_path, "r", encoding="utf-8") as f:
            initial_user_message += f"\n\nCONTEXT.md glossary content:\n{f.read()}"

    agent = create_deep_agent(
        model=llm, tools=[read_target_file], system_prompt=teacher_prompt
    )

    # Run interactive console chat loop
    messages = [HumanMessage(content=initial_user_message)]
    print(
        "\n[Wise Teacher]: Initializing review checklist... (Type 'exit' or 'quit' to end the session)\n"
    )

    while True:
        try:
            result = agent.invoke({"messages": messages})
            print(f"\n[Wise Teacher]: {result.content}\n")

            user_input = input("[You]: ")
            if user_input.strip().lower() in ["exit", "quit"]:
                print("Ending verification session.")
                break

            messages.append(HumanMessage(content=user_input))
        except KeyboardInterrupt:
            print("\nSession interrupted.")
            break
        except Exception as e:
            print(f"Error in teacher loop: {e}", file=sys.stderr)
            break


def run_draft(config: AppConfig):
    """Runs the issue splitting session (draft-issues) from planner-core."""
    print("=== Starting Phase 2: Draft Issue Generation (draft-issues) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    llm = get_llm(config)

    # Load skill
    planner_core_root = Path(__file__).resolve().parents[1]
    skill_path = planner_core_root / "skills" / "draft-issues" / "SKILL.md"
    if not skill_path.exists():
        print(
            f"Error: draft-issues skill prompt not found at {skill_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(skill_path, "r", encoding="utf-8") as f:
        draft_prompt = f.read()

    # Read PRD/CONTEXT files
    prd_path = Path(config.github_workspace) / "PRD.md"
    context_path = Path(config.github_workspace) / "CONTEXT.md"

    if not prd_path.exists():
        print(f"Error: PRD.md not found at {prd_path}.", file=sys.stderr)
        sys.exit(1)

    with open(prd_path, "r", encoding="utf-8") as f:
        prd_content = f.read()

    context_content = ""
    if context_path.exists():
        with open(context_path, "r", encoding="utf-8") as f:
            context_content = f.read()

    agent = create_deep_agent(
        model=llm, tools=[save_draft_issue], system_prompt=draft_prompt
    )

    print("Generating and saving draft issues centrally...")
    try:
        agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=f"PRD Content:\n{prd_content}\n\nDomain Glossary (CONTEXT.md):\n{context_content}"
                    )
                ]
            }
        )
        print(
            "Draft issues generation complete. Check the 'drafts/' directory in agentic-planner-core."
        )
    except Exception as e:
        print(f"Error generating draft issues: {e}", file=sys.stderr)
        sys.exit(1)
