import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

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
    save_verify_session,
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
        patch("planner.cli_planning.save_session") as mock_save,
    ):
        run_interactive_console_loop(
            mock_agent,
            "Grill Agent",
            "Initial",
            config=config,
            session_id=session_id,
        )

        mock_input.assert_called_once()
        # Verify save_session was called during loop execution
        # 1. Initial save before loop starts (completed=False)
        # 2. Save after agent reply (completed=False)
        # 3. Save when user types "exit" (completed=True)
        assert mock_save.call_count >= 3
        # Check last call is completed=True
        last_call_kwargs = mock_save.call_args_list[-1][1]
        assert last_call_kwargs["completed"] is True


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
        patch("planner.telemetry.init_telemetry") as mock_init,
        patch("planner.telemetry.start_orchestrator_loop") as mock_start,
        patch("planner.telemetry.end_orchestrator_loop") as mock_end,
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
        patch("planner.cli_planning.init_telemetry") as mock_init,
        patch("planner.cli_planning.start_orchestrator_loop") as mock_start,
        patch("planner.cli_planning.end_orchestrator_loop") as mock_end,
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
        patch("planner.cli_planning.init_telemetry") as mock_init,
        patch("planner.cli_planning.start_orchestrator_loop") as mock_start,
        patch("planner.cli_planning.end_orchestrator_loop") as mock_end,
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
        patch("planner.cli_planning.save_session") as mock_save,
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

        # Verify that save_session was called with completed=True
        assert mock_save.call_count >= 2
        last_call_kwargs = mock_save.call_args_list[-1][1]
        assert last_call_kwargs["completed"] is True


# ---------------------------------------------------------------------------
# Fixture: clean up verify session files in shared .planner/sessions/test-repo
# to prevent cross-test state pollution from tests that write to disk.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def verify_sessions_cleanup():
    """Remove all verify_*.json files from .planner/sessions/test-repo before and after each test."""
    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"

    def _cleanup():
        if sessions_dir.exists():
            for f in sessions_dir.glob("verify_*.json"):
                f.unlink(missing_ok=True)

    _cleanup()
    yield
    _cleanup()


# ---------------------------------------------------------------------------
# Tests for verify session save/resume
# ---------------------------------------------------------------------------


def test_save_verify_session(temp_workspace, verify_sessions_cleanup):
    """save_verify_session should write verify_<id>.json with correct structure."""
    config, _ = temp_workspace
    session_id = "verify-test-001"
    messages: list[BaseMessage] = [
        HumanMessage(content="Let's start the verify session.")
    ]

    save_verify_session(config, session_id, messages, completed=False)

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    session_file = sessions_dir / f"verify_{session_id}.json"
    assert session_file.exists(), f"Expected session file at {session_file}"

    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["session_id"] == f"verify_{session_id}"
    assert data["completed"] is False
    assert len(data["messages"]) == 1
    assert data["messages"][0]["type"] == "human"


def test_run_verify_resumes_session_via_menu(temp_workspace, verify_sessions_cleanup):
    """run_verify should offer incomplete sessions and resume the chosen one."""
    config, _ = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "verify_menu-resume.json"
    session_data = {
        "session_id": "verify_menu-resume",
        "last_modified": datetime.datetime.now().isoformat(),
        "completed": False,
        "messages": [{"type": "human", "content": "Start verify"}],
    }
    with open(session_file, "w") as f:
        json.dump(session_data, f)

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="Start verify"),
            AIMessage(content="Let's begin!"),
        ]
    }

    with (
        patch("builtins.input", side_effect=["1", "exit"]),
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
    ):
        from planner.cli_planning import run_verify

        run_verify(config)

        mock_loop.assert_called_once()
        kwargs = mock_loop.call_args[1]
        assert kwargs["session_id"] == "menu-resume"
        assert len(kwargs["existing_messages"]) == 1
        assert kwargs["existing_messages"][0].content == "Start verify"
        assert kwargs["session_prefix"] == "verify"


def test_run_verify_direct_session_id_exists(temp_workspace, verify_sessions_cleanup):
    """run_verify --session-id should resume the matching file directly."""
    config, _ = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "verify_direct-id.json"
    session_data = {
        "session_id": "verify_direct-id",
        "last_modified": datetime.datetime.now().isoformat(),
        "completed": False,
        "messages": [{"type": "human", "content": "Resuming directly"}],
    }
    with open(session_file, "w") as f:
        json.dump(session_data, f)

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="Resuming directly"),
            AIMessage(content="Welcome back!"),
        ]
    }

    with (
        patch("builtins.input", side_effect=["exit"]),
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.run_interactive_console_loop") as mock_loop,
    ):
        from planner.cli_planning import run_verify

        run_verify(config, session_id="direct-id")

        mock_loop.assert_called_once()
        kwargs = mock_loop.call_args[1]
        assert kwargs["session_id"] == "direct-id"
        assert len(kwargs["existing_messages"]) == 1
        assert kwargs["existing_messages"][0].content == "Resuming directly"
        assert kwargs["session_prefix"] == "verify"


