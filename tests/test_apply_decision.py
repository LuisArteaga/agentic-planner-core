import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from planner.state import RefinementState
from planner.nodes.apply_decision import (
    apply_decision_node,
    get_next_agdr_number,
    ApplyDecisionOutput,
    AgDROption,
    AgDRConsequences,
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

    def test_get_next_agdr_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            agdr_path = Path(temp_dir)
            # When empty
            self.assertEqual(get_next_agdr_number(agdr_path), 1)

            # With some AgDR files
            (agdr_path / "0001-first.md").write_text("content", encoding="utf-8")
            (agdr_path / "0002-second.md").write_text("content", encoding="utf-8")
            # Ignored files
            (agdr_path / "README.md").write_text("content", encoding="utf-8")
            (agdr_path / "0005.txt").write_text("content", encoding="utf-8")

            self.assertEqual(get_next_agdr_number(agdr_path), 3)

            # Test gap or higher number
            (agdr_path / "0010-high.md").write_text("content", encoding="utf-8")
            self.assertEqual(get_next_agdr_number(agdr_path), 11)

    @patch("planner.nodes.apply_decision.get_llm")
    def test_apply_decision_requires_agdr(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # Mock ApplyDecisionOutput with structured fields
        mock_output = ApplyDecisionOutput(
            requires_agdr=True,
            agdr_title="use-sqlite-cache",
            y_statement="In the context of caching, facing high latency, we decided to use sqlite to achieve speed.",
            context_and_problem="We need structured cache storage.",
            drivers=["speed", "simplicity"],
            options_considered=[
                AgDROption(
                    name="SQLite",
                    description="Fast and local",
                    score=9.0,
                    checks_passed=9,
                ),
                AgDROption(
                    name="Redis",
                    description="In-memory cache",
                    score=7.5,
                    checks_passed=7,
                ),
            ],
            decision_rationale="We chose SQLite because it runs in-process.",
            consequences=AgDRConsequences(
                positive=["Fast reads", "No extra server"],
                negative=["Local file locks"],
            ),
            references=["https://sqlite.org"],
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

            # Check AgDR created
            agdr_file = workspace / "docs" / "agdr" / "0001-use-sqlite-cache.md"
            self.assertTrue(agdr_file.exists())
            agdr_content = agdr_file.read_text(encoding="utf-8")
            self.assertIn("# 0001 - Use Sqlite Cache", agdr_content)
            self.assertIn("* **Status**: Accepted", agdr_content)
            self.assertIn(
                "* **Entscheidungsträger**: google/gemini-2.5-flash", agdr_content
            )
            self.assertIn("* **Trigger-Issue**: 0005-issue.md", agdr_content)
            self.assertIn(
                "* **Y-Statement**: In the context of caching, facing high latency, we decided to use sqlite to achieve speed.",
                agdr_content,
            )
            self.assertIn(
                "## Kontext und Problemstellung\nWe need structured cache storage.",
                agdr_content,
            )
            self.assertIn(
                "## Entscheidungsfaktoren (Drivers)\n* speed\n* simplicity",
                agdr_content,
            )
            self.assertIn("## Betrachtete Optionen", agdr_content)
            self.assertIn("| SQLite | 9.0/10.0 | 9/10 | Fast and local |", agdr_content)
            self.assertIn("| Redis | 7.5/10.0 | 7/10 | In-memory cache |", agdr_content)
            self.assertIn(
                "## Entscheidung\nWe chose SQLite because it runs in-process.",
                agdr_content,
            )
            self.assertIn(
                "* **Positiv**:\n* Fast reads\n* No extra server", agdr_content
            )
            self.assertIn(
                "## Inspiration & Referenzen\n* https://sqlite.org", agdr_content
            )

    @patch("planner.nodes.apply_decision.get_llm")
    def test_apply_decision_no_agdr_and_no_changes(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        # Mock ApplyDecisionOutput with no changes
        mock_output = ApplyDecisionOutput(
            requires_agdr=False,
            agdr_title="",
            y_statement="",
            context_and_problem="",
            drivers=[],
            options_considered=[],
            decision_rationale="",
            consequences=AgDRConsequences(),
            references=[],
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
                },  # Low score -> would propose Proposed if AgDR
                "all_grades": [],
            }

            output = apply_decision_node(state)

            self.assertEqual(output["status"], "success")

            # Check draft issue remains identical
            self.assertEqual(
                draft_issue.read_text(encoding="utf-8"),
                "## What to build\nOriginal content.",
            )

            # Check NO AgDR directory / file exists
            self.assertFalse((workspace / "docs" / "agdr").exists())

    @patch("planner.nodes.apply_decision.get_llm")
    def test_apply_decision_path_traversal_raises(self, mock_get_llm):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            os.environ["GITHUB_WORKSPACE"] = str(workspace)

            # Define a path pointing outside workspace
            outside_path = "/etc/passwd"

            state: RefinementState = {
                "draft_issue_content": "some content",
                "draft_issue_path": outside_path,
                "strict_mode": True,
                "allowed_domains": [],
                "messages": [],
                "keywords": [],
                "search_queries": [],
                "search_results": [],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "model_name": "",
                "status": "idle",
                "proposed_options": [],
                "best_option": {},
                "all_grades": [],
            }

            with self.assertRaises(ValueError) as context:
                apply_decision_node(state)

            self.assertIn("Path traversal detected", str(context.exception))

    @patch("planner.nodes.apply_decision.get_llm")
    def test_apply_decision_with_central_drafts_path_succeeds(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_structured_model = MagicMock()
        mock_instance.with_structured_output.return_value = mock_structured_model

        mock_output = ApplyDecisionOutput(
            requires_agdr=False,
            agdr_title="",
            y_statement="",
            context_and_problem="",
            drivers=[],
            options_considered=[],
            decision_rationale="",
            consequences=AgDRConsequences(),
            references=[],
            updated_issue_content="## What to build\nOriginal content.",
        )
        mock_raw_msg = MagicMock()
        mock_structured_model.invoke.return_value = {
            "parsed": mock_output,
            "raw": mock_raw_msg,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            os.environ["GITHUB_WORKSPACE"] = str(workspace)

            # Create a temp file inside the actual central drafts directory for testing traversal
            planner_root = Path(__file__).resolve().parents[1]
            drafts_base = (planner_root / ".planner" / "drafts").resolve()
            drafts_base.mkdir(parents=True, exist_ok=True)

            temp_draft = tempfile.NamedTemporaryFile(
                dir=str(drafts_base), suffix=".md", delete=False
            )
            try:
                temp_draft.write(b"## What to build\nOriginal content.")
                temp_draft.close()

                state: RefinementState = {
                    "draft_issue_content": "## What to build\nOriginal content.",
                    "draft_issue_path": temp_draft.name,
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
                self.assertEqual(output["status"], "success")
            finally:
                if os.path.exists(temp_draft.name):
                    os.remove(temp_draft.name)
