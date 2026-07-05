import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from planner.cli_planning import (
    deserialize_messages,
    run_interactive_console_loop,
    save_grill_session,
    serialize_messages,
)


class MockConfig:
    def __init__(self, workspace, repo):
        self.github_workspace = workspace
        self.github_repository = repo
        self.openrouter_api_key = "test-or-key"
        self.gh_pat = "test-gh-pat"


# Pytest fixture to configure a temporary workspace for session serialization tests
@pytest.fixture
def temp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = MockConfig(str(workspace), "test-owner/test-repo")
    return config, workspace


def test_serialize_deserialize_roundtrip():
    messages: list[BaseMessage] = [
        HumanMessage(content="Hello there! Ümlaut and Emoji 🚀"),
        AIMessage(
            content="Hello Human",
            tool_calls=[
                {
                    "name": "read_target_file",
                    "args": {"path": "PRD.md"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        SystemMessage(content="You are a helper bot."),
        ToolMessage(
            content="File contents...",
            tool_call_id="call_1",
            name="read_target_file",
        ),
    ]

    serialized = serialize_messages(messages)
    assert len(serialized) == 4

    assert serialized[0]["type"] == "human"
    assert serialized[0]["content"] == "Hello there! Ümlaut and Emoji 🚀"

    assert serialized[1]["type"] == "ai"
    assert serialized[1]["content"] == "Hello Human"
    assert serialized[1]["tool_calls"][0]["name"] == "read_target_file"

    assert serialized[2]["type"] == "system"

    assert serialized[3]["type"] == "tool"
    assert serialized[3]["tool_call_id"] == "call_1"

    deserialized = deserialize_messages(serialized)
    assert len(deserialized) == 4

    assert isinstance(deserialized[0], HumanMessage)
    assert deserialized[0].content == messages[0].content

    assert isinstance(deserialized[1], AIMessage)
    assert deserialized[1].content == messages[1].content
    assert deserialized[1].tool_calls == messages[1].tool_calls  # type: ignore[attr-defined]

    assert isinstance(deserialized[2], SystemMessage)
    assert deserialized[2].content == messages[2].content

    assert isinstance(deserialized[3], ToolMessage)
    assert deserialized[3].content == messages[3].content
    assert deserialized[3].tool_call_id == messages[3].tool_call_id  # type: ignore[attr-defined]
    assert deserialized[3].name == messages[3].name


def test_save_grill_session(temp_workspace):
    config, workspace = temp_workspace
    session_id = "test-session-123"

    messages: list[BaseMessage] = [
        HumanMessage(content="Test message with Unicode: Grüß Gott 🌟")
    ]

    # Save session
    save_grill_session(config, session_id, messages, completed=False)

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    session_file = sessions_dir / f"grill_{session_id}.json"

    assert session_file.exists()

    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["session_id"] == f"grill_{session_id}"
    assert data["completed"] is False
    assert len(data["messages"]) == 1
    assert data["messages"][0]["content"] == "Test message with Unicode: Grüß Gott 🌟"
    assert "last_modified" in data

    # Verify last_modified parses as ISO timestamp
    dt = datetime.datetime.fromisoformat(data["last_modified"])
    assert dt is not None

    # Clean up generated session directory / file
    if session_file.exists():
        session_file.unlink()
    if sessions_dir.exists():
        # Remove parent directories up to .planner if empty
        try:
            sessions_dir.rmdir()
            (planner_core_root / ".planner" / "sessions").rmdir()
        except OSError:
            pass


def test_save_grill_session_directory_traversal_protection(temp_workspace):
    config, _ = temp_workspace
    # Attempt directory traversal in session_id
    session_id = "../../../traversal"
    messages: list[BaseMessage] = [HumanMessage(content="Test")]

    # Should not throw but print error to stderr
    with patch("sys.stderr.write") as mock_stderr:
        save_grill_session(config, session_id, messages, completed=False)
        # Check that error or warning was written
        mock_stderr.assert_called()


def test_save_grill_session_repo_name_traversal_protection(temp_workspace):
    config, _ = temp_workspace
    # Attempt directory traversal in repository name
    config.github_repository = "some-org/.."
    messages: list[BaseMessage] = [HumanMessage(content="Test")]

    # Should not throw but print error to stderr
    with patch("sys.stderr.write") as mock_stderr:
        save_grill_session(config, "safe-session", messages, completed=False)
        mock_stderr.assert_called()


def test_save_grill_session_failure_caught(temp_workspace):
    config, _ = temp_workspace
    session_id = "test-fail"
    messages: list[BaseMessage] = [HumanMessage(content="Test")]

    # Force a failure (e.g. mkdir raises exception)
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        mock_mkdir.side_effect = Exception("Permission Denied")
        with patch("sys.stderr.write") as mock_stderr:
            save_grill_session(config, session_id, messages, completed=False)
            mock_stderr.assert_called()


def test_console_loop_auto_save_integration(temp_workspace):
    config, _ = temp_workspace
    session_id = "loop-test-123"

    mock_agent = MagicMock()
    # Mock agent returning dict with messages
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="Initial"),
            AIMessage(content="Agent reply"),
        ]
    }

    # Mock input to simulate user typing "exit"
    with (
        patch("builtins.input", side_effect=["exit"]) as mock_input,
        patch("planner.cli_planning.save_grill_session") as mock_save,
    ):
        run_interactive_console_loop(
            mock_agent,
            "Grill Agent",
            "Initial",
            config=config,
            session_id=session_id,
        )

        mock_input.assert_called_once()
        # Verify save_grill_session was called during loop execution
        # 1. Initial save before loop starts (completed=False)
        # 2. Save after agent reply (completed=False)
        # 3. Save when user types "exit" (completed=True)
        assert mock_save.call_count >= 3
        # Check last call is completed=True
        last_call_args = mock_save.call_args_list[-1]
        assert last_call_args[1]["completed"] is True


def test_console_loop_no_auto_save_when_omitted():
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="Initial"),
            AIMessage(content="Agent reply"),
        ]
    }

    with (
        patch("builtins.input", side_effect=["exit"]),
        patch("planner.cli_planning.save_grill_session") as mock_save,
    ):
        run_interactive_console_loop(
            mock_agent,
            "Grill Agent",
            "Initial",
            config=None,  # type: ignore[arg-type]
            session_id=None,  # type: ignore[arg-type]
        )

        # save_grill_session should never be called when config/session_id are None
        mock_save.assert_not_called()


