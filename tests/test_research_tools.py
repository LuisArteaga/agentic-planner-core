import unittest
from unittest.mock import patch, MagicMock
import json
from planner.config import AppConfig
from planner.tools.research import (
    extract_github_repo_from_url,
    is_domain_allowed,
    is_url_allowed,
    is_repo_allowed,
    create_fetch_url_tool,
    create_github_read_file_tool,
    create_github_list_issues_tool,
    create_github_get_releases_tool,
    fetch_allowed_url,
)


class ResearchToolsTests(unittest.TestCase):
    def setUp(self):
        # Create a mock AppConfig
        self.config = MagicMock(spec=AppConfig)
        self.config.sources = MagicMock()
        self.config.sources.strict = True
        self.config.sources.domains = ["example.com", "arxiv.org"]
        self.config.sources.urls = [
            "https://github.com/langchain-ai/langgraph",
            "https://python.langchain.com/docs/intro",
        ]
        self.config.github_repository = "LuisArteaga/agentic-planner-core"

    def test_extract_github_repo_from_url(self):
        self.assertEqual(
            extract_github_repo_from_url(
                "https://github.com/owner/repo/blob/main/file.py"
            ),
            "owner/repo",
        )
        self.assertEqual(
            extract_github_repo_from_url("http://github.com/owner/repo"), "owner/repo"
        )
        self.assertEqual(
            extract_github_repo_from_url("github.com/owner/repo"), "owner/repo"
        )
        self.assertIsNone(
            extract_github_repo_from_url("https://example.com/owner/repo")
        )

    def test_is_domain_allowed(self):
        # Strict mode
        self.assertTrue(is_domain_allowed(self.config, "example.com"))
        self.assertTrue(is_domain_allowed(self.config, "arxiv.org"))
        self.assertFalse(is_domain_allowed(self.config, "google.com"))

        # Non-strict mode
        self.config.sources.strict = False
        self.assertTrue(is_domain_allowed(self.config, "google.com"))

    def test_is_url_allowed(self):
        self.config.sources.strict = True
        # Exact match in urls list
        self.assertTrue(
            is_url_allowed(self.config, "https://python.langchain.com/docs/intro")
        )
        # Domain match in domains list
        self.assertTrue(is_url_allowed(self.config, "https://example.com/path/to/doc"))
        # Not allowed
        self.assertFalse(is_url_allowed(self.config, "https://google.com"))

        # Non-strict mode
        self.config.sources.strict = False
        self.assertTrue(is_url_allowed(self.config, "https://google.com"))

    def test_is_repo_allowed(self):
        self.config.sources.strict = True
        # Target repository always allowed
        self.assertTrue(
            is_repo_allowed(self.config, "LuisArteaga/agentic-planner-core")
        )
        # Extracted from urls list
        self.assertTrue(is_repo_allowed(self.config, "langchain-ai/langgraph"))
        # Not allowed
        self.assertFalse(is_repo_allowed(self.config, "some-other/repo"))

        # Non-strict mode
        self.config.sources.strict = False
        self.assertTrue(is_repo_allowed(self.config, "some-other/repo"))

    @patch("planner.tools.research.requests.get")
    def test_fetch_url_content_tool(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Hello World"
        mock_get.return_value = mock_response

        fetch_tool = create_fetch_url_tool(self.config)

        # Allowed URL
        result = fetch_tool.invoke({"url": "https://example.com"})
        self.assertEqual(result, "Hello World")

        # Disallowed URL under strict mode
        result = fetch_tool.invoke({"url": "https://restricted.com"})
        self.assertIn("restricted", result)

    @patch("planner.tools.research.base64.b64decode")
    def test_read_github_file_tool(self, mock_b64decode):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "encoding": "base64",
            "content": "bW9jayBjb250ZW50",
        }
        mock_session.get.return_value = mock_response
        self.config.get_github_session.return_value = mock_session
        mock_b64decode.return_value = b"mock content"

        read_file_tool = create_github_read_file_tool(self.config)

        # Allowed repo
        result = read_file_tool.invoke(
            {"repo": "langchain-ai/langgraph", "path": "README.md"}
        )
        self.assertEqual(result, "mock content")

        # Disallowed repo under strict mode
        result = read_file_tool.invoke({"repo": "restricted/repo", "path": "README.md"})
        self.assertIn("restricted", result)

    def test_list_github_issues_tool(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"number": 1, "title": "Bug A", "state": "open", "user": {"login": "user1"}}
        ]
        mock_session.get.return_value = mock_response
        self.config.get_github_session.return_value = mock_session

        list_issues_tool = create_github_list_issues_tool(self.config)

        result = list_issues_tool.invoke({"repo": "langchain-ai/langgraph"})
        data = json.loads(result)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Bug A")

    def test_get_github_releases_tool(self):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v1.0.0",
                "name": "Initial Release",
                "published_at": "2026-07-07T00:00:00Z",
            }
        ]
        mock_session.get.return_value = mock_response
        self.config.get_github_session.return_value = mock_session

        get_releases_tool = create_github_get_releases_tool(self.config)

        result = get_releases_tool.invoke({"repo": "langchain-ai/langgraph"})
        data = json.loads(result)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["tag_name"], "v1.0.0")

    @patch("planner.tools.research.requests.get")
    def test_fetch_allowed_url_helper(self, mock_get):
        # Mock non-GitHub HTTP request
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Some text</body></html>"
        mock_get.return_value = mock_response

        res = fetch_allowed_url(self.config, "https://example.com")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["title"], "Direct URL: https://example.com")
        self.assertIn("Some text", res["snippet"])
