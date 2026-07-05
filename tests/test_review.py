import os
import sys
import json
import urllib
import urllib.error
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.review import main  # noqa: E402


def make_mock_openrouter_response(content):
    response_data = {"choices": [{"message": {"content": content}}]}
    return json.dumps(response_data)


def make_mock_response(content, status=200):
    m = MagicMock()
    m.status = status
    m.read.return_value = content.encode("utf-8")
    m.__enter__.return_value = m
    m.__exit__.return_value = None
    return m


@pytest.fixture
def mock_env():
    old_env = dict(os.environ)
    os.environ["PR_NUMBER"] = "42"
    os.environ["GH_PAT"] = "test-token"
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
    yield
    os.environ.clear()
    os.environ.update(old_env)


@patch("requests.Session.get")
@patch("requests.Session.post")
@patch("urllib.request.urlopen")
@patch(
    "sys.stdin",
    new_callable=lambda: StringIO(
        "diff --git a/file.py b/file.py\n+class HubCustomer:\n+    pass"
    ),
)
def test_review_all_pass(mock_stdin, mock_urlopen, mock_post, mock_get, mock_env):
    # Setup mocks
    # We expect 4 calls to OpenRouter (syntax_lint, test_coverage, architecture, security)
    # and 3 calls to GitHub API (Get PR, Get User, Post Review)

    syntax_resp = make_mock_openrouter_response(
        "<reasoning>All syntax ok</reasoning>\n<findings></findings>"
    )
    test_resp = make_mock_openrouter_response(
        "<reasoning>Tests ok</reasoning>\n<findings></findings>"
    )
    arch_resp = make_mock_openrouter_response(
        "<reasoning>Arch ok</reasoning>\n<findings></findings>"
    )
    sec_resp = make_mock_openrouter_response(
        "<reasoning>Security ok</reasoning>\n<findings></findings>"
    )

    mock_urlopen.side_effect = [
        make_mock_response(syntax_resp),
        make_mock_response(test_resp),
        make_mock_response(arch_resp),
        make_mock_response(sec_resp),
    ]

    mock_get.side_effect = [
        MagicMock(
            json=lambda: {"user": {"login": "developer"}}, raise_for_status=lambda: None
        ),
        MagicMock(
            json=lambda: {"login": "reviewer-bot"}, raise_for_status=lambda: None
        ),
    ]
    mock_post.return_value = MagicMock(
        json=lambda: {"status": "success"}, raise_for_status=lambda: None
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0
    assert mock_urlopen.call_count == 4
    assert mock_get.call_count == 2
    assert mock_post.call_count == 1

    post_call_args = mock_post.call_args
    payload = post_call_args[1]["json"]
    assert payload["event"] == "APPROVE"
    assert "### 🤖 Automated LLM PR Judges Summary" in payload["body"]
    assert "✅ PASS" in payload["body"]


@patch("requests.Session.get")
@patch("requests.Session.post")
@patch("urllib.request.urlopen")
@patch(
    "sys.stdin",
    new_callable=lambda: StringIO(
        "diff --git a/file.py b/file.py\n+class HubCustomer:\n+    pass"
    ),
)
def test_review_syntax_lint_fail_fast(
    mock_stdin, mock_urlopen, mock_post, mock_get, mock_env
):
    syntax_resp = make_mock_openrouter_response(
        "<reasoning>Naming convention HubCustomer failed</reasoning>\n"
        "<findings>\n"
        '{"severity": "error", "message": "[Q3] Class HubCustomer violates prefix rule"}\n'
        "</findings>"
    )

    mock_urlopen.side_effect = [
        make_mock_response(syntax_resp),
    ]

    mock_get.side_effect = [
        MagicMock(
            json=lambda: {"user": {"login": "developer"}}, raise_for_status=lambda: None
        ),
        MagicMock(
            json=lambda: {"login": "reviewer-bot"}, raise_for_status=lambda: None
        ),
    ]
    mock_post.return_value = MagicMock(
        json=lambda: {"status": "success"}, raise_for_status=lambda: None
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    assert mock_urlopen.call_count == 1
    assert mock_get.call_count == 2
    assert mock_post.call_count == 1

    post_call_args = mock_post.call_args
    payload = post_call_args[1]["json"]
    assert payload["event"] == "REQUEST_CHANGES"

    body = payload["body"]
    assert "❌ FAIL" in body
    assert "⏭️ SKIPPED" in body
    assert "Q3" in body and "❌ FAIL" in body


@patch("scripts.review.time.sleep")
@patch("requests.Session.get")
@patch("requests.Session.post")
@patch("urllib.request.urlopen")
@patch(
    "sys.stdin",
    new_callable=lambda: StringIO(
        "diff --git a/file.py b/file.py\n+class HubCustomer:\n+    pass"
    ),
)
def test_review_api_error_resilience(
    mock_stdin, mock_urlopen, mock_post, mock_get, mock_sleep, mock_env
):
    syntax_resp = make_mock_openrouter_response(
        "<reasoning>Syntax OK</reasoning>\n<findings></findings>"
    )
    arch_resp = make_mock_openrouter_response(
        "<reasoning>Arch OK</reasoning>\n<findings></findings>"
    )
    sec_resp = make_mock_openrouter_response(
        "<reasoning>Security OK</reasoning>\n<findings></findings>"
    )

    call_count = [0]

    def urlopen_side_effect(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        if "chat/completions" in url:
            if call_count[0] == 0:
                call_count[0] += 1
                return make_mock_response(syntax_resp)
            elif call_count[0] == 1:
                call_count[0] += 1
                raise urllib.error.URLError("API Timeout or Rate Limit")
            elif call_count[0] == 2:
                call_count[0] += 1
                return make_mock_response(arch_resp)
            elif call_count[0] == 3:
                call_count[0] += 1
                return make_mock_response(sec_resp)

    mock_urlopen.side_effect = urlopen_side_effect

    mock_get.side_effect = [
        MagicMock(
            json=lambda: {"user": {"login": "developer"}}, raise_for_status=lambda: None
        ),
        MagicMock(
            json=lambda: {"login": "reviewer-bot"}, raise_for_status=lambda: None
        ),
    ]
    mock_post.return_value = MagicMock(
        json=lambda: {"status": "success"}, raise_for_status=lambda: None
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1

    post_call_args = mock_post.call_args
    payload = post_call_args[1]["json"]
    assert payload["event"] == "REQUEST_CHANGES"

    body = payload["body"]
    assert "Syntax & Konformität" in body
    assert "Test-Validierung" in body
    assert "Architektur-Compliance" in body
    assert "Deep Security Audit" in body
    assert "Check failed to run: LLM review failed after retries." in body
