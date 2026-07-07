import os
import sys
import json
import datetime
import urllib.request
import urllib.error
import subprocess
import time
from typing import List, Tuple, Dict, Any
import requests

# Add project root and scripts dir to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
scripts_dir = os.path.dirname(os.path.abspath(__file__))
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from planner.config import resolve_model_config  # noqa: E402

from telemetry import (  # noqa: E402
    init_telemetry,
    get_tracer,
    trace,
    OPENINFERENCE_SPAN_KIND,
    INPUT_VALUE,
    OUTPUT_VALUE,
    LLM_MODEL_NAME,
    TOOL_NAME,
    TOOL_PARAMETERS,
)

# Setup logger paths
log_file_path = None
agent_log_path = os.getenv("AGENT_LOG_PATH")
if agent_log_path:
    log_dir = os.path.dirname(agent_log_path)
else:
    agent_mode = os.getenv("AGENT_MODE", "ci")
    if agent_mode == "ci":
        workspace = os.getenv("GITHUB_WORKSPACE", ".")
        log_dir = os.path.join(workspace, "agent_logs")
    else:
        log_dir = None


def is_dir_writeable(path):
    try:
        os.makedirs(path, exist_ok=True)
        # Test writeability
        test_file = os.path.join(path, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except Exception:
        return False


if log_dir:
    if not is_dir_writeable(log_dir):
        sys.stdout.write(
            f"[WARN] Log directory {log_dir} is not writeable (Permission Denied). Falling back to container /tmp/agent_logs\n"
        )
        log_dir = "/tmp/agent_logs"
        if not is_dir_writeable(log_dir):
            log_dir = None

    if log_dir:
        log_file_path = os.path.join(log_dir, "review.log")


def log(message):
    """Logs a message with timestamp to stdout and CI log file if configured."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}"
    print(formatted)
    if log_file_path:
        try:
            with open(log_file_path, "a") as f:
                f.write(formatted + "\n")
        except Exception:
            pass


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


def run_command(cmd, env=None):
    """Runs a shell command and returns code, stdout, stderr."""
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return res.returncode, res.stdout, res.stderr


def call_openrouter_api(
    model, messages, api_key, routing=None, temperature=0.0, options=None, timeout=30
):
    """Performs HTTP request to OpenRouter chat completions API."""
    url = "https://openrouter.ai/api/v1/chat/completions"

    payload_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature if temperature is not None else 0.0,
    }
    if routing:
        payload_dict["provider"] = {
            "order": [r.lower() for r in routing],
            "allow_fallbacks": False,
        }
    if options:
        payload_dict.update(options)

    payload = json.dumps(payload_dict)
    data = payload.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "agentic-planner-core/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:  # nosemgrep
        return response.status, response.read().decode("utf-8")


def call_llm_for_review(judge_key, system_prompt, diff, api_key):
    """Resolves config for judge_key, wraps OpenRouter API call in a trace span and executes it with retry logic."""
    cfg = resolve_model_config(judge_key)
    model = cfg["model"]
    routing = cfg["routing"]
    temperature = cfg["temperature"]
    options = cfg["options"]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": diff},
    ]

    tracer = get_tracer()
    with tracer.start_as_current_span("openrouter_chat_completion") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "LLM")
        span.set_attribute(LLM_MODEL_NAME, model)
        span.set_attribute(INPUT_VALUE, json.dumps(messages))

        # Check for overridden model to log correctly
        log(f"[INFO] Running judge {judge_key} using model: {model}")

        response_body = ""
        last_error = ""

        # Set timeout based on judge: 180s for architecture/security (reasoning models), 30s for syntax/test_coverage
        timeout = 180 if judge_key in ["architecture", "security"] else 30

        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                status, body = call_openrouter_api(
                    model,
                    messages,
                    api_key,
                    routing=routing,
                    temperature=temperature,
                    options=options,
                    timeout=timeout,
                )

                # Pre-validate structure before considering it OK
                parsed_body = json.loads(body, strict=False)

                if "error" in parsed_body:
                    err = parsed_body["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise Exception(f"OpenRouter API error: {msg}")
                elif "choices" not in parsed_body or not parsed_body["choices"]:
                    raise Exception("OpenRouter response missing choices block")

                choice_msg = parsed_body["choices"][0].get("message", {})
                content = choice_msg.get("content")
                if not content or not content.strip():
                    raise Exception("OpenRouter response message content is empty")

                response_body = body
                break
            except Exception as e:
                last_error = str(e)
                log(
                    f"[WARN] OpenRouter attempt {attempt + 1} of {max_attempts} failed: {e}"
                )
                if attempt < max_attempts - 1:
                    sleep_time = (2**attempt) * 4
                    log(f"[INFO] Sleeping {sleep_time} seconds before retrying...")
                    time.sleep(sleep_time)
                    continue
                raise Exception(
                    f"LLM review failed after retries. Last error: {last_error}"
                )

        span.set_attribute(OUTPUT_VALUE, response_body)
        return response_body


def submit_github_review(pr_number, action, body_content):
    """Submits findings using GitHub REST API directly (bypassing gh CLI wrapper)."""
    token = os.getenv("GH_PAT") or os.getenv("GH_TOKEN")
    if not token:
        raise Exception("GitHub token (GH_PAT or GH_TOKEN) not found in environment.")

    github_repo = os.getenv("GITHUB_REPOSITORY", "")
    if not github_repo:
        raise Exception("GITHUB_REPOSITORY environment variable not set.")

    tracer = get_tracer()
    with tracer.start_as_current_span("submit_github_review") as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, "TOOL")
        span.set_attribute(TOOL_NAME, "submit_github_review")
        span.set_attribute(
            TOOL_PARAMETERS,
            json.dumps(
                {"pr_number": pr_number, "action": action, "body_content": body_content}
            ),
        )
        span.set_attribute(
            INPUT_VALUE,
            json.dumps(
                {"pr_number": pr_number, "action": action, "body_content": body_content}
            ),
        )

        from urllib3.util import Retry
        from requests.adapters import HTTPAdapter

        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[403, 429, 500, 502, 503, 504],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))

        # Get PR Author
        try:
            url = f"https://api.github.com/repos/{github_repo}/pulls/{pr_number}"
            res = session.get(url, timeout=30)
            res.raise_for_status()
            pr_data = res.json()
            pr_author = pr_data.get("user", {}).get("login", "")
        except Exception as e:
            raise Exception(f"Failed to fetch PR details from GitHub API: {e}")

        # Get Current Authenticated User
        try:
            url = "https://api.github.com/user"
            res = session.get(url, timeout=30)
            res.raise_for_status()
            user_data = res.json()
            current_user = user_data.get("login", "")
        except Exception as e:
            current_user = os.getenv("GITHUB_ACTOR", "")
            log(
                f"[WARN] Failed to fetch current user via /user: {e}. Fallback to GITHUB_ACTOR={current_user}"
            )

        # Determine appropriate review action flag
        if current_user and pr_author and current_user == pr_author:
            api_event = "COMMENT"
        elif action == "approve":
            api_event = "APPROVE"
        elif action == "comment":
            api_event = "COMMENT"
        else:
            api_event = "REQUEST_CHANGES"

        # Submit review
        try:
            review_payload = {"body": body_content, "event": api_event}
            url = (
                f"https://api.github.com/repos/{github_repo}/pulls/{pr_number}/reviews"
            )
            res = session.post(url, json=review_payload, timeout=30)
            res.raise_for_status()
            review_data = res.json()
            span.set_attribute(
                OUTPUT_VALUE,
                json.dumps(review_data),
            )
        except Exception as e:
            raise Exception(f"Failed to submit review via GitHub API: {e}")


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


def main():
    # Initialize telemetry
    init_telemetry()

    pr_number = os.getenv("PR_NUMBER", "")
    if not pr_number:
        sys.stderr.write("[ERR] PR_NUMBER not set\n")
        sys.exit(1)

    gh_pat = os.getenv("GH_PAT", "")
    gh_token = os.getenv("GH_TOKEN", "")
    token = gh_pat if gh_pat else gh_token
    if not token:
        sys.stderr.write("[ERR] GitHub token not configured.\n")
        sys.exit(1)

    os.environ["GH_TOKEN"] = token

    diff = sys.stdin.read()
    if not diff.strip():
        log("[WARN] No diff to review")
        sys.exit(0)

    tracer = get_tracer()
    with tracer.start_as_current_span("pr_review") as main_span:
        main_span.set_attribute(OPENINFERENCE_SPAN_KIND, "CHAIN")
        main_span.set_attribute(
            INPUT_VALUE, json.dumps({"pr_number": pr_number, "diff_len": len(diff)})
        )

        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not openrouter_api_key:
            sys.stderr.write("[ERR] OPENROUTER_API_KEY not configured.\n")
            sys.exit(1)

        judges_data: Dict[str, Any] = {
            "syntax_lint": {
                "name": "Syntax & Konformität",
                "prompt": SYSTEM_PROMPT_SYNTAX_LINT,
                "q_names": {
                    "Q1": "Syntax Validation (Free of syntax errors / typos)",
                    "Q2": "JSON Schema Verification",
                    "Q3": "Naming Conventions (Data Vault Hub/Sat prefixes)",
                },
                "status": "SKIPPED",
                "reasoning": "",
                "findings": [],
                "error": "",
            },
            "test_coverage": {
                "name": "Test-Validierung",
                "prompt": SYSTEM_PROMPT_TEST_COVERAGE,
                "q_names": {
                    "Q1": "Test Presence (Coverage for logic changes)",
                    "Q2": "Test Quality/Assertions (Meaningful assertions)",
                },
                "status": "SKIPPED",
                "reasoning": "",
                "findings": [],
                "error": "",
            },
            "architecture": {
                "name": "Architektur-Compliance",
                "prompt": SYSTEM_PROMPT_ARCH,
                "q_names": {
                    "Q1": "Layer Boundaries & Drift (e.g. state isolation)",
                    "Q2": "Radical Simplicity / Lazy Coding (No boilerplate/YAGNI)",
                },
                "status": "SKIPPED",
                "reasoning": "",
                "findings": [],
                "error": "",
            },
            "security": {
                "name": "Deep Security Audit",
                "prompt": SYSTEM_PROMPT_SECURITY,
                "q_names": {
                    "Q1": "Secrets (Free of keys/passwords/credentials)",
                    "Q2": "Injections (SQL / Shell command injection)",
                    "Q3": "Security Audit (Control flow taint analysis / OWASP Top 10)",
                },
                "status": "SKIPPED",
                "reasoning": "",
                "findings": [],
                "error": "",
            },
        }

        fail_fast_triggered = False

        for judge_key in ["syntax_lint", "test_coverage", "architecture", "security"]:
            if fail_fast_triggered:
                judges_data[judge_key]["status"] = "SKIPPED"
                judges_data[judge_key]["reasoning"] = (
                    "Skipped due to syntax_lint failure."
                )
                continue

            log(f"[INFO] Running judge: {judge_key}")
            judge_info = judges_data[judge_key]

            with tracer.start_as_current_span(f"{judge_key}_evaluation") as span:
                span.set_attribute(OPENINFERENCE_SPAN_KIND, "LLM")
                cfg = resolve_model_config(judge_key)
                span.set_attribute(LLM_MODEL_NAME, cfg["model"])
                span.set_attribute("eval.dimension", judge_key)

                prompt = judge_info["prompt"]
                if judge_key == "architecture":
                    workspace_dir = os.getenv("GITHUB_WORKSPACE", ".")
                    arch_context = load_architecture_context(workspace_dir)
                    if arch_context:
                        prompt += (
                            "\n\n=== REPOSITORY ARCHITECTURE CONTEXT ===\n"
                            + arch_context
                        )
                    else:
                        prompt += "\n\n=== REPOSITORY ARCHITECTURE CONTEXT ===\nNo specific architecture documentation found. Falling back to default rules."

                try:
                    raw_resp = call_llm_for_review(
                        judge_key, prompt, diff, openrouter_api_key
                    )
                    verdict, reasoning, findings = evaluate_response(raw_resp)

                    judge_info["reasoning"] = reasoning
                    judge_info["findings"] = findings

                    if verdict == "Pass":
                        judge_info["status"] = "PASS"
                    else:
                        judge_info["status"] = "FAIL"

                except Exception as e:
                    log(f"[ERR] Judge {judge_key} failed: {e}")
                    judge_info["status"] = "FAIL"
                    judge_info["error"] = str(e)
                    judge_info["reasoning"] = (
                        f"Exception encountered during execution: {e}"
                    )
                    span.record_exception(e)

                span.set_attribute("eval.verdict", judge_info["status"])
                span.set_attribute("eval.findings_count", len(judge_info["findings"]))

                status_code = (
                    trace.StatusCode.OK
                    if judge_info["status"] == "PASS"
                    else trace.StatusCode.ERROR
                )
                span.set_status(
                    trace.Status(
                        status_code,
                        f"Status: {judge_info['status']}"
                        if status_code == trace.StatusCode.ERROR
                        else None,
                    )
                )

            # Fail-fast logic
            if judge_key == "syntax_lint" and judge_info["status"] == "FAIL":
                log("[WARN] syntax_lint failed. Triggering fail-fast.")
                fail_fast_triggered = True

        # Compile combined Markdown report
        report_lines = []
        report_lines.append("### 🤖 Automated LLM PR Judges Summary\n")
        report_lines.append("| Judge | Status | Details |")
        report_lines.append("| :--- | :---: | :--- |")

        for key in ["syntax_lint", "test_coverage", "architecture", "security"]:
            info = judges_data[key]
            status = info["status"]
            if status == "PASS":
                status_emoji = "✅ PASS"
            elif status == "FAIL":
                status_emoji = "❌ FAIL"
            else:
                status_emoji = "⏭️ SKIPPED"

            if status == "SKIPPED":
                details = "Skipped due to syntax_lint failure."
            elif status == "FAIL":
                if info["error"]:
                    details = f"Check failed to run: {info['error']}"
                else:
                    details = f"{len(info['findings'])} violations found."
            else:
                details = "All criteria passed."

            report_lines.append(
                f"| **{info['name']} (`{key}`)** | {status_emoji} | {details} |"
            )

        report_lines.append("\n---\n")

        # Details section for executed judges
        for key in ["syntax_lint", "test_coverage", "architecture", "security"]:
            info = judges_data[key]
            if info["status"] == "SKIPPED":
                continue

            report_lines.append(f"### ➡️ {info['name']} (`{key}`)")
            report_lines.append(
                f"* **Status**: {'✅ PASS' if info['status'] == 'PASS' else '❌ FAIL'}"
            )

            # Resolve individual Q statuses
            q_status = {}
            for q_key in info["q_names"]:
                has_failed = False
                for finding in info["findings"]:
                    msg = finding.split("|", 1)[1] if "|" in finding else finding
                    if f"[{q_key}]" in msg or f"[{q_key.lower()}]" in msg:
                        has_failed = True
                        break
                if info["status"] == "FAIL" and not info["findings"] and info["error"]:
                    q_status[q_key] = "FAIL"
                else:
                    q_status[q_key] = "FAIL" if has_failed else "PASS"

            report_lines.append("* **Binary Evaluation (BINEVAL)**:")
            for q_key, q_desc in info["q_names"].items():
                q_emoji = "✅ PASS" if q_status[q_key] == "PASS" else "❌ FAIL"
                report_lines.append(f"  - **{q_key} ({q_desc})**: {q_emoji}")

            if info["findings"]:
                report_lines.append("\n#### 📝 Detailed Findings:")
                for f in info["findings"]:
                    sev, msg = f.split("|", 1) if "|" in f else ("bug", f)
                    report_lines.append(f"- `[{sev.upper()}]` {msg}")

            if info["error"]:
                report_lines.append(f"\n⚠️ **Execution Error**: {info['error']}")

            if info["reasoning"]:
                report_lines.append("\n#### 🧠 Reasoning:")
                report_lines.append("<details>")
                report_lines.append("<summary>Reasoning Details</summary>\n")
                report_lines.append(info["reasoning"])
                report_lines.append("\n</details>\n")

            report_lines.append("\n---\n")

        combined_report = "\n".join(report_lines)

        # Determine overall success / failure
        overall_failed = any(info["status"] == "FAIL" for info in judges_data.values())
        review_action = "request-changes" if overall_failed else "approve"

        try:
            submit_github_review(pr_number, review_action, combined_report)
        except Exception as e:
            log(f"[ERR] Failed to submit GitHub review: {e}")
            sys.exit(1)

        if overall_failed:
            log("[ERR] LLM review found issues in one or more judges")
            main_span.set_status(
                trace.Status(trace.StatusCode.ERROR, "Review evaluation failed")
            )
            sys.exit(1)
        else:
            log("[INFO] LLM review completed successfully")
            main_span.set_status(trace.Status(trace.StatusCode.OK))
            sys.exit(0)


if __name__ == "__main__":
    main()
