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

    # Hidden ADR-0015 verdict block (parsed by the pr-feedback-loop skill).
    body = payload["body"]
    assert "<!-- llm-pr-review-verdicts" in body
    assert "syntax_lint: PASS" in body
    assert "test_coverage: PASS" in body
    assert "architecture: PASS" in body
    assert "security: PASS" in body
    assert body.rstrip().endswith("-->")


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

    # Hidden ADR-0015 verdict block reflects the fail-fast state.
    assert "<!-- llm-pr-review-verdicts" in body
    assert "syntax_lint: FAIL" in body
    assert "test_coverage: SKIPPED" in body
    assert "architecture: SKIPPED" in body
    assert "security: SKIPPED" in body


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


@patch("requests.Session.get")
@patch("requests.Session.post")
def test_submit_github_review_author_comment(mock_post, mock_get, mock_env):
    # Test submit_github_review when current_user == pr_author
    # It must map the event to COMMENT instead of REQUEST_CHANGES/APPROVE

    mock_get.side_effect = [
        # Get PR (returns user.login = developer)
        MagicMock(
            json=lambda: {"user": {"login": "developer"}}, raise_for_status=lambda: None
        ),
        # Get Current User (returns login = developer)
        MagicMock(json=lambda: {"login": "developer"}, raise_for_status=lambda: None),
    ]
    mock_post.return_value = MagicMock(
        json=lambda: {"status": "success"}, raise_for_status=lambda: None
    )

    from scripts.review import submit_github_review

    submit_github_review(42, "approve", "This is some review body content")

    assert mock_get.call_count == 2
    assert mock_post.call_count == 1

    post_call_args = mock_post.call_args
    payload = post_call_args[1]["json"]
    # Even though we requested 'approve', since current_user == pr_author, it maps to 'COMMENT'
    assert payload["event"] == "COMMENT"
    assert payload["body"] == "This is some review body content"


@patch("urllib.request.urlopen")
def test_call_openrouter_api_timeout(mock_urlopen):
    """call_openrouter_api should pass the timeout parameter to urlopen."""
    from scripts.review import call_openrouter_api

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"choices": []}'
    mock_urlopen.return_value.__enter__.return_value = mock_response

    call_openrouter_api(
        model="test-model",
        messages=[],
        api_key="test-key",
        timeout=45,
    )

    # Assert urllib.request.urlopen was called with timeout=45
    called_args = mock_urlopen.call_args
    assert called_args[1]["timeout"] == 45


@patch("urllib.request.urlopen")
def test_call_llm_for_review_empty_response_content(mock_urlopen):
    """call_llm_for_review should raise Exception on empty response content."""
    from scripts.review import call_llm_for_review

    # Return 200 but with empty choices list or empty content message
    empty_resp = '{"choices": [{"message": {"role": "assistant", "content": ""}}]}'
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = empty_resp.encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    # It should raise an Exception because choices content is empty/blank
    with pytest.raises(Exception, match="OpenRouter response message content is empty"):
        call_llm_for_review("syntax_lint", "system prompt", "diff content", "api_key")