def test_run_grill_resumes_session_via_menu(temp_workspace):
    config, workspace = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "grill_menu-resume.json"
    session_data = {
        "session_id": "grill_menu-resume",
        "last_modified": "2026-07-05T09:00:00.000000+00:00",
        "completed": False,
        "messages": [
            {"type": "human", "content": "Hello"},
            {"type": "ai", "content": "Hi there", "tool_calls": []},
        ],
    }
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    try:
        mock_agent = MagicMock()
        with (
            patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["1"]),  # Choose option 1 (resume)
            patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
        ):
            from planner.cli_planning import run_grill

            run_grill(config)

            mock_loop.assert_called_once()
            call_kwargs = mock_loop.call_args[1]
            assert call_kwargs["session_id"] == "menu-resume"
            assert len(call_kwargs["existing_messages"]) == 2
            assert call_kwargs["existing_messages"][1].content == "Hi there"
    finally:
        if session_file.exists():
            session_file.unlink()
        try:
            sessions_dir.rmdir()
            (planner_core_root / ".planner" / "sessions").rmdir()
        except OSError:
            pass


def test_run_grill_new_session_via_menu(temp_workspace):
    config, workspace = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "grill_menu-new.json"
    session_data = {
        "session_id": "grill_menu-new",
        "last_modified": "2026-07-05T09:00:00.000000+00:00",
        "completed": False,
        "messages": [{"type": "human", "content": "Hello"}],
    }
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    try:
        mock_agent = MagicMock()
        with (
            patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
            patch("builtins.input", side_effect=["2"]),  # Choose option 2 (start new)
            patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
        ):
            from planner.cli_planning import run_grill

            run_grill(config)

            mock_loop.assert_called_once()
            call_kwargs = mock_loop.call_args[1]
            assert call_kwargs.get("existing_messages") is None
            assert call_kwargs["initial_message"] == "Let's start the design session."
    finally:
        if session_file.exists():
            session_file.unlink()
        try:
            sessions_dir.rmdir()
            (planner_core_root / ".planner" / "sessions").rmdir()
        except OSError:
            pass


