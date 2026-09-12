"""Judge-artifact snapshot for the Judge-Evaluierungssuite (ADR-0022).

The eval suite calibrates the CI PR judges against exactly the artifacts
those judges use. Since the CI judges come from the quality-gates-toolkit
composite (v1.6.0, ADR-0022), the artifacts the suite needs live here as a
verbatim snapshot of the judge implementation as of that migration:

- the four binary-judge system prompts (``SYSTEM_PROMPT_*``),
- the ``<reasoning>``/``<findings>`` response parser
  (``evaluate_response`` plus its ``parse_xml_tags`` helper),
- the architecture-context loader (``load_architecture_context``).

DRIFT PIN — quality-gates-toolkit v1.6.0 (ADR-0022, Option 3): the CI
judges run the toolkit engine at that ref, while this snapshot preserves
the pre-migration judge artifacts, which had already diverged from the
toolkit (~2000-line drift, including the Data-Vault naming criterion in
``SYSTEM_PROMPT_SYNTAX_LINT``). The suite must keep calibrating the exact
prompts its gold-standard fixtures were annotated against, so this module
is deliberately frozen and will drift further from the toolkit until the
planned follow-up replaces it with the importable
``quality_gates_toolkit`` judge package (toolkit D-0017). Do not edit the
artifacts below except to mirror a decision recorded in a new ADR.
"""

import json
import os
import sys
from typing import List, Tuple

SYSTEM_PROMPT_SYNTAX_LINT = (
    "You are a code reviewer specialized in syntax validation, JSON schemas, and naming conventions.\n"
    "Review the PR diff against these specific criteria:\n"
    "=== 1. CRITERIA DEFINITION ===\n"
    "- Q1 (Syntax Validation): Check if the modified code is free of syntax errors, obvious compilation issues, or typos. (Note: Due to system-level egress sanitization, the '@' symbol used for decorators, e.g. @pytest.fixture or @functools.lru_cache, might be received as '[EMAIL]'. Do NOT count '[EMAIL]' as a syntax error or typo; treat it as a valid '@' decorator symbol).\n"
    "- Q2 (JSON Schema Verification): Check if any modified JSON files adhere to standard or expected JSON formats and schemas.\n"
    "- Q3 (Naming Conventions): Check if class names, functions, and variables follow naming conventions (specifically: Data Vault Hub classes should have a 'Hub_' or 'Hub' prefix, Satellite classes should have 'Sat_' or 'Sat' prefix, etc.).\n\n"
    "=== 2. ARGUMENTATION STRUCTURE ===\n"
    "Output your thought process inside <reasoning>...</reasoning> tags.\n"
    "Output any violations inside <findings>...</findings> tags.\n\n"
    "=== 3. SCORING RULE ===\n"
    "- PASS: If there are no violations. Output an empty findings block: <findings></findings>.\n"
    "- FAIL: If one or more criteria fail. Report each violation as a JSON object on a single line inside the findings block: "
    '{"severity": "error", "message": "[QX] Details of the failure"}.\n'
    'Example: If Q3 fails: {"severity": "error", "message": "[Q3] Class HubCustomer does not use prefix Hub_"}\n\n'
    "=== OUTPUT FORMAT ===\n"
    "First, output your reasoning block:\n"
    "<reasoning>\n"
    "[Your reasoning/thinking about the syntax and naming aspects]\n"
    "</reasoning>\n\n"
    "Second, output your findings block:\n"
    "<findings>\n"
    "[Line-delimited JSON objects if FAIL, otherwise empty]\n"
    "</findings>"
)

SYSTEM_PROMPT_TEST_COVERAGE = (
    "You are a code reviewer specialized in test validation and coverage.\n"
    "Review the PR diff against these specific criteria:\n"
    "=== 1. CRITERIA DEFINITION ===\n"
    "- Q1 (Test Presence): Check if any modified logic or new code is accompanied by new tests or updates to existing tests in the test folders.\n"
    "- Q2 (Test Quality/Assertions): Check if the tests contain meaningful assertions validating the actual behavior/logic changes, rather than trivial or empty test cases.\n\n"
    "=== 2. ARGUMENTATION STRUCTURE ===\n"
    "Output your thought process inside <reasoning>...</reasoning> tags.\n"
    "Output any violations inside <findings>...</findings> tags.\n\n"
    "=== 3. SCORING RULE ===\n"
    "- PASS: If there are no violations. Output an empty findings block: <findings></findings>.\n"
    "- FAIL: If one or more criteria fail. Report each violation as a JSON object on a single line inside the findings block: "
    '{"severity": "error", "message": "[QX] Details of the failure"}.\n'
    'Example: If Q1 fails: {"severity": "error", "message": "[Q1] No tests added for new function compute_hash"}\n\n'
    "=== OUTPUT FORMAT ===\n"
    "First, output your reasoning block:\n"
    "<reasoning>\n"
    "[Your reasoning/thinking about the tests]\n"
    "</reasoning>\n\n"
    "Second, output your findings block:\n"
    "<findings>\n"
    "[Line-delimited JSON objects if FAIL, otherwise empty]\n"
    "</findings>"
)

