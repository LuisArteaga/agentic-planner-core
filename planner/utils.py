from pathlib import Path


def validate_draft_path(filepath: str, workspace_dir: Path) -> Path:
    """Validates that the draft issue path does not attempt path traversal.
    Allows paths inside the GITHUB_WORKSPACE or the central planner drafts directory.
    """
    draft_path = Path(filepath).resolve()

    # Locate central drafts directory in the planner core repository
    planner_root = Path(__file__).resolve().parents[1]
    drafts_base = (planner_root / ".planner" / "drafts").resolve()

    in_drafts = False
    try:
        draft_path.relative_to(drafts_base)
        in_drafts = True
    except ValueError:
        pass

    in_workspace = False
    try:
        draft_path.relative_to(workspace_dir)
        in_workspace = True
    except ValueError:
        pass

    if not (in_drafts or in_workspace):
        raise ValueError(
            f"Path traversal detected: draft issue path {draft_path} is outside GITHUB_WORKSPACE {workspace_dir} "
            f"and planner drafts directory {drafts_base}"
        )

    return draft_path
