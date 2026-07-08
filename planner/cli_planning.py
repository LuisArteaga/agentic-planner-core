import datetime
import json
import os
import re
import sys
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from deepagents import create_deep_agent
from planner.config import AppConfig, get_model
from planner.tools.research import (
    create_fetch_url_tool,
    create_github_read_file_tool,
    create_github_list_issues_tool,
    create_github_get_releases_tool,
)
from scripts.telemetry import (
    init_telemetry,
    start_orchestrator_loop,
    end_orchestrator_loop,
)


class ConsoleLoggingHandler(BaseCallbackHandler):
    """LangChain callback handler that logs LLM and tool activity to the console."""

    _MAX_LEN = 200  # Max chars to show inline before truncating

    def _truncate(self, text: str) -> str:
        text = str(text)
        if len(text) > self._MAX_LEN:
            return text[: self._MAX_LEN] + "..."
        return text

    def on_llm_start(self, serialized, prompts, **kwargs):
        model = serialized.get("kwargs", {}).get("model") or serialized.get(
            "name", "LLM"
        )
        print(f"\n[Agent]: Thinking... (model: {model})", flush=True)

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = serialized.get("name", "tool")
        print(f"\n[Tool ▶]: {name}({self._truncate(input_str)})", flush=True)

    def on_tool_end(self, output, **kwargs):
        print(f"[Tool ◀]: {self._truncate(output)}", flush=True)


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


def create_grill_session_tools(config: AppConfig, session_id: str, session_state: dict):
    """Tool factory to build session control tools bound to a specific AppConfig, session, and state."""

    @tool
    def finish_session(summary: str) -> str:
        """Conclude the interactive design session with a summary of the decisions and results.

        Prerequisites:
        - 'PRD.md' must exist in the target repository.
        """
        try:
            # Check if PRD.md exists in target repository
            prd_file = get_target_path(config, "PRD.md")
            if not prd_file.exists():
                return (
                    "Error: PRD.md does not exist in the target repository. "
                    "Please create it first using write_target_file before finishing the session."
                )

            # Optional check for CONTEXT.md
            context_file = get_target_path(config, "CONTEXT.md")
            warning_msg = ""
            if not context_file.exists():
                warning_msg = (
                    " Warning: CONTEXT.md does not exist in target repository."
                )
                print(
                    "\n[Warning]: CONTEXT.md does not exist in the target repository."
                )

            # Signal completion to the loop
            session_state["completed"] = True
            session_state["summary"] = summary

            # Return success status
            return f"Session successfully completed.{warning_msg}"

        except Exception as e:
            return f"Error concluding session: {e}"

    return finish_session


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


def get_llm(config: AppConfig, model_name: str = None) -> ChatOpenAI:
    """Instantiate ChatOpenAI configured for OpenRouter compatibility."""
    if not model_name:
        model_name = get_model("default")
    return ChatOpenAI(
        model=model_name,
        temperature=0.0,
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=config.openrouter_api_key,
        use_responses_api=False,  # CRITICAL: OpenRouter compatibility flag
        timeout=600.0,  # Prevent indefinite hangs on OpenRouter API calls while allowing long reasoning generations
    )


def setup_planning_agent(config: AppConfig, skill_name: str, tools: list):
    """Factory to load skill prompts and construct the deep agent."""
    if skill_name == "grill-with-docs":
        model_name = get_model("grill")
    elif skill_name == "wise-teacher":
        model_name = get_model("verify")
    elif skill_name == "draft-issues":
        model_name = get_model("draft")
    else:
        model_name = get_model("default")

    llm = get_llm(config, model_name=model_name)

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

    return serialized


def deserialize_messages(serialized: list[dict]) -> list[BaseMessage]:
    """Deserializes dictionaries back into LangChain messages."""
    deserialized: list[BaseMessage] = []
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