SYSTEM_PROMPT_ARCH = (
    "You are a code reviewer specialized in architecture compliance. Review the PR diff for compliance with repository architecture, conventions, and design decisions.\n\n"
    "=== 1. CRITERIA DEFINITION ===\n"
    "Check the diff for compliance against the documented architecture rules, ADRs, context conventions, and the following rules:\n"
    "- Q1 (Layer Boundaries & Drift): Check if layer boundaries are respected and architectural drift is avoided. For example, refinement subgraph state must be isolated and must not leak context to other issues.\n"
    "- Q2 (Radical Simplicity / Lazy Coding): Check if the code is free of unnecessary abstractions, boilerplate, redundant interfaces, or scaffolding for future use (YAGNI). Prefer stdlib over new dependencies. Delete unused code. (Note: Due to system-level egress sanitization, the '@' symbol used for decorators, e.g. @pytest.fixture or @functools.lru_cache, might be received as '[EMAIL]'. Do NOT count '[EMAIL]' as an architectural compliance issue or syntax error; treat it as a valid '@' decorator symbol). (Note: Due to system-level egress sanitization, IP addresses such as '127.0.0.1' or '169.254.169.254' in the diff may be rendered as '[IP_ADDRESS]'. Do NOT treat consecutive '[IP_ADDRESS]' occurrences as duplicate code — they may represent distinct IP addresses in the original source. Only flag as duplicate if the complete surrounding expression is identical).\n\n"
    "=== 2. ARGUMENTATION STRUCTURE ===\n"
    "Output your thought process inside <reasoning>...</reasoning> tags.\n"
    "Output any compliance deviations inside <findings>...</findings> tags.\n\n"
    "=== 3. SCORING RULE ===\n"
    "- PASS: If the code complies. Output an empty findings block: <findings></findings>.\n"
    "- FAIL: If any compliance deviation is found. Report each as a JSON object on a single line inside the findings block: "
    '{"severity": "bug", "message": "[QX] Details of the failure"}.\n\n'
    "=== OUTPUT FORMAT ===\n"
    "First, output your reasoning block:\n"
    "<reasoning>\n"
    "[Your reasoning/thinking about the architectural compliance]\n"
    "</reasoning>\n\n"
    "Second, output your findings block:\n"
    "<findings>\n"
    "[Line-delimited JSON objects if FAIL, otherwise empty]\n"
    "</findings>"
)


SYSTEM_PROMPT_SECURITY = (
    "You are a code reviewer specialized in security. Review the PR diff for critical security issues.\n\n"
    "=== 1. CRITERIA DEFINITION ===\n"
    "Check the diff for the following critical security vulnerabilities:\n"
    "- Q1 (Secrets): Free of hardcoded credentials, secrets, passwords, or API keys.\n"
    "- Q2 (Injections): Protected against SQL injection, shell command execution without escaping, or unsanitized inputs.\n"
    "- Q3 (Security Audit): Control flow safety (Taint-Analysis) against logical exploits and OWASP Top 10.\n\n"
    "=== 2. ARGUMENTATION STRUCTURE ===\n"
    "Output your thought process inside <reasoning>...</reasoning> tags.\n"
    "Output any found vulnerabilities inside <findings>...</findings> tags.\n\n"
    "=== 3. SCORING RULE ===\n"
    "- PASS: If there are no security vulnerabilities. Output an empty findings block: <findings></findings>.\n"
    "- FAIL: If one or more verified security vulnerabilities are found. Report each as a JSON object on a single line inside the findings block: "
    '{"severity": "security", "message": "[QX] Details of the failure"}.\n\n'
    "=== OUTPUT FORMAT ===\n"
    "First, output your reasoning block:\n"
    "<reasoning>\n"
    "[Your reasoning/thinking about security]\n"
    "</reasoning>\n\n"
    "Second, output your findings block:\n"
    "<findings>\n"
    "[Line-delimited JSON objects if FAIL, otherwise empty]\n"
    "</findings>"
)