def test_review_needs_review_blocks_merge(mock_env):
    """A 'Needs Review' verdict must block the merge (ADR-0014).

    Uses `with patch(...)` context managers (no @decorators) to keep the diff
    free of '@' tokens that the test_coverage judge receives as '[EMAIL]'.
    Each judge returns content with no <reasoning>/<findings> tags ->
    "Needs Review" verdict -> status NEEDS REVIEW -> overall_failed ->
    request-changes -> exit 1.
    """
    # Content present but no <reasoning>/<findings> tags -> "Needs Review".
    no_tag_resp = make_mock_openrouter_response("I cannot review this unclear diff.")
    urlopen_side = [make_mock_response(no_tag_resp) for _ in range(4)]

    with (
        patch(
            "sys.stdin",
            new_callable=lambda: StringIO("diff --git a/f.py b/f.py\n+x=1\n"),
        ),
        patch("urllib.request.urlopen", side_effect=urlopen_side),
        patch(
            "requests.Session.get",
            side_effect=[
                MagicMock(
                    json=lambda: {"user": {"login": "developer"}},
                    raise_for_status=lambda: None,
                ),
                MagicMock(
                    json=lambda: {"login": "reviewer-bot"},
                    raise_for_status=lambda: None,
                ),
            ],
        ),
        patch("requests.Session.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(
            json=lambda: {"status": "success"}, raise_for_status=lambda: None
        )
        with pytest.raises(SystemExit) as excinfo:
            main()

    assert excinfo.value.code == 1

    payload = mock_post.call_args[1]["json"]
    assert payload["event"] == "REQUEST_CHANGES"

    body = payload["body"]
    assert "⚠️ NEEDS REVIEW" in body
    assert "syntax_lint: NEEDS REVIEW" in body
    assert "test_coverage: NEEDS REVIEW" in body
    assert "security: NEEDS REVIEW" in body
    assert "architecture: NEEDS REVIEW" in body


# --- ADR-0011: enclosing-function context enrichment ---------------------


def test_parse_diff_hunks_extracts_file_and_target_range():
    """Hunk extraction: file path from `+++ b/`, target range from `@@ +n,nc @@`."""
    from scripts.review import _parse_diff_hunks

    diff = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "--- a/pkg/mod.py\n"
        "+++ b/pkg/mod.py\n"
        "@@ -10,3 +12,4 @@ def process():\n"
        " ctx\n"
        "+added\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    assert _parse_diff_hunks(diff) == [
        ("pkg/mod.py", 12, 4),
        ("README.md", 1, 1),
    ]


def test_parse_diff_hunks_ignores_entries_without_hunks():
    from scripts.review import _parse_diff_hunks

    # Pure rename / no `@@` hunks -> nothing extracted.
    diff = "diff --git a/old.py b/new.py\nrename from old.py\nrename to new.py\n"
    assert _parse_diff_hunks(diff) == []
    # No preceding `+++ b/` header -> no file associated with the hunk.
    assert _parse_diff_hunks("@@ -1,1 +1,1 @@\n+x\n") == []


def test_find_enclosing_function_finds_innermost_def():
    from scripts.review import _find_enclosing_function

    lines = [
        "def first():",
        "    a = 1",
        "    return a",
        "",
        "def second():",
        "    b = 2",
        "    return b",
        "",
        "def third():",
        "    c = 3",
    ]
    # Hunk inside `second` (b = 2) -> walk up finds `second`, down finds
    # `third` (next def at the same indent).
    assert _find_enclosing_function(lines, 5, 5) == (4, 8, "second")
    # Hunk inside `first` -> down boundary is `second`.
    assert _find_enclosing_function(lines, 1, 1) == (0, 4, "first")
    # Hunk inside `third` -> no following def -> body runs to EOF.
    assert _find_enclosing_function(lines, 9, 9) == (8, 10, "third")


def test_find_enclosing_function_module_level_returns_none():
    from scripts.review import _find_enclosing_function

    lines = ["import os", "CONST = 1", "", "def f():", "    pass"]
    # Module-level change (CONST = 1) has no enclosing def/class.
    assert _find_enclosing_function(lines, 1, 1) is None
    # Empty input is safe.
    assert _find_enclosing_function([], 0, 0) is None


def test_truncate_context_respects_per_file_limit():
    from scripts.review import _truncate_context, _CONTEXT_CHAR_LIMIT_PER_FILE

    short = "x" * 100
    assert _truncate_context(short) == short

    at_limit = "x" * _CONTEXT_CHAR_LIMIT_PER_FILE
    assert _truncate_context(at_limit) == at_limit

    over = "y" * (_CONTEXT_CHAR_LIMIT_PER_FILE + 50)
    result = _truncate_context(over)
    assert result.endswith("\n[... truncated ...]")
    assert result[:_CONTEXT_CHAR_LIMIT_PER_FILE] == "y" * _CONTEXT_CHAR_LIMIT_PER_FILE


