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
        # Model returns prose synthesis; citations arrive as url_citation annotations
        mock_response.content = (
            "Based on research: LangGraph is a library for building stateful, "
            "multi-actor applications with LLMs."
        )
        mock_response.additional_kwargs = {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": "https://github.com/langchain-ai/langgraph",
                        "title": "LangGraph Docs",
                        "content": "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
                        "start_index": 0,
                        "end_index": 10,
                    },
                }
            ]
        }
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

    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_execution_with_list_content(self, mock_get_llm):
        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        # Model returns prose inside a list of content blocks; citations arrive
        # as url_citation annotations (list content must not break parsing)
        mock_response.content = [
            {
                "type": "reasoning",
                "content": [{"text": "Synthesizing search queries..."}],
            },
            {
                "type": "text",
                "text": (
                    "Based on research: LangGraph is a library for building "
                    "stateful, multi-actor applications with LLMs."
                ),
            },
        ]
        mock_response.additional_kwargs = {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": "https://github.com/langchain-ai/langgraph",
                        "title": "LangGraph Docs",
                        "content": "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
                        "start_index": 0,
                        "end_index": 10,
                    },
                }
            ]
        }
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

        # Verify results parsing
        self.assertEqual(len(output["search_results"]), 1)
        self.assertEqual(output["search_results"][0]["title"], "LangGraph Docs")
        self.assertEqual(
            output["search_results"][0]["url"],
            "https://github.com/langchain-ai/langgraph",
        )
        self.assertEqual(output["prompt_tokens"], 110)
        self.assertEqual(output["completion_tokens"], 170)

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
        mock_response.content = "Synthesized search findings."
        mock_response.additional_kwargs = {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": "https://example.com/search-result",
                        "title": "Search Result Title",
                        "content": "Search result snippet",
                        "start_index": 0,
                        "end_index": 5,
                    },
                }
            ]
        }
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
        mock_response.additional_kwargs = {}
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

    @patch("planner.nodes.web_search.AppConfig")
    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_no_annotations_sets_failure_signal(
        self, mock_get_llm, mock_config_class
    ):
        # An empty/unparseable OpenRouter response (no url_citation annotations)
        # must NOT raise JSONDecodeError and must set an honest failure signal.
        mock_config = MagicMock()
        mock_config.sources.urls = []
        mock_config_class.return_value = mock_config

        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "Prose-only response with no JSON block."
        mock_response.additional_kwargs = {}  # no annotations
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 5, "completion_tokens": 7}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.return_value = mock_response

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["arxiv.org"],
            "messages": [],
            "keywords": ["test"],
            "search_queries": ["test"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = web_search_node(state)

        # Degraded path is explicit and observable (not "success")
        self.assertEqual(output["status"], "web_search_failed")
        self.assertNotEqual(output["web_search_error"], "")
        self.assertEqual(output["search_results"], [])
        # Token usage is still tracked from the response
        self.assertEqual(output["prompt_tokens"], 5)
        self.assertEqual(output["completion_tokens"], 7)

    @patch("planner.nodes.web_search.AppConfig")
    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_invoke_exception_sets_failure_signal(
        self, mock_get_llm, mock_config_class
    ):
        mock_config = MagicMock()
        mock_config.sources.urls = []
        mock_config_class.return_value = mock_config

        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.side_effect = RuntimeError("OpenRouter timeout")

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["arxiv.org"],
            "messages": [],
            "keywords": ["test"],
            "search_queries": ["test"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = web_search_node(state)

        self.assertEqual(output["status"], "web_search_failed")
        self.assertIn("OpenRouter timeout", output["web_search_error"])
        self.assertEqual(output["search_results"], [])

    def test_extract_citations_helper(self):
        from planner.nodes.web_search import _extract_citations_from_annotations

        annotations = [
            {
                "type": "url_citation",
                "url_citation": {
                    "url": "https://example.com/a",
                    "title": "A",
                    "content": "snippet A",
                    "start_index": 0,
                    "end_index": 2,
                },
            },
            {"type": "other", "other": {"url": "https://example.com/skip"}},
            {
                "type": "url_citation",
                "url_citation": {
                    "url": "https://example.com/long",
                    "title": "Long",
                    "content": "x" * 400,
                    "start_index": 0,
                    "end_index": 2,
                },
            },
            {"type": "url_citation", "url_citation": {"title": "No URL"}},
        ]

        citations = _extract_citations_from_annotations(annotations)
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0]["title"], "A")
        self.assertEqual(citations[0]["url"], "https://example.com/a")
        self.assertEqual(citations[0]["snippet"], "snippet A")
        # Non-url_citation entries and entries without a URL are skipped
        # Over-long snippets are truncated to <= 300 chars
        self.assertTrue(len(citations[1]["snippet"]) <= 300)
        self.assertTrue(citations[1]["snippet"].endswith("..."))

        # Empty/None input is safe
        self.assertEqual(_extract_citations_from_annotations(None), [])
        self.assertEqual(_extract_citations_from_annotations([]), [])

    @patch("planner.nodes.web_search.AppConfig")
    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_multi_query_accumulates_and_dedupes(
        self, mock_get_llm, mock_config_class
    ):
        """#57: each query produces its own search call; citations are
        accumulated across queries, deduplicated by URL, and capped."""
        mock_config = MagicMock()
        mock_config.sources.urls = []  # no direct pre-fetch
        mock_config_class.return_value = mock_config

        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        def _response(citations):
            """Build a mock AIMessage carrying several url_citation annotations."""
            resp = MagicMock(spec=AIMessage)
            resp.content = "synthesis"
            resp.additional_kwargs = {
                "annotations": [
                    {
                        "type": "url_citation",
                        "url_citation": {
                            "url": url,
                            "title": title,
                            "content": "snippet",
                            "start_index": 0,
                            "end_index": 1,
                        },
                    }
                    for url, title in citations
                ]
            }
            resp.response_metadata = {
                "token_usage": {"prompt_tokens": 50, "completion_tokens": 50}
            }
            return resp

        # Query 1 returns citations a + b; query 2 returns a (dup) + c.
        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.side_effect = [
            _response([("https://example.com/a", "A"), ("https://example.com/b", "B")]),
            _response(
                [("https://example.com/a", "A-dup"), ("https://example.com/c", "C")]
            ),
        ]

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["example.com"],
            "messages": [],
            "keywords": ["q1", "q2"],
            "search_queries": ["query one", "query two"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = web_search_node(state)

        # One invoke per query (each query yields exactly one search call here).
        self.assertEqual(mock_bind.invoke.call_count, 2)
        # Tool bound once, reused across queries.
        mock_instance.bind.assert_called_once()

        urls = [r["url"] for r in output["search_results"]]
        # Deduped: 'a' appears in both queries but is kept once; total 3 unique.
        self.assertEqual(
            sorted(urls),
            ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
        )
        # Tokens accumulated across both queries (50+50 per response, 2 responses).
        self.assertEqual(output["prompt_tokens"], 100)
        self.assertEqual(output["completion_tokens"], 100)
        # Aggregate success with citations.
        self.assertEqual(output["status"], "success")
        self.assertEqual(output["web_search_error"], "")

    @patch("planner.nodes.web_search.AppConfig")
    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_multi_query_no_silent_drop_on_failure(
        self, mock_get_llm, mock_config_class
    ):
        """#57 AC: a later query failure must NOT discard earlier queries'
        results (no silent drop)."""
        mock_config = MagicMock()
        mock_config.sources.urls = []
        mock_config_class.return_value = mock_config

        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        good_response = MagicMock(spec=AIMessage)
        good_response.content = "synthesis"
        good_response.additional_kwargs = {
            "annotations": [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": "https://example.com/kept",
                        "title": "Kept",
                        "content": "snippet",
                        "start_index": 0,
                        "end_index": 1,
                    },
                }
            ]
        }
        good_response.response_metadata = {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 10}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        # Query 1 succeeds; query 2 raises (e.g. transient OpenRouter 504).
        mock_bind.invoke.side_effect = [good_response, RuntimeError("OpenRouter 504")]

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["example.com"],
            "messages": [],
            "keywords": ["q1", "q2"],
            "search_queries": ["good query", "bad query"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = web_search_node(state)

        # Earlier query's results are retained — no silent drop.
        self.assertEqual(len(output["search_results"]), 1)
        self.assertEqual(output["search_results"][0]["url"], "https://example.com/kept")
        # Partial success is honest: success status with the failure recorded.
        self.assertEqual(output["status"], "success")
        self.assertIn("OpenRouter 504", output["web_search_error"])
        # Tokens from the successful query are still tracked.
        self.assertEqual(output["prompt_tokens"], 10)

    @patch("planner.nodes.web_search.AppConfig")
    @patch("planner.nodes.web_search.get_llm")
    def test_web_search_multi_query_all_fail_is_failed(
        self, mock_get_llm, mock_config_class
    ):
        """#57: when every query fails/returns nothing, status is an honest
        web_search_failed (not a silent empty success)."""
        mock_config = MagicMock()
        mock_config.sources.urls = []
        mock_config_class.return_value = mock_config

        mock_instance = MagicMock()
        mock_get_llm.return_value = mock_instance

        empty_response = MagicMock(spec=AIMessage)
        empty_response.content = "no findings"
        empty_response.additional_kwargs = {}  # no annotations
        empty_response.response_metadata = {
            "token_usage": {"prompt_tokens": 5, "completion_tokens": 5}
        }

        mock_bind = MagicMock()
        mock_instance.bind.return_value = mock_bind
        mock_bind.invoke.side_effect = [empty_response, RuntimeError("OpenRouter 504")]

        state: RefinementState = {
            "draft_issue_content": "Some draft",
            "strict_mode": True,
            "allowed_domains": ["example.com"],
            "messages": [],
            "keywords": ["q1", "q2"],
            "search_queries": ["empty query", "bad query"],
            "search_results": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model_name": "",
            "status": "idle",
        }

        output = web_search_node(state)

        self.assertEqual(output["search_results"], [])
        self.assertEqual(output["status"], "web_search_failed")
        self.assertNotEqual(output["web_search_error"], "")

    def test_web_search_aggregated_cap_enforced(self):
        """#57 AC: the hard cap is raised to ~20 so deduped accumulation is
        not silently discarded."""
        from planner.nodes.web_search import MAX_AGGREGATED_RESULTS

        self.assertGreaterEqual(MAX_AGGREGATED_RESULTS, 15)
        self.assertLessEqual(MAX_AGGREGATED_RESULTS, 20)

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
                "succeeded_drafts": [],
                "failed_drafts": [],
            }

            from planner.refine_graph import graph

            result = graph.invoke(initial_state)

            self.assertEqual(result["current_issue_index"], 2)
            self.assertEqual(mock_subgraph.invoke.call_count, 2)
            # Per-draft outcomes are accumulated via reducers — both drafts
            # succeed, so the honest signal is succeeded_drafts populated and
            # failed_drafts empty (not an overwriteable ``status`` field, #56).
            self.assertEqual(result["succeeded_drafts"], [str(file_1), str(file_2)])
            self.assertEqual(result["failed_drafts"], [])

            # Assert that the subgraph was invoked with the propagated search_params
            called_args = mock_subgraph.invoke.call_args[0][0]
            self.assertEqual(called_args["search_params"], {"engine": "exa"})

    @patch("planner.refine_graph.refine_subgraph")
    def test_master_graph_partial_failure_is_honest(self, mock_subgraph):
        """A mid-loop draft failure must be recorded, not clobbered by a later
        success. This is the core of #56: a partial run must not look like a
        full success while leaving a draft silently unpublished."""
        # First invocation raises (draft 1 fails); second succeeds (draft 2).
        mock_subgraph.invoke.side_effect = [
            ValueError("apply_decision failed after 3 attempts"),
            {"status": "success"},
        ]

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
                "succeeded_drafts": [],
                "failed_drafts": [],
            }

            from planner.refine_graph import graph

            result = graph.invoke(initial_state)

            self.assertEqual(result["current_issue_index"], 2)
            self.assertEqual(mock_subgraph.invoke.call_count, 2)
            # ADR-0005 fault isolation: the batch continued past the failure.
            # The failed draft is recorded; the later success did NOT clobber it.
            self.assertEqual(result["failed_drafts"], [str(file_1)])
            self.assertEqual(result["succeeded_drafts"], [str(file_2)])
