import datetime
import json
import os
import re
import sys
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from deepagents import create_deep_agent
from planner.config import AppConfig


def get_repo_name(config: AppConfig) -> str:
    """Helper to extract the short repository name."""
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


def create_target_file_tools(config: AppConfig):
    """Tool factory to build file access tools bound to a specific AppConfig instance."""

    @tool
    def read_target_file(path: str) -> str:
        """Read the content of a file in the target repository.

        The path must be relative to the target repository root (e.g. 'PRD.md', 'CONTEXT.md', 'docs/adr/0001-setup.md').
        """
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
        try:
            target_file = get_target_path(config, path)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote file '{path}'."
        except Exception as e:
            return f"Error writing file '{path}': {e}"

    return read_target_file, write_target_file


def create_planning_tools(config: AppConfig):
    """Tool factory to build planning and logging tools bound to a specific AppConfig instance."""

    @tool
    def save_draft_issue(filename: str, markdown_content: str) -> str:
        """Save a generated draft issue markdown file in the central planner core repository.

        The filename must strictly follow the format '####-slug.md' (e.g., '0001-setup-db.md') topologically sorted.
        """
        # Enforce filename format described in skills/draft-issues/SKILL.md
        if not re.match(r"^\d{4}-[\w-]+\.md$", filename):
            return (
                "Error: Filename must strictly follow the format '####-slug.md' "
                "(e.g., '0001-setup-db.md') topologically sorted."
            )

        repo_name = get_repo_name(config)
        planner_core_root = Path(__file__).resolve().parents[1]
        drafts_base = (planner_core_root / ".planner" / "drafts" / repo_name).resolve()
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
            return f"Successfully saved draft issue to central drafts: .planner/drafts/{repo_name}/{filename}"
        except Exception as e:
            return f"Failed to save draft issue: {e}"

    @tool
    def save_teaching_checklist(markdown_content: str) -> str:
        """Save the updated .teaching-checklist.md log centrally in the planner core.

        Use this to persist the wise-teacher checklist.
        """
        repo_name = get_repo_name(config)
        planner_core_root = Path(__file__).resolve().parents[1]
        checklist_file = (
            planner_core_root
            / ".planner"
            / "drafts"
            / repo_name
            / ".teaching-checklist.md"
        ).resolve()
        checklist_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(checklist_file, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            return "Successfully saved teaching checklist."
        except Exception as e:
            return f"Error saving checklist: {e}"

    return save_draft_issue, save_teaching_checklist


@tool
def ask_question(
    question: str, options: list[str], is_multi_select: bool = False
) -> str:
    """Ask the user a multiple-choice question or get a write-in response.

    This tool prompts the developer in the console to select one of the options.
    """
    # Console prompt logic for interactive chat
    print(f"\n[Question]: {question}")
    for i, opt in enumerate(options):
        print(f"  {i + 1}. {opt}")
    print("  0. Write custom response")

    while True:
        try:
            ans = input("Your choice (number): ").strip()
            if not ans:
                continue
            idx = int(ans)
            if idx == 0:
                return input("Your custom response: ")
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            print("Invalid input. Please enter a valid number.")


def get_llm(config: AppConfig) -> ChatOpenAI:
    """Instantiate ChatOpenAI configured for OpenRouter compatibility."""
    return ChatOpenAI(
        model=os.getenv("AGENT_MODEL", "moonshotai/kimi-k2.7-code"),
        temperature=0.0,
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=config.openrouter_api_key,
        use_responses_api=False,  # CRITICAL: OpenRouter compatibility flag
    )


def setup_planning_agent(config: AppConfig, skill_name: str, tools: list):
    """Factory to load skill prompts and construct the deep agent."""
    llm = get_llm(config)

    planner_core_root = Path(__file__).resolve().parents[1]
    skill_path = planner_core_root / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists():
        print(f"Error: Skill prompt not found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    with open(skill_path, "r", encoding="utf-8") as f:
        skill_prompt = f.read()

    return create_deep_agent(model=llm, tools=tools, system_prompt=skill_prompt)


def serialize_messages(messages: list[BaseMessage]) -> list[dict]:
    """Serializes LangChain messages into standard dictionaries."""
    serialized = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            serialized.append({"type": "human", "content": msg.content})
        elif isinstance(msg, AIMessage):
            serialized.append(
                {"type": "ai", "content": msg.content, "tool_calls": msg.tool_calls}
            )
        elif isinstance(msg, SystemMessage):
            serialized.append({"type": "system", "content": msg.content})
        elif isinstance(msg, ToolMessage):
            serialized.append(
                {
                    "type": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                }
            )
        elif isinstance(msg, dict):
            serialized.append(msg)
    return serialized


def deserialize_messages(serialized: list[dict]) -> list[BaseMessage]:
    """Deserializes dictionaries back into LangChain messages."""
    deserialized = []
    for msg_dict in serialized:
        msg_type = msg_dict.get("type")
        content = msg_dict.get("content", "")
        if msg_type == "human":
            deserialized.append(HumanMessage(content=content))
        elif msg_type == "ai":
            tool_calls = msg_dict.get("tool_calls", [])
            deserialized.append(AIMessage(content=content, tool_calls=tool_calls))
        elif msg_type == "system":
            deserialized.append(SystemMessage(content=content))
        elif msg_type == "tool":
            tool_call_id = msg_dict.get("tool_call_id")
            name = msg_dict.get("name")
            deserialized.append(
                ToolMessage(content=content, tool_call_id=tool_call_id, name=name)
            )
    return deserialized


def save_grill_session(
    config: AppConfig,
    session_id: str,
    messages: list[BaseMessage],
    completed: bool = False,
):
    """Saves the current grill session to .planner/sessions/{repo_name}/grill_{session_id}.json."""
    try:
        repo_name = get_repo_name(config)
        planner_core_root = Path(__file__).resolve().parents[1]
        sessions_dir = (
            planner_core_root / ".planner" / "sessions" / repo_name
        ).resolve()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        filename = f"grill_{session_id}.json"
        target_file = sessions_dir / filename

        # Prevent directory traversal
        try:
            target_file.relative_to(sessions_dir)
        except ValueError:
            print("Error: Session file traversal detected.", file=sys.stderr)
            return

        serialized_messages = serialize_messages(messages)
        last_modified = datetime.datetime.now().astimezone().isoformat()

        session_data = {
            "session_id": f"grill_{session_id}",
            "last_modified": last_modified,
            "completed": completed,
            "messages": serialized_messages,
        }

        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"Warning: Auto-saving grill session failed: {e}", file=sys.stderr)


def run_interactive_console_loop(
    agent,
    agent_name: str,
    initial_message: str,
    config: AppConfig = None,
    session_id: str = None,
):
    """Generic interactive console chat loop for planning agents."""
    messages = [HumanMessage(content=initial_message)]

    # Initial save if auto-saving is active
    if config and session_id:
        save_grill_session(config, session_id, messages, completed=False)

    print(f"\n[{agent_name}]: Initializing session... (Type 'exit' or 'quit' to end)\n")

    while True:
        try:
            result = agent.invoke({"messages": messages})
            if isinstance(result, dict) and "messages" in result:
                response_message = result["messages"][-1]
                messages = list(result["messages"])
            else:
                response_message = result
                messages.append(response_message)

            print(f"\n[{agent_name}]: {response_message.content}\n")

            # Save state after agent step
            if config and session_id:
                save_grill_session(config, session_id, messages, completed=False)

            user_input = input("[You]: ")
            if user_input.strip().lower() in ["exit", "quit"]:
                print(f"Ending {agent_name} session.")
                # Save state as completed
                if config and session_id:
                    save_grill_session(config, session_id, messages, completed=True)
                break

            messages.append(HumanMessage(content=user_input))

            # Save state after user input
            if config and session_id:
                save_grill_session(config, session_id, messages, completed=False)

        except KeyboardInterrupt:
            print("\nSession interrupted.")
            break
        except Exception as e:
            print(f"Error in agent execution loop: {e}", file=sys.stderr)
            break


def run_grill(config: AppConfig):
    """Runs the interactive PRD/ADR design session (grill-with-docs) from planner-core."""
    print("=== Starting Phase 1: Interactive Design Session (grill-with-docs) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    read_target_file, write_target_file = create_target_file_tools(config)
    agent = setup_planning_agent(
        config, "grill-with-docs", [read_target_file, write_target_file]
    )

    # Read initial PRD/CONTEXT files if they exist to bootstrap context
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

    # Generate timestamp-based session_id: e.g. "2026-07-05_07-40-00"
    session_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    run_interactive_console_loop(
        agent,
        "Grill Agent",
        initial_user_message,
        config=config,
        session_id=session_id,
    )


def run_verify(config: AppConfig):
    """Runs the learning verification session (wise-teacher) from planner-core."""
    print("=== Starting Phase 1b: Learning Verification Session (wise-teacher) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    read_target_file, _ = create_target_file_tools(config)
    _, save_teaching_checklist = create_planning_tools(config)

    agent = setup_planning_agent(
        config,
        "wise-teacher",
        [read_target_file, ask_question, save_teaching_checklist],
    )

    # Read PRD/CONTEXT files to bootstrap wise-teacher
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

    run_interactive_console_loop(agent, "Wise Teacher", initial_user_message)


def run_draft(config: AppConfig):
    """Runs the issue splitting session (draft-issues) from planner-core."""
    print("=== Starting Phase 2: Draft Issue Generation (draft-issues) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    read_target_file, _ = create_target_file_tools(config)
    save_draft_issue, _ = create_planning_tools(config)
    agent = setup_planning_agent(
        config, "draft-issues", [save_draft_issue, read_target_file]
    )

    # Read target PRD/CONTEXT files
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
            "Draft issues generation complete. Check '.planner/drafts/' centrally in planner-core."
        )
    except Exception as e:
        print(f"Error generating draft issues: {e}", file=sys.stderr)
        sys.exit(1)
