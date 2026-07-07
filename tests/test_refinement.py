import os
import unittest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage
from planner.state import AgentState, RefinementState
from planner.nodes.analyze_sources import analyze_sources_node
from planner.nodes.web_search import web_search_node


class RefinementNodesTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "mock-openrouter-key"
        os.environ["GH_PAT"] = "mock-gh-pat"
        os.environ["GITHUB_REPOSITORY"] = "LuisArteaga/agentic-planner-core"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("planner.nodes.analyze_sources.get_llm")
    def test_analyze_sources_strict_mode(self, mock_get_llm):
        # Setup mock model output
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = '{"keywords": ["auth", "jwt"], "suggested_sources": ["malicious-domain.com", "other/repo"]}'
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 15, "completion_tokens": 20}
        }

        # mock_instance.bind().invoke()
        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.return_value = mock_response

        # Test state
        state: RefinementState = {
            "draft_issue_content": "Implement auth token mechanism.",
            "strict_mode": True,
            "allowed_domains": ["arxiv.org", "github.com/langchain-ai/langgraph"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = analyze_sources_node(state)

        # In strict: true, we ignore suggested_sources
        self.assertEqual(output["keywords"], ["auth", "jwt"])
        self.assertEqual(
            output["allowed_domains"],
            ["arxiv.org", "github.com/langchain-ai/langgraph"],
        )
        self.assertEqual(output["prompt_tokens"], 15)
        self.assertEqual(output["completion_tokens"], 20)

    @patch("planner.nodes.analyze_sources.get_llm")
    def test_analyze_sources_non_strict_mode(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = '{"keywords": ["auth"], "suggested_sources": ["example.org", "langchain-ai/langgraph", "github.com/SWE-agent/SWE-agent"]}'
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 15}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.return_value = mock_response

        state: RefinementState = {
            "draft_issue_content": "Some draft content",
            "strict_mode": False,
            "allowed_domains": ["arxiv.org"],
            "messages": [],
            "keywords": [],
            "search_queries": [],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = analyze_sources_node(state)

        # In strict: false, suggested sources are normalized and merged into allowed_domains
        self.assertEqual(output["keywords"], ["auth"])
        self.assertIn("example.org", output["allowed_domains"])
        # Repository names should be prefixed with github.com/
        self.assertIn("github.com/langchain-ai/langgraph", output["allowed_domains"])
        self.assertIn("github.com/swe-agent/swe-agent", output["allowed_domains"])

    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_execution(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        # Model returns JSON block of results as instructed
        mock_response.content = (
            "Based on research:\n"
            "```json\n"
            "[\n"
            "  {\n"
            '    "title": "LangGraph Docs",\n'
            '    "url": "https://github.com/langchain-ai/langgraph",\n'
            '    "snippet": "LangGraph is a library for building stateful, multi-actor applications with LLMs."\n'
            "  }\n"
            "]\n"
            "```"
        )
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 150}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.return_value = mock_response

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["github.com/langchain-ai/langgraph"],
            "messages": [],
            "keywords": ["langgraph"],
            "search_queries": ["langgraph"],
            "search_results": [],
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "model_name": "google/gemini-2.5-flash",
            "status": "success",
        }

        output = web_search_node(state)

        # Verify results parsing and tool binding
        self.assertEqual(len(output["search_results"]), 1)
        self.assertEqual(output["search_results"][0]["title"], "LangGraph Docs")
        self.assertEqual(
            output["search_results"][0]["url"],
            "https://github.com/langchain-ai/langgraph",
        )
        self.assertEqual(output["prompt_tokens"], 110)  # 10 + 100
        self.assertEqual(output["completion_tokens"], 170)  # 20 + 150

        # Verify tool binding was called with correct parameters via bind()
        mock_instance.bind.assert_called_once()
        _, kwargs = mock_instance.bind.call_args
        tool_list = kwargs.get("tools", [])
        self.assertEqual(tool_list[0]["type"], "openrouter:web_search")
        self.assertEqual(
            tool_list[0]["parameters"]["allowed_domains"],
            ["github.com/langchain-ai/langgraph"],
        )

    @patch("planner.nodes.web_search.fetch_allowed_url")
    @patch("planner.nodes.web_search.AppConfig")
    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_with_pre_fetched_urls(
        self, mock_get_llm, mock_config_class, mock_fetch
    ):
        # 1. Mock AppConfig to return custom urls
        mock_config = MagicMock()
        mock_config.sources.urls = ["https://python.langchain.com/docs/intro"]
        mock_config_class.return_value = mock_config

        # 2. Mock fetch_allowed_url to return a mock document
        mock_fetch.return_value = {
            "title": "LangChain Intro",
            "url": "https://python.langchain.com/docs/intro",
            "snippet": "Pre-fetched doc content",
        }

        # 3. Mock ChatOpenAI and response
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = (
            "```json\n"
            "[\n"
            "  {\n"
            '    "title": "Search Result Title",\n'
            '    "url": "https://example.com/search-result",\n'
            '    "snippet": "Search result snippet"\n'
            "  }\n"
            "]\n"
            "```"
        )
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 10}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.return_value = mock_response

        # 4. Define refinement state
        state: RefinementState = {
            "draft_issue_content": "Test draft",
            "strict_mode": True,
            "allowed_domains": ["example.com"],
            "messages": [],
            "keywords": ["test"],
            "search_queries": ["test"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "success",
        }

        # 5. Execute web_search_node
        output = web_search_node(state)

        # 6. Assertions
        mock_fetch.assert_called_once_with(
            mock_config, "https://python.langchain.com/docs/intro"
        )
        self.assertEqual(len(output["search_results"]), 2)
        self.assertEqual(output["search_results"][0]["title"], "LangChain Intro")
        self.assertEqual(
            output["search_results"][0]["snippet"], "Pre-fetched doc content"
        )
        self.assertEqual(output["search_results"][1]["title"], "Search Result Title")

    def test_analyze_sources_strict_empty_domains_raises(self):
        state: RefinementState = {
            "draft_issue_content": "Some draft",
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
        }
        with self.assertRaises(ValueError):
            analyze_sources_node(state)

    def test_web_search_strict_empty_domains_raises(self):
        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": [],
            "messages": [],
            "keywords": ["test"],
            "search_queries": ["test"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }
        with self.assertRaises(ValueError):
            web_search_node(state)

    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_execution_with_custom_params(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "[]"
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 15}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.return_value = mock_response

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["arxiv.org"],
            "search_params": {
                "engine": "exa",
                "search_context_size": "medium",
                "max_results": 5,
                "max_total_results": 15,
                "excluded_domains": ["reddit.com"],
            },
            "messages": [],
            "keywords": ["test"],
            "search_queries": ["test"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        _ = web_search_node(state)

        # Verify tool binding was called with correct parameters
        mock_instance.bind.assert_called_once()
        _, kwargs = mock_instance.bind.call_args
        tool_list = kwargs.get("tools", [])
        self.assertEqual(tool_list[0]["type"], "openrouter:web_search")

        tool_params = tool_list[0]["parameters"]
        self.assertEqual(tool_params["engine"], "exa")
        self.assertEqual(tool_params["search_context_size"], "medium")
        self.assertEqual(tool_params["max_results"], 5)
        self.assertEqual(tool_params["max_total_results"], 15)
        self.assertEqual(tool_params["allowed_domains"], ["arxiv.org"])
        self.assertEqual(tool_params["excluded_domains"], ["reddit.com"])

    @patch("planner.refine_graph.refine_subgraph")
    def test_master_graph_iteration(self, mock_subgraph):
        mock_subgraph.invoke.return_value = {"status": "success"}

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            file_1 = Path(temp_dir) / "issue1.md"
            file_2 = Path(temp_dir) / "issue2.md"
            file_1.write_text("Draft issue 1 content", encoding="utf-8")
            file_2.write_text("Draft issue 2 content", encoding="utf-8")

            initial_state: AgentState = {
                "draft_issues": [str(file_1), str(file_2)],
                "current_issue_index": 0,
                "strict_mode": False,
                "allowed_domains": [],
                "search_params": {"engine": "exa"},
                "status": "idle",
            }

            from planner.refine_graph import graph

            result = graph.invoke(initial_state)

            self.assertEqual(result["current_issue_index"], 2)
            self.assertEqual(result["status"], "success")
            self.assertEqual(mock_subgraph.invoke.call_count, 2)

            # Assert that the subgraph was invoked with the propagated search_params
            called_args = mock_subgraph.invoke.call_args[0][0]
            self.assertEqual(called_args["search_params"], {"engine": "exa"})
