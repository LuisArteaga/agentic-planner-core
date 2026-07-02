import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from planner.state import RefinementState
from planner.nodes.apply_decision import (
    apply_decision_node,
    get_next_adr_number,
    ApplyDecisionOutput,
)


class ApplyDecisionTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "mock-openrouter-key"
        os.environ["GH_PAT"] = "mock-gh-pat"
        os.environ["GITHUB_REPOSITORY"] = "LuisArteaga/agentic-planner-core"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_get_next_adr_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adr_path = Path(temp_dir)
            # When empty
            self.assertEqual(get_next_adr_number(adr_path), 1)

            # With some ADR files
            (adr_path / "0001-first.md").write_text("content", encoding="utf-8")
            (adr_path / "0002-second.md").write_text("content", encoding="utf-8")
            # Ignored files
            (adr_path / "README.md").write_text("content", encoding="utf-8")
            (adr_path / "0005.txt").write_text("content", encoding="utf-8")

            self.assertEqual(get_next_adr_number(adr_path), 3)

            # Test gap or higher number
            (adr_path / "0010-high.md").write_text("content", encoding="utf-8")
            self.assertEqual(get_next_adr_number(adr_path), 11)

    @patch("planner.nodes.apply_decision.ChatOpenAI")
    def test_apply_decision_requires_adr(self, mock_chat_openai):
        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # Mock ApplyDecisionOutput
        mock_output = ApplyDecisionOutput(
            requires_adr=True,
            adr_title="use-sqlite-cache",
            adr_content="## Kontext und Problemstellung\nWe choose SQLite.",
            updated_issue_content="## What to build\nEnriched what to build.",
        )
        mock_raw_msg = MagicMock()
        mock_raw_msg.response_metadata = {
            "token_usage": {"prompt_tokens": 40, "completion_tokens": 80}
        }
        mock_structured_model.invoke.return_value = {
            "parsed": mock_output,
            "raw": mock_raw_msg,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            os.environ["GITHUB_WORKSPACE"] = str(workspace)

            draft_issue = workspace / "0005-issue.md"
            draft_issue.write_text(
                "## What to build\nOriginal content.", encoding="utf-8"
            )

            state: RefinementState = {
                "draft_issue_content": "## What to build\nOriginal content.",
                "draft_issue_path": str(draft_issue),
                "strict_mode": True,
                "allowed_domains": ["github.com"],
                "messages": [],
                "keywords": [],
                "search_queries": [],
                "search_results": [],
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "model_name": "google/gemini-2.5-flash",
                "status": "success",
                "proposed_options": [],
                "best_option": {"choice_id": "opt1", "score": 9.0},
                "all_grades": [],
            }

            output = apply_decision_node(state)

            # Check return values
            self.assertEqual(output["prompt_tokens"], 50)
            self.assertEqual(output["completion_tokens"], 100)
            self.assertEqual(output["status"], "success")

            # Check draft issue updated
            self.assertEqual(
                draft_issue.read_text(encoding="utf-8"),
                "## What to build\nEnriched what to build.\n",
            )

            # Check ADR created
            adr_file = workspace / "docs" / "adr" / "0001-use-sqlite-cache.md"
            self.assertTrue(adr_file.exists())
            adr_content = adr_file.read_text(encoding="utf-8")
            self.assertIn("# 0001 - Use Sqlite Cache", adr_content)
            self.assertIn("* **Status**: Accepted", adr_content)
            self.assertIn(
                "* **Entscheidungsträger**: google/gemini-2.5-flash", adr_content
            )
            self.assertIn("* **Trigger-Issue**: 0005-issue.md", adr_content)
            self.assertIn(
                "## Kontext und Problemstellung\nWe choose SQLite.", adr_content
            )

    @patch("planner.nodes.apply_decision.ChatOpenAI")
    def test_apply_decision_no_adr_and_no_changes(self, mock_chat_openai):
        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # Mock ApplyDecisionOutput with no changes
        mock_output = ApplyDecisionOutput(
            requires_adr=False,
            adr_title="",
            adr_content="",
            updated_issue_content="## What to build\nOriginal content.",  # identical
        )
        mock_raw_msg = MagicMock()
        mock_structured_model.invoke.return_value = {
            "parsed": mock_output,
            "raw": mock_raw_msg,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            os.environ["GITHUB_WORKSPACE"] = str(workspace)

            draft_issue = workspace / "0005-issue.md"
            draft_issue.write_text(
                "## What to build\nOriginal content.", encoding="utf-8"
            )

            state: RefinementState = {
                "draft_issue_content": "## What to build\nOriginal content.",
                "draft_issue_path": str(draft_issue),
                "strict_mode": True,
                "allowed_domains": ["github.com"],
                "messages": [],
                "keywords": [],
                "search_queries": [],
                "search_results": [],
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "model_name": "google/gemini-2.5-flash",
                "status": "success",
                "proposed_options": [],
                "best_option": {
                    "choice_id": "opt1",
                    "score": 5.0,
                },  # Low score -> would proposed Proposed if ADR
                "all_grades": [],
            }

            output = apply_decision_node(state)

            self.assertEqual(output["status"], "success")

            # Check draft issue remains identical
            self.assertEqual(
                draft_issue.read_text(encoding="utf-8"),
                "## What to build\nOriginal content.",
            )

            # Check NO ADR directory / file exists
            self.assertFalse((workspace / "docs" / "adr").exists())

    @patch("planner.nodes.apply_decision.ChatOpenAI")
    def test_apply_decision_io_error_raises(self, mock_chat_openai):
        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        mock_output = ApplyDecisionOutput(
            requires_adr=True,
            adr_title="error-trigger",
            adr_content="## Kontext und Problemstellung\nBoom.",
            updated_issue_content="## What to build\nBoom.",
        )
        mock_structured_model.invoke.return_value = {
            "parsed": mock_output,
            "raw": MagicMock(),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            os.environ["GITHUB_WORKSPACE"] = str(workspace)

            draft_issue = workspace / "0005-issue.md"
            draft_issue.write_text("original", encoding="utf-8")

            state: RefinementState = {
                "draft_issue_content": "original",
                "draft_issue_path": str(draft_issue),
                "strict_mode": True,
                "allowed_domains": [],
                "messages": [],
                "keywords": [],
                "search_queries": [],
                "search_results": [],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "model_name": "",
                "status": "success",
                "proposed_options": [],
                "best_option": {},
                "all_grades": [],
            }

            # Mock file writing to raise IOError
            with patch("builtins.open", side_effect=IOError("Permission denied")):
                with self.assertRaises(IOError):
                    apply_decision_node(state)
