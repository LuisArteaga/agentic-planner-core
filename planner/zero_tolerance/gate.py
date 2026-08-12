"""Orchestration for the Zero-Error-Tolerance AddOn.

Exposes:
  * ``run_batch_gate``  — deterministic pre-refinement gate over all drafts.
  * ``detect_structural_change_node`` — deterministic subgraph node.
  * ``threshold_check_node`` — deterministic escape-hatch thresholds.
  * ``route_after_decision`` — conditional-edge router for the subgraph tail.
  * ``run_cascade_pass`` — post-change stale marking of downstream drafts.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from planner.state import RefinementState
from planner.zero_tolerance.linters import (
    adr_traceability_lint,
    dependency_lint,
    glossary_lint,
    is_trivial,
    reverse_dependency_map,
    structural_signature,
)
from planner.zero_tolerance.models import (
    BatchValidationResult,
    LintFinding,
    Severity,
    ZeroToleranceConfig,
    ZeroToleranceViolation,
)
from scripts.telemetry import orchestrator_phase

logger = logging.getLogger("planner.zero_tolerance.gate")


def _read_drafts(draft_files: List[str]) -> Dict[str, str]:
    """Read draft files into a mapping of filename -> content."""
    contents: Dict[str, str] = {}
    for path_str in draft_files:
        path = Path(path_str)
        try:
            contents[path.name] = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Could not read draft {path_str}: {exc}")
    return contents


def run_batch_gate(
    draft_files: List[str], config: ZeroToleranceConfig
) -> BatchValidationResult:
    """Run all deterministic batch-level lints before the master loop.

    Checks: glossary violations, dependency DAG validity (dangling + cycles),
    and ADR/AgDR traceability. Any ERROR finding means the gate did not pass;
    the caller halts the process (HITL) instead of auto-fixing.
    """
    with orchestrator_phase("zero_tolerance_batch_gate"):
        findings: List[LintFinding] = []
        draft_contents = _read_drafts(draft_files)

        from planner.zero_tolerance.linters import parse_glossary

        glossary = parse_glossary(config.context_path)
        findings.extend(glossary_lint(draft_contents, glossary))

        dep_findings, dep_map = dependency_lint(draft_contents)
        findings.extend(dep_findings)

        findings.extend(adr_traceability_lint(draft_contents, config.adr_dirs))

        passed = not any(f.severity == Severity.ERROR for f in findings)
        return BatchValidationResult(passed=passed, findings=findings)


def compute_dependency_map(draft_files: List[str]) -> Dict[str, List[str]]:
    """Parse the dependency map (filename -> blockers) for the master loop."""
    contents = _read_drafts(draft_files)
    _, dep_map = dependency_lint(contents)
    return dep_map


# ---------------------------------------------------------------------------
# Deterministic subgraph nodes
# ---------------------------------------------------------------------------


def detect_structural_change_node(state: RefinementState) -> Dict[str, Any]:
    """Deterministic node: detect whether refinement changed the issue structure.

    Reads the refined content from disk (``apply_decision`` writes it there) and
    compares its structural signature to the original. Also resolves the
    triviality flag so the router can bypass the LLM gates for trivial issues.
    """
    with orchestrator_phase("zero_tolerance_detect_structural_change"):
        config = _zt_config_from_state(state)
        draft_path = state.get("draft_issue_path", "")
        original_sig = state.get("original_draft_signature", "")

        trivial = False
        structurally_changed = False
        if draft_path and Path(draft_path).exists():
            refined = Path(draft_path).read_text(encoding="utf-8")
            trivial = is_trivial(refined, config)
            refined_sig = structural_signature(refined)
            structurally_changed = bool(original_sig) and refined_sig != original_sig
        return {
            "trivial": trivial,
            "structurally_changed": structurally_changed,
        }


def threshold_check_node(state: RefinementState) -> Dict[str, Any]:
    """Deterministic escape-hatch thresholds (Fable Method: bounded retries).

    Halts (raises ``ZeroToleranceViolation``) when:
      * the best graded option scored below ``min_acceptable_score`` (a failed
        grading cycle), or
      * the number of fruitless (empty) search result sets exceeds
        ``max_fruitless_searches``.
    """
    with orchestrator_phase("zero_tolerance_threshold_check"):
        config = _zt_config_from_state(state)
        issue_name = Path(state.get("draft_issue_path", "")).name or "(unknown)"

        best_option = state.get("best_option", {}) or {}
        score = best_option.get("score", 0.0)
        if score < config.min_acceptable_score:
            raise ZeroToleranceViolation(
                "threshold",
                (
                    f"Best option score {score} is below the minimum acceptable "
                    f"score {config.min_acceptable_score} (failed grading cycle)."
                ),
                issue_name,
            )

        search_results = state.get("search_results", []) or []
        if len(search_results) <= config.max_fruitless_searches:
            raise ZeroToleranceViolation(
                "threshold",
                (
                    f"Only {len(search_results)} search result(s) — at or below the "
                    f"max fruitless searches ({config.max_fruitless_searches})."
                ),
                issue_name,
            )
        return {}


def route_after_decision(state: RefinementState) -> str:
    """Conditional-edge router for the subgraph tail.

    * Non-zero-tolerance, or a trivial draft  -> ``publish_issue`` (skip gates).
    * Otherwise                                -> ``threshold_check``.
    """
    if not state.get("zero_tolerance", False):
        return "publish_issue"
    if state.get("trivial", False):
        return "publish_issue"
    return "threshold_check"


# ---------------------------------------------------------------------------
# Cascade collision gate
# ---------------------------------------------------------------------------


def run_cascade_pass(
    remaining_draft_files: List[str],
    changed_filenames: List[str],
    dep_map: Dict[str, List[str]],
) -> List[str]:
    """Mark downstream drafts stale when an upstream draft changed structurally.

    Returns the list of draft file paths marked stale. A ``<draft>.stale`` marker
    file is written next to each stale draft so a subsequent run can detect it.
    """
    if not changed_filenames:
        return []
    reverse = reverse_dependency_map(dep_map)
    changed_set = set(changed_filenames)
    stale_names: List[str] = []
    for changed in changed_filenames:
        for dependent in reverse.get(changed, []):
            if dependent in changed_set:
                continue
            if dependent not in stale_names:
                stale_names.append(dependent)

    stale_paths: List[str] = []
    name_to_path = {Path(p).name: p for p in remaining_draft_files}
    for name in stale_names:
        path_str = name_to_path.get(name)
        if not path_str:
            continue
        marker = Path(path_str + ".stale")
        try:
            marker.write_text(
                "Marked stale by the cascade collision gate: an upstream draft "
                "issue was structurally changed during refinement.\n",
                encoding="utf-8",
            )
            stale_paths.append(path_str)
        except Exception as exc:
            logger.warning(f"Could not write stale marker for {path_str}: {exc}")
    if stale_paths:
        logger.info(
            f"Cascade collision gate marked {len(stale_paths)} draft(s) stale: "
            f"{stale_paths}"
        )
    return stale_paths


def _zt_config_from_state(state: RefinementState) -> ZeroToleranceConfig:
    raw = state.get("zero_tolerance_config", {}) or {}
    return ZeroToleranceConfig.model_validate(raw)