def test_enrich_diff_appends_enclosing_function_context(tmp_path):
    from scripts.review import enrich_diff_with_function_context

    src = tmp_path / "src" / "mod.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        "def is_url_allowed(url):\n"
        "    return True\n"
        "\n"
        "def process(url):\n"
        "    return is_url_allowed(url)\n",
        encoding="utf-8",
    )
    diff = (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -4,2 +4,2 @@\n"
        " def process(url):\n"
        "-    return is_url_allowed(url)\n"
        "+    return is_url_allowed(url) or True\n"
    )
    result = enrich_diff_with_function_context(diff, str(tmp_path))

    assert result.startswith(diff)
    assert "=== ENCLOSING FUNCTION CONTEXT ===" in result
    assert "=== CONTEXT: src/mod.py process ===" in result
    # The full body (not just the changed line) is included.
    assert "return is_url_allowed(url) or True" in result
    # The untouched sibling def is NOT emitted as its own context block.
    assert "=== CONTEXT: src/mod.py is_url_allowed ===" not in result


def test_enrich_diff_ip_address_regression(tmp_path):
    """INC-001 regression: two distinct IPs in the same function must both be
    visible in the enriched context so the architecture judge no longer
    treats them as a duplicate assertion (which caused the false positive
    when only the ±3-line diff was visible)."""
    from scripts.review import enrich_diff_with_function_context

    src = tmp_path / "tests" / "test_fetch.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        "class TestFetch:\n"
        "    def test_ssrf_protection(self):\n"
        "        # loopback must be blocked\n"
        '        self.assertFalse(is_url_allowed("http://127.0.0.1"))\n'
        "        # aws metadata must be blocked\n"
        '        self.assertFalse(is_url_allowed("http://169.254.169.254"))\n'
        "        # public host is allowed\n"
        '        self.assertTrue(is_url_allowed("https://example.com"))\n',
        encoding="utf-8",
    )
    diff = (
        "diff --git a/tests/test_fetch.py b/tests/test_fetch.py\n"
        "--- a/tests/test_fetch.py\n"
        "+++ b/tests/test_fetch.py\n"
        "@@ -4,3 +4,3 @@\n"
        "        # loopback must be blocked\n"
        '-        self.assertFalse(is_url_allowed("http://127.0.0.1"))\n'
        '+        self.assertFalse(is_url_allowed("http://127.0.0.1", strict=True))\n'
        "        # aws metadata must be blocked\n"
    )
    result = enrich_diff_with_function_context(diff, str(tmp_path))

    # The enclosing method is fully included ...
    assert "=== CONTEXT: tests/test_fetch.py test_ssrf_protection ===" in result
    # ... and both distinct IP addresses are visible to the judge.
    assert "127.0.0.1" in result
    assert "169.254.169.254" in result
    # The class is not emitted as a separate context block.
    assert "=== CONTEXT: tests/test_fetch.py TestFetch ===" not in result


def test_enrich_diff_skips_non_python_and_missing_files(tmp_path):
    from scripts.review import enrich_diff_with_function_context

    # A Python hunk whose file does not exist on disk + a non-Python hunk:
    # both must be skipped without crashing, and the diff returned unchanged.
    diff = (
        "diff --git a/missing.py b/missing.py\n"
        "--- a/missing.py\n"
        "+++ b/missing.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n+ b\n"
        "diff --git a/notes.md b/notes.md\n"
        "--- a/notes.md\n"
        "+++ b/notes.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n+ b\n"
    )
    assert enrich_diff_with_function_context(diff, str(tmp_path)) == diff


def test_enrich_diff_no_hunks_returns_diff_unchanged():
    from scripts.review import enrich_diff_with_function_context

    # The simplified diffs used by the existing end-to-end tests lack `@@`
    # hunks: enrichment must be a no-op so those tests stay green.
    diff = "diff --git a/file.py b/file.py\n+class HubCustomer:\n+    pass"
    assert enrich_diff_with_function_context(diff, ".") == diff
