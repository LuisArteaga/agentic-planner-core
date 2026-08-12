import os
import sys
import time
import random
import logging
from pathlib import Path
from typing import Dict, Any
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.config import AppConfig

logger = logging.getLogger("planner.nodes.publish_issue")


def _confirm_publish(
    title: str,
    body: str,
    original_content: str,
    refined_path: Path,
    require_approval: bool,
) -> bool:
    """HITL confirmation gate before the GitHub API call (ADR-0020).

    Displays the issue to be published plus a unified diff of the refinement
    and prompts the user. ``--yes`` (require_approval=False) auto-approves. In
    a non-interactive environment (no TTY) the gate auto-approves with a
    warning so CI/autonomous runs do not hang or crash.
    """
    if not require_approval:
        return True

    if not sys.stdin.isatty():
        logger.warning(
            "HITL publish gate enabled but stdin is not a TTY; auto-approving."
        )
        return True

    import difflib

    print("\n" + "=" * 70)
    print("PUBLISH GATE — proposed GitHub issue")
    print("=" * 70)
    print(f"Title: {title}")
    print("-" * 70)
    print(body)
    print("-" * 70)

    refined_content = ""
    try:
        if refined_path.exists():
            refined_content = refined_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Could not read refined draft for diff: {exc}")

    if (
        refined_content
        and refined_content.rstrip() != (original_content or "").rstrip()
    ):
        diff = difflib.unified_diff(
            (original_content or "").splitlines(),
            refined_content.splitlines(),
            fromfile="original-draft",
            tofile="refined-draft",
            lineterm="",
        )
        print("Refinement diff:")
        for line in diff:
            print(line)
        print("-" * 70)

    try:
        answer = input("Publish this issue to GitHub? [y/N]: ").strip().lower()
    except EOFError:
        logger.warning("HITL prompt got EOF; auto-approving.")
        return True
    return answer in ("y", "yes")


def extract_title_and_body(content: str, filepath: str) -> tuple[str, str]:
    """Extracts issue title and body from the draft markdown content."""
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            # Der Rest ist der Body
            body = "\n".join(lines[idx + 1 :]).strip()
            return title, body

    # Fallback to plain filename without extension (unnecessary complexity removed)
    title = os.path.splitext(os.path.basename(filepath))[0]
    return title, content.strip()


def publish_issue_node(state: RefinementState) -> Dict[str, Any]:
    """Publishes the refined issue to GitHub using requests and deletes the local draft file."""
    logger.info("Running publish_issue node...")

    with orchestrator_phase("publish_issue"):
        filepath = state.get("draft_issue_path", "")
        original_content = state.get("draft_issue_content", "")

        # 1. Initialize configuration and get GitHub session consistently
        config = AppConfig()
        session = config.get_github_session()
        repo_name = config.github_repository
        workspace_dir = Path(config.github_workspace).resolve()

        # Publish the REFINED content — what ``apply_decision`` wrote to disk
        # and what the security audit / zero-tolerance gates actually inspected
        # — falling back to the original draft if the file is unavailable. This
        # keeps publish consistent with intent_gate / planning_judge (which
        # read from disk) so the audited content is what is published (ADR-0020).
        from planner.utils import validate_draft_path

        content = original_content
        refined_path: Path = Path(filepath) if filepath else Path("")
        if filepath:
            try:
                refined_path = validate_draft_path(filepath, workspace_dir)
                if refined_path.exists():
                    disk_content = refined_path.read_text(encoding="utf-8")
                    if disk_content.strip():
                        content = disk_content
            except Exception as exc:
                logger.warning(
                    f"Could not read refined draft from disk ({exc}); "
                    f"using state content."
                )
                refined_path = Path(filepath)

        if not content:
            logger.warning("No draft issue content found. Skipping publishing.")
            return {"status": "success"}

        title, body = extract_title_and_body(content, filepath)

        # 2. Resolve ready label
        label_name = os.environ.get("AGENT_LABEL_READY", "agent-ready")
        label_url = f"https://api.github.com/repos/{repo_name}/labels/{label_name}"

        try:
            label_response = session.get(label_url)
            if label_response.status_code == 404:
                logger.info(
                    f"Label '{label_name}' not found. Creating it in the target repository..."
                )
                create_label_url = f"https://api.github.com/repos/{repo_name}/labels"
                res = session.post(
                    create_label_url,
                    json={
                        "name": label_name,
                        "color": "0e8a16",  # Green color
                        "description": "Ready for autonomous developer loop execution",
                    },
                )
                res.raise_for_status()
            else:
                label_response.raise_for_status()
        except Exception as e:
            logger.warning(
                f"Error checking/creating label '{label_name}': {e}. Continuing without creating it."
            )

        # 3. Publish the issue
        # Zero-Trust HITL gate (ADR-0020): optionally confirm before the API
        # call. ``require_approval`` is resolved from the subgraph state (set
        # from the CLI flags / config in the master entrypoint).
        require_approval = bool(state.get("require_approval", False))

        if not _confirm_publish(
            title=title,
            body=body,
            original_content=original_content,
            refined_path=refined_path,
            require_approval=require_approval,
        ):
            logger.info(
                "HITL gate: user DECLINED publishing. Skipping GitHub API call."
            )
            # Keep the draft on disk so a human can rerun/inspect it.
            return {"status": "skipped_by_hitl"}

        logger.info(f"Creating GitHub issue: '{title}'...")
        create_issue_url = f"https://api.github.com/repos/{repo_name}/issues"
        issue_res = session.post(
            create_issue_url,
            json={
                "title": title,
                "body": body,
                "labels": [label_name],
            },
        )
        issue_res.raise_for_status()
        issue_data = issue_res.json()
        logger.info(
            f"Successfully published issue #{issue_data.get('number')} at {issue_data.get('html_url')}"
        )

        # Artificial jitter (1.0 to 2.0 seconds) to avoid secondary rate limits
        jitter = 1.0 + random.random()
        logger.debug(f"Applying artificial jitter of {jitter:.2f} seconds...")
        time.sleep(jitter)

        # 4. Validate and remove local draft file to prevent Path Traversal.
        if filepath:
            from planner.utils import validate_draft_path

            draft_path = validate_draft_path(filepath, workspace_dir)

            if draft_path.exists():
                try:
                    os.remove(draft_path)
                    logger.info(f"Successfully deleted local draft file: {draft_path}")
                except Exception as e:
                    logger.warning(f"Could not delete draft file {draft_path}: {e}")

        return {"status": "success"}
