import os
import time
import random
import logging
from typing import Dict, Any
from github import Github, Auth, GithubRetry
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase

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

    # Fallback to file name if no H1 header found
    filename = os.path.basename(filepath)
    name_without_ext = os.path.splitext(filename)[0]
    parts = [p for p in name_without_ext.split("-") if p]
    # Remove leading sequence number if present (e.g., 0001)
    if parts and parts[0].isdigit():
        parts = parts[1:]
    title = " ".join(parts).title()
    return title, content.strip()


def publish_issue_node(state: RefinementState) -> Dict[str, Any]:
    """Publishes the refined issue to GitHub using PyGithub and deletes the local draft file."""
    logger.info("Running publish_issue node...")

    with orchestrator_phase("publish_issue"):
        content = state.get("draft_issue_content", "")
        filepath = state.get("draft_issue_path", "")

        if not content:
            logger.warning("No draft issue content found. Skipping publishing.")
            return {"status": "success"}

        title, body = extract_title_and_body(content, filepath)

        # Connect to GitHub API
        gh_pat = os.environ.get("GH_PAT") or os.environ.get("GH_TOKEN")
        repo_name = os.environ.get("GITHUB_REPOSITORY")

        if not gh_pat:
            raise ValueError(
                "Missing GitHub Personal Access Token (GH_PAT or GH_TOKEN) in environment."
            )
        if not repo_name:
            raise ValueError(
                "Missing target GitHub repository (GITHUB_REPOSITORY) in environment."
            )

        auth = Auth.Token(gh_pat)
        retry_strategy = GithubRetry(
            total=5,
            status_forcelist=[403, 500, 502, 503, 504],
            backoff_factor=1.0,
            secondary_rate_wait=10.0,
        )
        g = Github(auth=auth, retry=retry_strategy)

        # Get repo object
        repo = g.get_repo(repo_name)

        # Resolve ready label
        label_name = os.environ.get("AGENT_LABEL_READY", "agent-ready")
        try:
            label = repo.get_label(label_name)
        except Exception:
            logger.info(
                f"Label '{label_name}' not found. Creating it in the target repository..."
            )
            label = repo.create_label(
                name=label_name,
                color="0e8a16",  # Green color
                description="Ready for autonomous developer loop execution",
            )

        # Publish the issue
        logger.info(f"Creating GitHub issue: '{title}'...")
        issue = repo.create_issue(
            title=title,
            body=body,
            labels=[label],
        )
        logger.info(f"Successfully published issue #{issue.number} at {issue.html_url}")

        # Artificial jitter (1.0 to 2.0 seconds) to avoid secondary rate limits
        jitter = 1.0 + random.random()
        logger.debug(f"Applying artificial jitter of {jitter:.2f} seconds...")
        time.sleep(jitter)

        # Remove local draft file after successful publish
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Successfully deleted local draft file: {filepath}")
            except Exception as e:
                logger.warning(f"Could not delete draft file {filepath}: {e}")

        return {"status": "success"}