def test_run_grill_direct_session_id_exists(temp_workspace):
    config, workspace = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "grill_direct-id.json"
    session_data = {
        "session_id": "grill_direct-id",
        "last_modified": "2026-07-05T09:00:00.000000+00:00",
        "completed": False,
        "messages": [{"type": "human", "content": "Hello"}],
    }
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    try:
        mock_agent = MagicMock()
        with (
            patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
            patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
        ):
            from planner.cli_planning import run_grill

            run_grill(config, session_id="direct-id")

            mock_loop.assert_called_once()
            call_kwargs = mock_loop.call_args[1]
            assert call_kwargs["session_id"] == "direct-id"
            assert len(call_kwargs["existing_messages"]) == 1
    finally:
        if session_file.exists():
            session_file.unlink()
        try:
            sessions_dir.rmdir()
            (planner_core_root / ".planner" / "sessions").rmdir()
        except OSError:
            pass


def test_run_grill_direct_session_id_not_found(temp_workspace):
    config, workspace = temp_workspace

    from planner.cli_planning import run_grill

    with pytest.raises(SystemExit) as excinfo:
        run_grill(config, session_id="nonexistent-id")

    assert excinfo.value.code == 1


def test_run_grill_invalid_json_is_ignored(temp_workspace):
    config, workspace = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "grill_corrupt.json"
    with open(session_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")

    try:
        mock_agent = MagicMock()
        with (
            patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
            patch("sys.stderr.write") as mock_stderr,
            patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
        ):
            from planner.cli_planning import run_grill

            run_grill(config)

            mock_loop.assert_called_once()
            assert mock_loop.call_args[1].get("existing_messages") is None
            mock_stderr.assert_called()
    finally:
        if session_file.exists():
            session_file.unlink()
        try:
            sessions_dir.rmdir()
            (planner_core_root / ".planner" / "sessions").rmdir()
        except OSError:
            pass


def test_console_loop_skip_agent_turn(temp_workspace):
    config, _ = temp_workspace
    session_id = "skip-test"

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="Initial"),
            AIMessage(content="Agent reply"),
        ]
    }

    existing_messages = [
        HumanMessage(content="Hello"),
        AIMessage(content="I am here to help."),
    ]

    with (
        patch("builtins.input", side_effect=["exit"]) as mock_input,
        patch("planner.cli_planning.save_grill_session"),
        patch("builtins.print"),
    ):
        run_interactive_console_loop(
            mock_agent,
            "Grill Agent",
            config=config,
            session_id=session_id,
            existing_messages=existing_messages,
        )

        mock_agent.invoke.assert_not_called()
        mock_input.assert_called_once()


def test_run_grill_telemetry_disabled(temp_workspace):
    config, workspace = temp_workspace

    mock_agent = MagicMock()
    with (
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
        patch.dict("os.environ", {}, clear=True),
        patch("scripts.telemetry.init_telemetry") as mock_init,
        patch("scripts.telemetry.start_orchestrator_loop") as mock_start,
        patch("scripts.telemetry.end_orchestrator_loop") as mock_end,
    ):
        from planner.cli_planning import run_grill

        run_grill(config)

        mock_init.assert_not_called()
        mock_start.assert_not_called()
        mock_end.assert_not_called()
        mock_loop.assert_called_once()


