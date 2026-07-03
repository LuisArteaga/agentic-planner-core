import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

from planner.nodes.publish_issue import extract_title_and_body, publish_issue_node
from planner.state import RefinementState, AgentState
from planner.refine_graph import run_refinement_subgraph_node


class PublishNodeTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["GH_PAT"] = "mock-token"
        os.environ["GITHUB_REPOSITORY"] = "org/repo"
        os.environ["AGENT_LABEL_READY"] = "agent-ready"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_extract_title_and_body_with_h1(self):
        content = "# My Issue Title\n\nSome body text here.\n- List item"
        title, body = extract_title_and_body(content, "/path/to/0001-issue-title.md")
        self.assertEqual(title, "My Issue Title")
        self.assertEqual(body, "Some body text here.\n- List item")

    def test_extract_title_and_body_fallback_to_filename(self):
        content = "Some body text here without H1 header.\n- List item"
        title, body = extract_title_and_body(
            content, "/path/to/0001-implement-feature.md"
        )
        self.assertEqual(title, "Implement Feature")
        self.assertEqual(body, content.strip())

    @patch("planner.nodes.publish_issue.Github")
    @patch("planner.nodes.publish_issue.time.sleep")
    def test_publish_issue_node_success(self, mock_sleep, mock_github_class):
        # Setup mocks for PyGithub
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        # Mock label checking
        mock_label = MagicMock()
        mock_repo.get_label.return_value = mock_label

        # Mock issue creation
        mock_issue = MagicMock()
        mock_issue.number = 42
        mock_issue.html_url = "http://github.com/org/repo/issues/42"
        mock_repo.create_issue.return_value = mock_issue

        # Create a temp file to simulate the draft
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_file = Path(temp_dir) / "0001-test-issue.md"
            draft_file.write_text("# Test Issue\nThis is content", encoding="utf-8")

            state: RefinementState = {
                "draft_issue_content": "# Test Issue\nThis is content",
                "draft_issue_path": str(draft_file),
                "strict_mode": False,
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

            result = publish_issue_node(state)

            self.assertEqual(result["status"], "success")
            mock_repo.create_issue.assert_called_once_with(
                title="Test Issue",
                body="This is content",
                labels=[mock_label],
            )
            # Verify file was deleted
            self.assertFalse(draft_file.exists())
            mock_sleep.assert_called_once()

    @patch("planner.nodes.publish_issue.Github")
    def test_publish_issue_node_missing_label_created(self, mock_github_class):
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        # Simulating that get_label raises Exception
        mock_repo.get_label.side_effect = Exception("Label not found")
        mock_label = MagicMock()
        mock_repo.create_label.return_value = mock_label

        mock_issue = MagicMock()
        mock_repo.create_issue.return_value = mock_issue

        state: RefinementState = {
            "draft_issue_content": "Just body",
            "draft_issue_path": "0002-issue.md",
            "strict_mode": False,
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

        # Patch time.sleep and os.path.exists (to avoid deleting real file)
        with (
            patch("planner.nodes.publish_issue.time.sleep"),
            patch("planner.nodes.publish_issue.os.path.exists", return_value=False),
        ):
            publish_issue_node(state)

        mock_repo.create_label.assert_called_once_with(
            name="agent-ready",
            color="0e8a16",
            description="Ready for autonomous developer loop execution",
        )
        mock_repo.create_issue.assert_called_once_with(
            title="Issue",
            body="Just body",
            labels=[mock_label],
        )

    def test_publish_issue_node_missing_token_raises(self):
        del os.environ["GH_PAT"]
        if "GH_TOKEN" in os.environ:
            del os.environ["GH_TOKEN"]

        state: RefinementState = {
            "draft_issue_content": "content",
            "draft_issue_path": "path",
            "strict_mode": False,
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
        with self.assertRaises(ValueError):
            publish_issue_node(state)


class MasterGraphErrorHandlingTests(unittest.TestCase):
    @patch("planner.refine_graph.refine_subgraph")
    def test_master_graph_node_continues_on_subgraph_error(self, mock_subgraph):
        # Simulating that subgraph invoke raises an exception
        mock_subgraph.invoke.side_effect = Exception("Subgraph crashed!")

        with tempfile.TemporaryDirectory() as temp_dir:
            draft_file = Path(temp_dir) / "0001-issue.md"
            draft_file.write_text("content", encoding="utf-8")

            state: AgentState = {
                "draft_issues": [str(draft_file)],
                "current_issue_index": 0,
                "strict_mode": False,
                "allowed_domains": [],
                "status": "idle",
            }

            # This should not raise an exception, but return status = "failed"
            result = run_refinement_subgraph_node(state)
            self.assertEqual(result["current_issue_index"], 1)
            self.assertEqual(result["status"], "failed")


class MainRateLimitTests(unittest.TestCase):
    @patch("planner.__main__.graph")
    @patch("planner.__main__.AppConfig")
    @patch("github.Github")
    @patch("planner.__main__.glob.glob")
    @patch("planner.__main__.Path")
    def test_main_insufficient_rate_limit_aborts(
        self, mock_path, mock_glob, mock_github_class, mock_config_class, mock_graph
    ):
        # Setup configs
        mock_config = MagicMock()
        mock_config.gh_pat = "mock-token"
        mock_config.github_repository = "org/repo"
        mock_config.github_workspace = "/workspace"
        mock_config.sources.strict = False
        mock_config.sources.domains = []
        mock_config.sources.repositories = []
        mock_config_class.return_value = mock_config

        # 2 draft files
        mock_glob.return_value = [
            "/workspace/.planner/drafts/org/repo/0001-issue.md",
            "/workspace/.planner/drafts/org/repo/0002-issue.md",
        ]
        # Mock path exists
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        # Mock Github
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github
        # Simulate remaining rate limit: 2 files * 3 = 6 needed, but we check max(50, 6) = 50. Let's return 45.
        mock_rate_limit = MagicMock()
        mock_rate_limit.core.remaining = 45
        mock_github.get_rate_limit.return_value = mock_rate_limit

        from planner.__main__ import main

        # We expect sys.exit(1) to be called because of ValueError from insufficient quota
        with patch("sys.argv", ["planner", "refine"]), patch("sys.exit") as mock_exit:
            main()
            mock_exit.assert_called_once_with(1)
            mock_graph.invoke.assert_not_called()
