import os
import time
import random
import logging
from pathlib import Path
from typing import Dict, Any
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.config import AppConfig

logger = logging.getLogger("planner.nodes.publish_issue")


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
        content = state.get("draft_issue_content", "")
        filepath = state.get("draft_issue_path", "")

        if not content:
            logger.warning("No draft issue content found. Skipping publishing.")
            return {"status": "success"}

        title, body = extract_title_and_body(content, filepath)

        # 1. Initialize configuration and get GitHub session consistently
        config = AppConfig()
        session = config.get_github_session()
        repo_name = config.github_repository
        workspace_dir = Path(config.github_workspace).resolve()

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

        # 4. Validate and remove local draft file to prevent Path Traversal
        if filepath:
            draft_path = Path(filepath).resolve()
            try:
                draft_path.relative_to(workspace_dir)
            except ValueError:
                raise ValueError(
                    f"Path traversal detected: draft issue path {draft_path} is outside GITHUB_WORKSPACE {workspace_dir}"
                )

            if draft_path.exists():
                try:
                    os.remove(draft_path)
                    logger.info(f"Successfully deleted local draft file: {draft_path}")
                except Exception as e:
                    logger.warning(f"Could not delete draft file {draft_path}: {e}")

        return {"status": "success"}