def save_session(
    config: AppConfig,
    session_id: str,
    messages: list[BaseMessage],
    prefix: str = "grill",
    completed: bool = False,
):
    """Saves an interactive session to .planner/sessions/{repo_name}/{prefix}_{session_id}.json."""
    try:
        repo_name = get_repo_name(config)
        planner_core_root = Path(__file__).resolve().parents[1]
        sessions_base = (planner_core_root / ".planner" / "sessions").resolve()

        # Prevent directory traversal for sessions_dir
        sessions_dir = (sessions_base / repo_name).resolve()
        try:
            sessions_dir.relative_to(sessions_base)
        except ValueError:
            print("Error: Session directory traversal detected.", file=sys.stderr)
            return

        filename = f"{prefix}_{session_id}.json"
        target_file = (sessions_dir / filename).resolve()

        # Prevent directory traversal for target_file
        try:
            target_file.relative_to(sessions_dir)
        except ValueError:
            print("Error: Session file traversal detected.", file=sys.stderr)
            return

        sessions_dir.mkdir(parents=True, exist_ok=True)

        serialized_messages = serialize_messages(messages)
        last_modified = datetime.datetime.now().astimezone().isoformat()

        session_data = {
            "session_id": f"{prefix}_{session_id}",
            "last_modified": last_modified,
            "completed": completed,
            "messages": serialized_messages,
        }

        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"Warning: Auto-saving {prefix} session failed: {e}", file=sys.stderr)


def save_grill_session(
    config: AppConfig,
    session_id: str,
    messages: list[BaseMessage],
    completed: bool = False,
):
    """Saves the current grill session. Delegates to save_session with prefix='grill'."""
    save_session(config, session_id, messages, prefix="grill", completed=completed)


def save_verify_session(
    config: AppConfig,
    session_id: str,
    messages: list[BaseMessage],
    completed: bool = False,
):
    """Saves the current verify session. Delegates to save_session with prefix='verify'."""
    save_session(config, session_id, messages, prefix="verify", completed=completed)


def run_interactive_console_loop(
    agent,
    agent_name: str,
    initial_message: str = None,
    config: AppConfig = None,
    session_id: str = None,
    existing_messages: list[BaseMessage] = None,
    session_state: dict = None,
    session_prefix: str = "grill",
):
    """Generic interactive console chat loop for planning agents."""
    if existing_messages:
        messages = list(existing_messages)
    else:
        messages = [HumanMessage(content=initial_message)]

    # Initial save if auto-saving is active and this is a new session
    if config and session_id and not existing_messages:
        save_session(
            config, session_id, messages, prefix=session_prefix, completed=False
        )

    print(f"\n[{agent_name}]: Initializing session... (Type 'exit' or 'quit' to end)\n")

    skip_agent = False
    if existing_messages and len(existing_messages) > 0:
        last_msg = existing_messages[-1]
        if isinstance(last_msg, AIMessage):
            # Print the agent's last reply so the user has context
            print(f"\n[{agent_name}]: {last_msg.content}\n")
            skip_agent = True

    while True:
        try:
            if not skip_agent:
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
                    completed = bool(session_state and session_state.get("completed"))
                    save_session(
                        config,
                        session_id,
                        messages,
                        prefix=session_prefix,
                        completed=completed,
                    )

                if session_state and session_state.get("completed"):
                    print("\n" + "=" * 80)
                    print("                           GRILL SESSION SUMMARY")
                    print("=" * 80)
                    print(session_state.get("summary", ""))
                    print("=" * 80 + "\n")
                    break
            else:
                skip_agent = False

            user_input = input("[You]: ")
            if user_input.strip().lower() in ["exit", "quit"]:
                print(f"Ending {agent_name} session.")
                # Save state as completed
                if config and session_id:
                    save_session(
                        config,
                        session_id,
                        messages,
                        prefix=session_prefix,
                        completed=True,
                    )
                break

            messages.append(HumanMessage(content=user_input))

            # Save state after user input
            if config and session_id:
                save_session(
                    config, session_id, messages, prefix=session_prefix, completed=False
                )

        except KeyboardInterrupt:
            print("\nSession interrupted.")
            break
        except Exception as e:
            print(f"Error in agent execution loop: {e}", file=sys.stderr)
            break


