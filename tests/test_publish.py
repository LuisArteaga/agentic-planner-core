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
        os.environ["OPENROUTER_API_KEY"] = "mock-openrouter-key"

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
        self.assertEqual(title, "0001-implement-feature")
        self.assertEqual(body, content.strip())

    @patch("requests.Session")
    @patch("planner.nodes.publish_issue.time.sleep")
    def test_publish_issue_node_success(self, mock_sleep, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock label response (label exists)
        mock_label_response = MagicMock()
        mock_label_response.status_code = 200
        mock_session.get.return_value = mock_label_response

        # Mock issue creation response
        mock_issue_response = MagicMock()
        mock_issue_response.status_code = 201
        mock_issue_response.json.return_value = {
            "number": 42,
            "html_url": "http://github.com/org/repo/issues/42",
        }
        mock_session.post.return_value = mock_issue_response

        # Create a temp file to simulate the draft
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["GITHUB_WORKSPACE"] = temp_dir
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
            mock_session.post.assert_called_once_with(
                "https://api.github.com/repos/org/repo/issues",
                json={
                    "title": "Test Issue",
                    "body": "This is content",
                    "labels": ["agent-ready"],
                },
            )
            # Verify file was deleted
            self.assertFalse(draft_file.exists())
            mock_sleep.assert_called_once()

    @patch("requests.Session")
    def test_publish_issue_node_missing_label_created(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Get label returns 404
        mock_label_response = MagicMock()
        mock_label_response.status_code = 404
        mock_session.get.return_value = mock_label_response

        # Post response
        mock_post_response = MagicMock()
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {
            "number": 42,
            "html_url": "http://github.com/org/repo/issues/42",
        }
        mock_session.post.return_value = mock_post_response

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

        # Check label creation and issue creation calls
        mock_session.post.assert_any_call(
            "https://api.github.com/repos/org/repo/labels",
            json={
                "name": "agent-ready",
                "color": "0e8a16",
                "description": "Ready for autonomous developer loop execution",
            },
        )
        mock_session.post.assert_any_call(
            "https://api.github.com/repos/org/repo/issues",
            json={
                "title": "0002-issue",
                "body": "Just body",
                "labels": ["agent-ready"],
            },
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

    @patch("requests.Session")
    def test_publish_issue_node_path_traversal_raises(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock responses to satisfy early parts of publish_issue_node
        mock_label_res = MagicMock(status_code=200)
        mock_issue_res = MagicMock(status_code=201)
        mock_issue_res.json.return_value = {"number": 1, "html_url": "url"}
        mock_session.get.return_value = mock_label_res
        mock_session.post.return_value = mock_issue_res

        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["GITHUB_WORKSPACE"] = temp_dir

            outside_path = "/etc/passwd"

            state: RefinementState = {
                "draft_issue_content": "some content",
                "draft_issue_path": outside_path,
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

            with self.assertRaises(ValueError) as context:
                with patch("planner.nodes.publish_issue.time.sleep"):
                    publish_issue_node(state)

            self.assertIn("Path traversal detected", str(context.exception))

    @patch("requests.Session")
    def test_publish_issue_node_with_central_drafts_path_succeeds(
        self, mock_session_class
    ):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock responses to satisfy early parts of publish_issue_node
        mock_label_res = MagicMock(status_code=200)
        mock_issue_res = MagicMock(status_code=201)
        mock_issue_res.json.return_value = {"number": 1, "html_url": "url"}
        mock_session.get.return_value = mock_label_res
        mock_session.post.return_value = mock_issue_res

        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["GITHUB_WORKSPACE"] = temp_dir

            # Create a temp file inside the actual central drafts directory
            planner_root = Path(__file__).resolve().parents[1]
            drafts_base = (planner_root / ".planner" / "drafts").resolve()
            drafts_base.mkdir(parents=True, exist_ok=True)

            temp_draft = tempfile.NamedTemporaryFile(
                dir=str(drafts_base), suffix=".md", delete=False
            )
            try:
                temp_draft.write(b"# Test Issue\nThis is content")
                temp_draft.close()

                state: RefinementState = {
                    "draft_issue_content": "# Test Issue\nThis is content",
                    "draft_issue_path": temp_draft.name,
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

                with patch("planner.nodes.publish_issue.time.sleep"):
                    result = publish_issue_node(state)
                self.assertEqual(result["status"], "success")
                self.assertFalse(os.path.exists(temp_draft.name))
            finally:
                if os.path.exists(temp_draft.name):
                    os.remove(temp_draft.name)


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

            # This must not raise (ADR-0005 fault isolation). The failure is
            # recorded in failed_drafts (honest partial-run signal, #56) rather
            # than an overwriteable ``status`` field.
            result = run_refinement_subgraph_node(state)
            self.assertEqual(result["current_issue_index"], 1)
            self.assertEqual(result["failed_drafts"], [str(draft_file)])
            self.assertEqual(result["succeeded_drafts"], [])


class MainRateLimitTests(unittest.TestCase):
    @patch("planner.__main__.graph")
    @patch("planner.__main__.AppConfig")
    @patch("requests.Session")
    @patch("planner.__main__.glob.glob")
    @patch("planner.__main__.Path")
    def test_main_insufficient_rate_limit_aborts(
        self, mock_path, mock_glob, mock_session_class, mock_config_class, mock_graph
    ):
        # Setup configs
        mock_config = MagicMock()
        mock_config.gh_pat = "mock-token"
        mock_config.github_repository = "org/repo"
        mock_config.github_workspace = "/workspace"
        mock_config.sources.strict = False
        mock_config.sources.domains = []
        mock_config.sources.urls = []
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

        # Mock requests.Session rate limit call
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"resources": {"core": {"remaining": 45}}}
        mock_session.get.return_value = mock_response

        from planner.__main__ import main

        # We expect sys.exit(1) to be called because of ValueError from insufficient quota
        with patch("sys.argv", ["planner", "refine"]), patch("sys.exit") as mock_exit:
            main()
            mock_exit.assert_called_once_with(1)
            mock_graph.invoke.assert_not_called()


class MainRefineStatusTests(unittest.TestCase):
    """Tests for the terminal batch-status derivation and exit code in the
    ``refine`` CLI command (#56). A partial run must print ``status: partial``,
    list the skipped drafts, and exit non-zero; a full success must print
    ``status: success`` and exit 0."""

    def _config_with_rate_limit(self, mock_config_class, remaining=100):
        mock_config = MagicMock()
        mock_config.gh_pat = "mock-token"
        mock_config.github_repository = "org/repo"
        mock_config.github_workspace = "/workspace"
        mock_config.sources.strict = False
        mock_config.sources.domains = []
        mock_config.sources.urls = []
        mock_config_class.return_value = mock_config

        # A real int ``remaining`` >= required so the rate-limit guard passes and
        # graph.invoke is reached. (Auto-MagicMock would be truthy and abort.)
        mock_session = MagicMock()
        mock_rate_response = MagicMock()
        mock_rate_response.json.return_value = {
            "resources": {"core": {"remaining": remaining}}
        }
        mock_session.get.return_value = mock_rate_response
        mock_config.get_github_session.return_value = mock_session
        return mock_config

    @patch("planner.__main__.graph")
    @patch("planner.__main__.AppConfig")
    @patch("planner.__main__.glob.glob")
    @patch("planner.__main__.Path")
    @patch("planner.cli_planning.ConsoleLoggingHandler")
    def test_main_refine_success_exits_zero(
        self, mock_handler, mock_path, mock_glob, mock_config_class, mock_graph
    ):
        self._config_with_rate_limit(mock_config_class)
        mock_glob.return_value = [
            "/workspace/.planner/drafts/org/repo/0001-issue.md",
            "/workspace/.planner/drafts/org/repo/0002-issue.md",
        ]
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        mock_graph.invoke.return_value = {
            "succeeded_drafts": [
                "/workspace/.planner/drafts/org/repo/0001-issue.md",
                "/workspace/.planner/drafts/org/repo/0002-issue.md",
            ],
            "failed_drafts": [],
        }

        from planner.__main__ import main
        import io
        import contextlib

        buf = io.StringIO()
        with patch("sys.argv", ["planner", "refine"]), patch("sys.exit") as mock_exit:
            with contextlib.redirect_stdout(buf):
                main()
            mock_exit.assert_not_called()
            mock_graph.invoke.assert_called_once()

        self.assertIn("status: success", buf.getvalue())

    @patch("planner.__main__.graph")
    @patch("planner.__main__.AppConfig")
    @patch("planner.__main__.glob.glob")
    @patch("planner.__main__.Path")
    @patch("planner.cli_planning.ConsoleLoggingHandler")
    def test_main_refine_partial_exits_nonzero(
        self, mock_handler, mock_path, mock_glob, mock_config_class, mock_graph
    ):
        self._config_with_rate_limit(mock_config_class)
        mock_glob.return_value = [
            "/workspace/.planner/drafts/org/repo/0001-issue.md",
            "/workspace/.planner/drafts/org/repo/0002-issue.md",
        ]
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        failed_path = "/workspace/.planner/drafts/org/repo/0001-issue.md"
        mock_graph.invoke.return_value = {
            "succeeded_drafts": ["/workspace/.planner/drafts/org/repo/0002-issue.md"],
            "failed_drafts": [failed_path],
        }

        from planner.__main__ import main
        import io
        import contextlib

        buf = io.StringIO()
        with patch("sys.argv", ["planner", "refine"]), patch("sys.exit") as mock_exit:
            with contextlib.redirect_stdout(buf):
                main()
            mock_exit.assert_called_once_with(1)
            mock_graph.invoke.assert_called_once()

        output = buf.getvalue()
        self.assertIn("status: partial", output)
        # The skipped draft path must be listed for the operator.
        self.assertIn(failed_path, output)