def test_run_verify_direct_session_id_not_found(
    temp_workspace, verify_sessions_cleanup
):
    """run_verify with a non-existent session-id should exit with an error."""
    config, _ = temp_workspace

    from planner.cli_planning import run_verify

    with pytest.raises(SystemExit):
        run_verify(config, session_id="nonexistent-verify-id")


def test_run_verify_invalid_json_is_ignored(temp_workspace, verify_sessions_cleanup):
    """Corrupted verify session files should be skipped with a warning."""
    config, _ = temp_workspace

    planner_core_root = Path(__file__).resolve().parents[1]
    sessions_dir = planner_core_root / ".planner" / "sessions" / "test-repo"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_file = sessions_dir / "verify_corrupt.json"
    session_file.write_text("{ this is not valid json }")

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [HumanMessage(content="init"), AIMessage(content="Hello")]
    }

    with (
        patch("builtins.input", side_effect=["exit"]),
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.save_session"),
    ):
        from planner.cli_planning import run_verify

        # Should not raise — corrupted file is silently ignored, and no valid sessions
        # are found so we go directly to a new session (no menu).
        run_verify(config)


def test_run_verify_telemetry_disabled(temp_workspace, verify_sessions_cleanup):
    """run_verify should not call telemetry functions when keys are absent."""
    config, _ = temp_workspace

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [HumanMessage(content="init"), AIMessage(content="hi")]
    }

    with (
        patch("builtins.input", side_effect=["exit"]),
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.save_session"),
        patch.dict("os.environ", {}, clear=True),
    ):
        from planner.cli_planning import run_verify

        run_verify(config)