def load_or_select_session(config: AppConfig, prefix: str, session_id: str = None):
    """
    Loads a specific session directly by session_id, or scans for incomplete sessions
    with the given prefix and prompts the user to select one via an interactive menu.
    Returns:
        (resumed_messages, active_session_id)
        - resumed_messages: List of deserialized messages or None if a new session should start.
        - active_session_id: The ID of the session (resumed clean ID or a newly generated one).
    """
    repo_name = get_repo_name(config)
    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_base = (planner_core_root / ".planner" / "sessions").resolve()
    sessions_dir = (sessions_base / repo_name).resolve()

    # Prevent directory traversal for sessions_dir
    try:
        sessions_dir.relative_to(sessions_base)
        sessions_dir_ok = True
    except ValueError:
        sessions_dir_ok = False

    resumed_messages = None
    resumed_session_id = None
    prefix_with_under = f"{prefix}_"

    if session_id:
        if not sessions_dir_ok:
            print(
                "Error: Invalid session directory traversal detected.", file=sys.stderr
            )
            sys.exit(1)

        # Strip prefix if present to find it robustly
        clean_id = (
            session_id[len(prefix_with_under) :]
            if session_id.startswith(prefix_with_under)
            else session_id
        )
        filename1 = f"{prefix_with_under}{clean_id}.json"
        filename2 = f"{session_id}.json"

        target_file = None
        f1 = (sessions_dir / filename1).resolve()
        f2 = (sessions_dir / filename2).resolve()
        try:
            f1.relative_to(sessions_dir)
            if f1.exists():
                target_file = f1
        except ValueError:
            pass

        if not target_file:
            try:
                f2.relative_to(sessions_dir)
                if f2.exists():
                    target_file = f2
            except ValueError:
                pass

        if not target_file or not target_file.exists():
            print(
                f"Error: Session file not found for session ID '{session_id}'.",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            resumed_messages = deserialize_messages(data["messages"])
            resumed_session_id = clean_id
            print(
                f"Resuming session '{prefix_with_under}{resumed_session_id}' directly..."
            )
        except Exception as e:
            print(f"Error loading session '{session_id}': {e}", file=sys.stderr)
            sys.exit(1)

    elif sessions_dir_ok and sessions_dir.exists():
        # Scan for existing session files with prefix
        session_files = list(sessions_dir.glob(f"{prefix_with_under}*.json"))
        incomplete_sessions = []

        for f_path in session_files:
            try:
                with open(f_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Check for mandatory keys
                if "completed" not in data or "messages" not in data:
                    print(
                        f"Warning: Skipping invalid session file '{f_path.name}': Missing 'completed' or 'messages' fields.",
                        file=sys.stderr,
                    )
                    continue

                if not data["completed"]:
                    clean_id = (
                        f_path.stem[len(prefix_with_under) :]
                        if f_path.stem.startswith(prefix_with_under)
                        else f_path.stem
                    )
                    incomplete_sessions.append(
                        {
                            "id": clean_id,
                            "last_modified": data.get("last_modified", ""),
                            "messages": data["messages"],
                        }
                    )
            except (json.JSONDecodeError, KeyError) as e:
                print(
                    f"Warning: Skipping corrupted session file '{f_path.name}': {e}",
                    file=sys.stderr,
                )
                continue
            except Exception as e:
                print(
                    f"Warning: Failed to read session file '{f_path.name}': {e}",
                    file=sys.stderr,
                )
                continue

        # Sort by last_modified descending (newest first)
        incomplete_sessions.sort(key=lambda s: s["last_modified"], reverse=True)

        if incomplete_sessions:
            print(
                f"\nEs wurden unvollständige {prefix.capitalize()}-Sitzungen gefunden. Möchtest du eine fortsetzen?"
            )
            for idx, sess in enumerate(incomplete_sessions):
                last_mod = sess["last_modified"]
                try:
                    dt = datetime.datetime.fromisoformat(last_mod)
                    last_mod_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_mod_str = last_mod
                print(
                    f"  {idx + 1}. {prefix_with_under}{sess['id']} fortsetzen (Zuletzt geändert: {last_mod_str})"
                )
            print(f"  {len(incomplete_sessions) + 1}. Eine neue Sitzung starten")

            choice = None
            while True:
                try:
                    ans = input(
                        f"Deine Auswahl (1-{len(incomplete_sessions) + 1}): "
                    ).strip()
                    if not ans:
                        continue
                    val = int(ans)
                    if 1 <= val <= len(incomplete_sessions) + 1:
                        choice = val
                        break
                    else:
                        print(
                            f"Ungültige Auswahl. Bitte wähle eine Zahl zwischen 1 und {len(incomplete_sessions) + 1}."
                        )
                except ValueError:
                    print("Ungültige Eingabe. Bitte gib eine Zahl ein.")

            if choice <= len(incomplete_sessions):
                chosen = incomplete_sessions[choice - 1]
                resumed_session_id = chosen["id"]
                resumed_messages = deserialize_messages(chosen["messages"])
                print(
                    f"Setze Sitzung '{prefix_with_under}{resumed_session_id}' fort..."
                )

    if resumed_messages is not None:
        active_session_id = resumed_session_id
    else:
        active_session_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    return resumed_messages, active_session_id


def run_grill(config: AppConfig, session_id: str = None):
    """Runs the interactive PRD/ADR design session (grill-with-docs) from planner-core."""
    print("=== Starting Phase 1: Interactive Design Session (grill-with-docs) ===")
    print(f"Target workspace: {config.github_workspace}")

    resumed_messages, active_session_id = load_or_select_session(
        config, "grill", session_id
    )

    assert active_session_id is not None

    # Optional Langfuse tracing telemetry
    use_telemetry = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )
    if use_telemetry:
        init_telemetry()
        start_orchestrator_loop(session_id=active_session_id)

    session_state = {"completed": False, "summary": None}
    exit_code = 0
    try:
        print("Connecting to OpenRouter...")
        read_target_file, write_target_file = create_target_file_tools(config)
        finish_session = create_grill_session_tools(
            config, active_session_id, session_state
        )
        agent = setup_planning_agent(
            config,
            "grill-with-docs",
            [read_target_file, write_target_file, finish_session],
        )

        if resumed_messages is not None:
            run_interactive_console_loop(
                agent,
                "Grill Agent",
                config=config,
                session_id=active_session_id,
                existing_messages=resumed_messages,
                session_state=session_state,
            )
        else:
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

            run_interactive_console_loop(
                agent,
                "Grill Agent",
                initial_message=initial_user_message,
                config=config,
                session_id=active_session_id,
                session_state=session_state,
            )
    except Exception as e:
        exit_code = 1
        raise e
    finally:
        if use_telemetry:
            end_orchestrator_loop(exit_code=exit_code)


def run_verify(config: AppConfig, session_id: str = None):
    """Runs the learning verification session (wise-teacher) from planner-core."""
    print("=== Starting Phase 1b: Learning Verification Session (wise-teacher) ===")
    print(f"Target workspace: {config.github_workspace}")

    resumed_messages, active_session_id = load_or_select_session(
        config, "verify", session_id
    )

    assert active_session_id is not None

    # Optional Langfuse tracing telemetry
    use_telemetry = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )
    if use_telemetry:
        init_telemetry()
        start_orchestrator_loop(session_id=active_session_id)

    exit_code = 0
    try:
        print("Connecting to OpenRouter...")
        read_target_file, _ = create_target_file_tools(config)
        _, save_teaching_checklist = create_planning_tools(config)

        # Research and GitHub API tools
        fetch_url = create_fetch_url_tool(config)
        github_read_file = create_github_read_file_tool(config)
        github_list_issues = create_github_list_issues_tool(config)
        github_get_releases = create_github_get_releases_tool(config)

        agent = setup_planning_agent(
            config,
            "wise-teacher",
            [
                read_target_file,
                ask_question,
                save_teaching_checklist,
                fetch_url,
                github_read_file,
                github_list_issues,
                github_get_releases,
            ],
        )

        if resumed_messages is not None:
            run_interactive_console_loop(
                agent,
                "Wise Teacher",
                config=config,
                session_id=active_session_id,
                existing_messages=resumed_messages,
                session_prefix="verify",
            )
        else:
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
                    initial_user_message += (
                        f"\n\nCONTEXT.md glossary content:\n{f.read()}"
                    )

            run_interactive_console_loop(
                agent,
                "Wise Teacher",
                initial_message=initial_user_message,
                config=config,
                session_id=active_session_id,
                session_prefix="verify",
            )
    except Exception as e:
        exit_code = 1
        raise e
    finally:
        if use_telemetry:
            end_orchestrator_loop(exit_code=exit_code)


def run_draft(config: AppConfig):
    """Runs the issue splitting session (draft-issues) from planner-core."""
    print("=== Starting Phase 2: Draft Issue Generation (draft-issues) ===")
    print(f"Target workspace: {config.github_workspace}")
    print("Connecting to OpenRouter...")

    # Optional Langfuse tracing telemetry
    session_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    use_telemetry = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )
    if use_telemetry:
        init_telemetry()
        start_orchestrator_loop(session_id=session_id)

    exit_code = 0
    try:
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
        handler = ConsoleLoggingHandler()
        result = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=f"PRD Content:\n{prd_content}\n\nDomain Glossary (CONTEXT.md):\n{context_content}"
                    )
                ]
            },
            config={"callbacks": [handler]},
        )

        # Print final agent summary response
        if isinstance(result, dict) and "messages" in result:
            last_msg = result["messages"][-1]
            if hasattr(last_msg, "content") and last_msg.content:
                print(f"\n[Draft Agent]: {last_msg.content}")

        print(
            "\nDraft issues generation complete. Check '.planner/drafts/' centrally in planner-core."
        )
    except Exception as e:
        exit_code = 1
        print(f"Error generating draft issues: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if use_telemetry:
            end_orchestrator_loop(exit_code=exit_code)