def parse_xml_tags(text: str, open_tag: str, close_tag: str) -> str:
    """Helper to extract content between open_tag and close_tag."""
    if open_tag not in text:
        return ""
    last_open = text.rfind(open_tag)
    block = text[last_open + len(open_tag) :]
    close_idx = block.find(close_tag)
    if close_idx != -1:
        return block[:close_idx].strip()
    return block.strip()


def evaluate_response(raw_response: str) -> Tuple[str, str, List[str]]:
    """Evaluates the LLM response.

    Returns (verdict, reasoning, findings_list)
    where verdict is 'Pass', 'Fail', or 'Needs Review'.
    """
    data = json.loads(raw_response, strict=False)
    content = data["choices"][0]["message"]["content"]

    if not content:
        return "Needs Review", "Empty response from LLM", []

    reasoning = parse_xml_tags(content, "<reasoning>", "</reasoning>")
    findings_block = parse_xml_tags(content, "<findings>", "</findings>")

    # Check for refusal / lack of tags
    if not reasoning and not findings_block:
        return (
            "Needs Review",
            "Response lacks both <reasoning> and <findings> tags. Original output:\n"
            + content,
            [],
        )

    findings_list = []
    verdict = "Pass"

    for line in findings_block.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            f = json.loads(line, strict=False)
            if not isinstance(f, dict):
                continue
            sev = f.get("severity", "bug").lower()
            msg = f.get("message", "").replace("\n", " ")
            findings_list.append(f"{sev}|{msg}")
            verdict = "Fail"
        except Exception:
            continue

    return verdict, reasoning, findings_list


def load_architecture_context(workspace_dir: str) -> str:
    """Loads CONTEXT.md or docs/context.md and all docs/adr/*.md files relative to workspace_dir."""
    context_lines = []

    # Try reading CONTEXT.md in project root (typical for agentic-planner-core)
    context_file = os.path.join(workspace_dir, "CONTEXT.md")
    if not os.path.isfile(context_file):
        # Fallback to docs/context.md
        context_file = os.path.join(workspace_dir, "docs", "context.md")

    if os.path.isfile(context_file):
        try:
            with open(context_file, "r", encoding="utf-8", errors="replace") as f:
                context_lines.append(
                    f"--- {os.path.relpath(context_file, workspace_dir)} ---"
                )
                context_lines.append(f.read())
                context_lines.append("")
        except Exception as e:
            sys.stdout.write(f"[WARN] Failed to read {context_file}: {e}\n")
    else:
        sys.stdout.write(
            "[WARN] Architecture context file (CONTEXT.md or docs/context.md) is missing.\n"
        )

    # Try reading adr/*.md files
    docs_dir = os.path.join(workspace_dir, "docs")
    adr_dir = os.path.join(docs_dir, "adr")
    if os.path.isdir(adr_dir):
        try:
            for entry in sorted(os.listdir(adr_dir)):
                if entry.endswith(".md"):
                    entry_path = os.path.join(adr_dir, entry)
                    if os.path.isfile(entry_path):
                        with open(
                            entry_path, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            context_lines.append(f"--- docs/adr/{entry} ---")
                            context_lines.append(f.read())
                            context_lines.append("")
        except Exception as e:
            sys.stdout.write(f"[WARN] Failed to read ADR files from {adr_dir}: {e}\n")
    else:
        # Fallback to check if adr directory exists directly under workspace_dir/adr (in case structure is flat)
        flat_adr_dir = os.path.join(workspace_dir, "adr")
        if os.path.isdir(flat_adr_dir):
            try:
                for entry in sorted(os.listdir(flat_adr_dir)):
                    if entry.endswith(".md"):
                        entry_path = os.path.join(flat_adr_dir, entry)
                        if os.path.isfile(entry_path):
                            with open(
                                entry_path, "r", encoding="utf-8", errors="replace"
                            ) as f:
                                context_lines.append(f"--- adr/{entry} ---")
                                context_lines.append(f.read())
                                context_lines.append("")
            except Exception as e:
                sys.stdout.write(
                    f"[WARN] Failed to read ADR files from {flat_adr_dir}: {e}\n"
                )
        else:
            sys.stdout.write(
                "[WARN] Architecture Decision Records folder (docs/adr or adr) is missing.\n"
            )

    return "\n".join(context_lines)