def test_run_verify_telemetry_enabled_success(temp_workspace, verify_sessions_cleanup):
    """run_verify should init telemetry and end loop with exit_code=0 on success."""
    config, _ = temp_workspace

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [HumanMessage(content="init"), AIMessage(content="hi")]
    }

    with (
        patch("builtins.input", side_effect=["exit"]),
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.save_session"),
        patch.dict(
            "os.environ",
            {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"},
        ),
        patch("planner.cli_planning.init_telemetry"),
        patch("planner.cli_planning.start_orchestrator_loop"),
        patch("planner.cli_planning.end_orchestrator_loop") as mock_end,
    ):
        from planner.cli_planning import run_verify

        run_verify(config)

    mock_end.assert_called_once_with(exit_code=0)


def test_run_verify_telemetry_enabled_failure(temp_workspace, verify_sessions_cleanup):
    """run_verify should call end_orchestrator_loop with exit_code=1 on exception."""
    config, _ = temp_workspace

    with (
        patch("builtins.input"),
        patch(
            "planner.cli_planning.setup_planning_agent",
            side_effect=RuntimeError("Agent setup failed"),
        ),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.save_session"),
        patch.dict(
            "os.environ",
            {"LANGFUSE_PUBLIC_KEY": "pk-test", "LANGFUSE_SECRET_KEY": "sk-test"},
        ),
        patch("planner.cli_planning.init_telemetry"),
        patch("planner.cli_planning.start_orchestrator_loop"),
        patch("planner.cli_planning.end_orchestrator_loop") as mock_end,
    ):
        from planner.cli_planning import run_verify

        with pytest.raises(RuntimeError, match="Agent setup failed"):
            run_verify(config)

    mock_end.assert_called_once_with(exit_code=1)


def test_console_logging_handler(capsys):
    """ConsoleLoggingHandler methods should truncate output and log to console."""
    from planner.cli_planning import ConsoleLoggingHandler

    handler = ConsoleLoggingHandler()

    # Test _truncate
    long_text = "a" * 300
    truncated = handler._truncate(long_text)
    assert len(truncated) == 203
    assert truncated.endswith("...")

    short_text = "hello"
    assert handler._truncate(short_text) == "hello"

    # Test on_llm_start
    serialized = {"kwargs": {"model": "test-model"}}
    handler.on_llm_start(serialized, ["prompt"])
    captured = capsys.readouterr()
    assert "[Agent]: Thinking... (model: test-model)" in captured.out

    # Test on_tool_start
    serialized_tool = {"name": "test_tool"}
    handler.on_tool_start(serialized_tool, "tool-input-text")
    captured = capsys.readouterr()
    assert "[Tool ▶]: test_tool(tool-input-text)" in captured.out

    # Test on_tool_end
    handler.on_tool_end("tool-output-text")
    captured = capsys.readouterr()
    assert "[Tool ◀]: tool-output-text" in captured.out


def test_run_draft_success(temp_workspace):
    """run_draft should initialize agent, read files, and trigger invoke with callback."""
    config, workspace = temp_workspace
    prd_file = workspace / "PRD.md"
    prd_file.write_text("PRD content", encoding="utf-8")

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [AIMessage(content="Draft issues generated!")]
    }

    with (
        patch("planner.cli_planning.setup_planning_agent", return_value=mock_agent),
        patch(
            "planner.cli_planning.create_target_file_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            "planner.cli_planning.create_planning_tools",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("planner.cli_planning.ConsoleLoggingHandler") as mock_handler_class,
    ):
        from planner.cli_planning import run_draft

        run_draft(config)

        mock_agent.invoke.assert_called_once()
        args = mock_agent.invoke.call_args[0][0]
        assert "messages" in args
        assert "PRD Content" in args["messages"][0].content
        mock_handler_class.assert_called_once()

        kwargs = mock_agent.invoke.call_args[1]
        assert "config" in kwargs
        assert kwargs["config"] == {"callbacks": [mock_handler_class.return_value]}


def test_main_refine_command():
    """Main function should parse CLI options, verify rate limit quota, and run graph with callback."""
    import logging
    from planner.__main__ import main

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {"status": "success"}

    mock_response = MagicMock()
    mock_response.json.return_value = {"resources": {"core": {"remaining": 100}}}
    # The rate-limit check uses the response as a context manager (#71) —
    # __enter__ must return the configured response (like requests.Response).
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    mock_config = MagicMock()
    mock_config.github_repository = "owner/repo"
    mock_config.sources.strict = False
    mock_config.sources.domains = ["domain.com"]
    mock_config.sources.urls = ["https://github.com/owner/repo"]
    mock_config.get_github_session.return_value = mock_session
    # Zero-Error-Tolerance AddOn is disabled by default (ADR-0019).
    from planner.zero_tolerance.models import ZeroToleranceConfig

    mock_config.get_zero_tolerance_config.return_value = ZeroToleranceConfig(
        enabled=False
    )

    with (
        patch("sys.argv", ["planner", "refine", "--config", "test-sources.toml"]),
        patch("planner.__main__.AppConfig", return_value=mock_config),
        patch("planner.__main__.graph", mock_graph),
        patch("planner.telemetry.init_telemetry") as mock_init,
        patch("planner.telemetry.start_orchestrator_loop") as mock_start,
        patch("planner.telemetry.end_orchestrator_loop") as mock_end,
        patch("planner.__main__.glob.glob", return_value=["draft1.md"]),
        patch("planner.__main__.Path.exists", return_value=True),
        patch("logging.basicConfig") as mock_logging_config,
        patch("planner.cli_planning.ConsoleLoggingHandler") as mock_handler_class,
    ):
        main()

        mock_init.assert_called_once()
        mock_start.assert_called_once()
        mock_end.assert_called_once_with(exit_code=0)
        mock_logging_config.assert_called_once_with(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        mock_handler_class.assert_called_once()
        mock_graph.invoke.assert_called_once()
        args, kwargs = mock_graph.invoke.call_args
        called_state = args[0]
        assert "domain.com" in called_state["allowed_domains"]
        assert "github.com" in called_state["allowed_domains"]
        assert kwargs["config"] == {"callbacks": [mock_handler_class.return_value]}


def test_main_grill_command():
    """Main function should parse grill command and delegate to run_grill."""
    from planner.__main__ import main

    with (
        patch("sys.argv", ["planner", "grill", "--session-id", "test-session"]),
        patch("planner.cli_planning.run_grill") as mock_run_grill,
        patch("planner.__main__.AppConfig"),
    ):
        main()
        mock_run_grill.assert_called_once()


def test_main_verify_command():
    """Main function should parse verify command and delegate to run_verify with session_id."""
    from planner.__main__ import main

    with (
        patch("sys.argv", ["planner", "verify", "--session-id", "test-verify-session"]),
        patch("planner.cli_planning.run_verify") as mock_run_verify,
        patch("planner.__main__.AppConfig"),
    ):
        main()
        mock_run_verify.assert_called_once_with(ANY, session_id="test-verify-session")


@patch("planner.cli_planning.setup_planning_agent")
@patch("planner.cli_planning.run_interactive_console_loop")
@patch("planner.cli_planning.load_or_select_session")
def test_run_verify_registers_research_tools(mock_load, mock_console, mock_setup):
    """run_verify should correctly wire direct fetch and github api tools into wise-teacher agent."""
    from planner.cli_planning import run_verify
    from unittest.mock import MagicMock

    mock_config = MagicMock()
    mock_config.github_workspace = "/workspace"
    mock_config.github_repository = "owner/repo"
    mock_config.sources.strict = False

    mock_load.return_value = (None, "test-session")

    run_verify(mock_config, session_id="test-session")

    mock_setup.assert_called_once()
    args, kwargs = mock_setup.call_args
    self_config, skill, tools = args
    tool_names = [t.name for t in tools]

    assert "fetch_url_content" in tool_names
    assert "read_github_file" in tool_names
    assert "list_github_issues" in tool_names
    assert "get_github_releases" in tool_names