def test_run_grill_telemetry_enabled_success(temp_workspace):
    config, workspace = temp_workspace

    mock_agent = MagicMock()
    env_keys = {"LANGFUSE_PUBLIC_KEY": "pk_test", "LANGFUSE_SECRET_KEY": "sk_test"}
    with (
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
        patch.dict("os.environ", env_keys, clear=False),
        patch("scripts.telemetry.init_telemetry") as mock_init,
        patch("scripts.telemetry.start_orchestrator_loop") as mock_start,
        patch("scripts.telemetry.end_orchestrator_loop") as mock_end,
    ):
        from planner.cli_planning import run_grill

        run_grill(config)

        mock_init.assert_called_once()
        mock_start.assert_called_once()
        # Verify that start_orchestrator_loop was called with a session ID
        call_kwargs = mock_start.call_args[1]
        assert "session_id" in call_kwargs
        assert len(call_kwargs["session_id"]) > 0
        mock_end.assert_called_once_with(exit_code=0)
        mock_loop.assert_called_once()


def test_run_grill_telemetry_enabled_failure(temp_workspace):
    config, workspace = temp_workspace

    env_keys = {"LANGFUSE_PUBLIC_KEY": "pk_test", "LANGFUSE_SECRET_KEY": "sk_test"}
    with (
        patch(
            "planner.cli_planning.setup_planning_agent",
            side_effect=Exception("Setup failed"),
        ),
        patch.dict("os.environ", env_keys, clear=False),
        patch("scripts.telemetry.init_telemetry") as mock_init,
        patch("scripts.telemetry.start_orchestrator_loop") as mock_start,
        patch("scripts.telemetry.end_orchestrator_loop") as mock_end,
    ):
        from planner.cli_planning import run_grill

        with pytest.raises(Exception, match="Setup failed"):
            run_grill(config)

        mock_init.assert_called_once()
        mock_start.assert_called_once()
        mock_end.assert_called_once_with(exit_code=1)


def test_finish_session_missing_prd(temp_workspace):
    config, workspace = temp_workspace
    # PRD.md does not exist
    session_state = {"completed": False, "summary": None}

    from planner.cli_planning import create_grill_session_tools

    finish_session = create_grill_session_tools(config, "test-sess", session_state)

    result = finish_session.invoke("Test Summary")
    assert "Error: PRD.md does not exist" in result
    assert session_state["completed"] is False


def test_finish_session_missing_context_warning(temp_workspace):
    config, workspace = temp_workspace
    # Create PRD.md
    prd_file = workspace / "PRD.md"
    prd_file.write_text("PRD Content")

    session_state = {"completed": False, "summary": None}

    from planner.cli_planning import create_grill_session_tools

    finish_session = create_grill_session_tools(config, "test-sess", session_state)

    result = finish_session.invoke("Test Summary")
    assert "Session successfully completed." in result
    assert "Warning: CONTEXT.md does not exist" in result
    assert session_state["completed"] is True
    assert session_state["summary"] == "Test Summary"


def test_finish_session_success(temp_workspace):
    config, workspace = temp_workspace
    # Create PRD.md and CONTEXT.md
    prd_file = workspace / "PRD.md"
    prd_file.write_text("PRD Content")
    context_file = workspace / "CONTEXT.md"
    context_file.write_text("Glossary")

    session_state = {"completed": False, "summary": None}

    from planner.cli_planning import create_grill_session_tools

    finish_session = create_grill_session_tools(config, "test-sess", session_state)

    result = finish_session.invoke("Test Summary")
    assert result == "Session successfully completed."
    assert session_state["completed"] is True
    assert session_state["summary"] == "Test Summary"


def test_console_loop_exits_on_finish_session(temp_workspace):
    config, _ = temp_workspace
    session_state = {"completed": True, "summary": "Final Summary"}

    mock_agent = MagicMock()
    # Mock agent return to stop the turn
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="Initial"),
            AIMessage(content="Agent reply"),
        ]
    }

    with (
        patch("builtins.input") as mock_input,
        patch("planner.cli_planning.save_grill_session") as mock_save,
        patch("builtins.print"),
    ):
        run_interactive_console_loop(
            mock_agent,
            "Grill Agent",
            "Initial",
            config=config,
            session_id="test-sess",
            session_state=session_state,
        )

        # Verify that input was never called because it broke immediately when session_state["completed"] became True
        mock_input.assert_not_called()

        # Verify that save_grill_session was called with completed=True
        assert mock_save.call_count >= 2
        last_call_args = mock_save.call_args_list[-1]
        assert last_call_args[1]["completed"] is True
