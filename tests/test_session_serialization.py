import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
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
    messages = [
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
    assert deserialized[1].tool_calls == messages[1].tool_calls

    assert isinstance(deserialized[2], SystemMessage)
    assert deserialized[2].content == messages[2].content

    assert isinstance(deserialized[3], ToolMessage)
    assert deserialized[3].content == messages[3].content
    assert deserialized[3].tool_call_id == messages[3].tool_call_id
    assert deserialized[3].name == messages[3].name


def test_save_grill_session(temp_workspace):
    config, workspace = temp_workspace
    session_id = "test-session-123"

    messages = [HumanMessage(content="Test message with Unicode: Grüß Gott 🌟")]

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
    messages = [HumanMessage(content="Test")]

    # Should not throw but print error to stderr
    with patch("sys.stderr.write") as mock_stderr:
        save_grill_session(config, session_id, messages, completed=False)
        # Check that error or warning was written
        mock_stderr.assert_called()


def test_save_grill_session_repo_name_traversal_protection(temp_workspace):
    config, _ = temp_workspace
    # Attempt directory traversal in repository name
    config.github_repository = "some-org/.."
    messages = [HumanMessage(content="Test")]

    # Should not throw but print error to stderr
    with patch("sys.stderr.write") as mock_stderr:
        save_grill_session(config, "safe-session", messages, completed=False)
        mock_stderr.assert_called()


def test_save_grill_session_failure_caught(temp_workspace):
    config, _ = temp_workspace
    session_id = "test-fail"
    messages = [HumanMessage(content="Test")]

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
            config=None,
            session_id=None,
        )

        # save_grill_session should never be called when config/session_id are None
        mock_save.assert_not_called()
