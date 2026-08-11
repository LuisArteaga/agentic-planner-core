import importlib.util
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# The parser lives in the skill directory (not on sys.path). Load it by path.
PARSER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "pr-feedback-loop",
    "scripts",
    "parse_pr_verdicts.py",
)


def _load_parser():
    spec = importlib.util.spec_from_file_location("parse_pr_verdicts", PARSER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def parser():
    return _load_parser()


VERDICT_BODY = """### 🤖 Automated LLM PR Judges Summary
| Judge | Status | Details |
| :--- | :---: | :--- |
| **Syntax (`syntax_lint`)** | ✅ PASS | All criteria passed. |
| **Test (`test_coverage`)** | ❌ FAIL | 1 violation found. |
| **Arch (`architecture`)** | ✅ PASS | All criteria passed. |
| **Sec (`security`)** | ✅ PASS | All criteria passed. |

### ➡️ Test (`test_coverage`)
* **Status**: ❌ FAIL
#### 📝 Detailed Findings:
- `[ERROR]` [Q1] No tests added for new logic.
<!-- llm-pr-review-verdicts
syntax_lint: PASS
test_coverage: FAIL
architecture: PASS
security: PASS
-->
"""

ALL_PASS_BODY = """### Summary
<!-- llm-pr-review-verdicts
syntax_lint: PASS
test_coverage: PASS
architecture: PASS
security: PASS
-->
"""

NO_BLOCK_BODY = "### Summary\nNo verdict block here.\n"

NEEDS_REVIEW_BODY = """<!-- llm-pr-review-verdicts
syntax_lint: PASS
test_coverage: NEEDS REVIEW
architecture: PASS
security: PASS
-->
"""


def test_parse_verdict_block_all_pass(parser):
    verdicts = parser.parse_verdict_block(ALL_PASS_BODY)
    assert verdicts == {
        "syntax_lint": "PASS",
        "test_coverage": "PASS",
        "architecture": "PASS",
        "security": "PASS",
    }


def test_parse_verdict_block_with_fail(parser):
    verdicts = parser.parse_verdict_block(VERDICT_BODY)
    assert verdicts["test_coverage"] == "FAIL"
    assert verdicts["syntax_lint"] == "PASS"
    assert verdicts["architecture"] == "PASS"
    assert verdicts["security"] == "PASS"


def test_parse_verdict_block_no_block(parser):
    assert parser.parse_verdict_block(NO_BLOCK_BODY) == {}


def test_parse_verdict_block_needs_review(parser):
    verdicts = parser.parse_verdict_block(NEEDS_REVIEW_BODY)
    assert verdicts["test_coverage"] == "NEEDS REVIEW"


def test_extract_findings(parser):
    findings = parser.extract_findings(VERDICT_BODY)
    assert len(findings) == 1
    assert findings[0] == "- `[ERROR]` [Q1] No tests added for new logic."
    assert "PASS" not in " ".join(findings)


def test_extract_findings_empty(parser):
    assert parser.extract_findings(ALL_PASS_BODY) == []


def test_main_no_reviews_exits_zero(parser, capsys):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=json.dumps({"reviews": []}))
        sys.argv = ["parse_pr_verdicts.py", "42"]
        with pytest.raises(SystemExit) as exc:
            parser.main()
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["has_review"] is False


def test_main_all_pass_exits_zero(parser, capsys):
    reviews = [{"body": ALL_PASS_BODY, "state": "APPROVED"}]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=json.dumps({"reviews": reviews}))
        sys.argv = ["parse_pr_verdicts.py", "42"]
        with pytest.raises(SystemExit) as exc:
            parser.main()
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["all_pass"] is True
    assert out["failing"] == []
    assert out["needs_review"] == []


def test_main_fail_exits_one(parser, capsys):
    reviews = [{"body": VERDICT_BODY, "state": "REQUEST_CHANGES"}]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=json.dumps({"reviews": reviews}))
        sys.argv = ["parse_pr_verdicts.py", "42"]
        with pytest.raises(SystemExit) as exc:
            parser.main()
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert "test_coverage" in out["failing"]
    assert out["all_pass"] is False
    assert len(out["findings"]) == 1


def test_main_needs_review_exits_one(parser, capsys):
    reviews = [{"body": NEEDS_REVIEW_BODY, "state": "COMMENTED"}]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=json.dumps({"reviews": reviews}))
        sys.argv = ["parse_pr_verdicts.py", "42"]
        with pytest.raises(SystemExit) as exc:
            parser.main()
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert "test_coverage" in out["needs_review"]


def test_main_uses_latest_review_with_block(parser, capsys):
    # Stale review (no block) then a fresh one with a block; parser must pick
    # the fresh one, not the first.
    reviews = [
        {"body": NO_BLOCK_BODY, "state": "COMMENTED"},
        {"body": ALL_PASS_BODY, "state": "APPROVED"},
    ]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=json.dumps({"reviews": reviews}))
        sys.argv = ["parse_pr_verdicts.py", "42"]
        with pytest.raises(SystemExit) as exc:
            parser.main()
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["all_pass"] is True


def test_main_arg_error_exits_two(parser):
    sys.argv = ["parse_pr_verdicts.py"]
    with pytest.raises(SystemExit) as exc:
        parser.main()
    assert exc.value.code == 2


def test_main_gh_error_exits_two(parser):
    with patch(
        "subprocess.run", side_effect=parser.subprocess.CalledProcessError(1, "gh")
    ):
        sys.argv = ["parse_pr_verdicts.py", "42"]
        with pytest.raises(SystemExit) as exc:
            parser.main()
    assert exc.value.code == 2
