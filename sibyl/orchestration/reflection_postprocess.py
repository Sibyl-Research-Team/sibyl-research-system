"""Reflection post-processing helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sibyl.event_logger import EventLogger

from .review_artifacts import (
    extract_supervisor_issues,
    extract_supervisor_score,
    summarize_critic_findings,
    summarize_supervisor_review,
)


def _load_reflection_payload(
    orchestrator: Any,
    *,
    load_workspace_action_plan: Callable[..., dict | None],
) -> tuple[dict, list[dict], list[str], list[str], str]:
    """Load normalized reflection payload and derive issue tracking fields."""
    from sibyl.evolution import IssueCategory, normalize_issue_entry

    action_plan = load_workspace_action_plan(
        orchestrator.ws,
        "reflection/action_plan.json",
        persist_normalized=True,
    ) or {}
    classified_issues = [
        issue
        for issue in action_plan.get("issues_classified", [])
        if issue.get("status") != "fixed"
    ]
    issues_fixed = list(action_plan.get("issues_fixed", []))
    quality_trajectory = action_plan.get("quality_trajectory", "stagnant")

    if not classified_issues:
        for issue in extract_supervisor_issues(orchestrator.ws):
            normalized_issue = normalize_issue_entry(
                {
                    "description": issue.get("description", ""),
                    "category": issue.get("category")
                    or IssueCategory.classify(issue.get("description", "")).value,
                    "severity": issue.get("severity", "medium"),
                    "status": issue.get("status", "new"),
                    "issue_key": issue.get("issue_key", ""),
                    "suggestion": issue.get("suggestion", ""),
                }
            )
            if normalized_issue is not None and normalized_issue.get("status") != "fixed":
                classified_issues.append(normalized_issue)

    issues_found = [
        issue.get("description", "")
        for issue in classified_issues
        if issue.get("description")
    ]
    issues_fixed = _merge_inferred_fixed_issues(
        orchestrator,
        classified_issues,
        issues_fixed,
        load_workspace_action_plan=load_workspace_action_plan,
    )
    return (
        action_plan,
        classified_issues,
        issues_found,
        issues_fixed,
        quality_trajectory,
    )


def _merge_inferred_fixed_issues(
    orchestrator: Any,
    classified_issues: list[dict],
    issues_fixed: list[str],
    *,
    load_workspace_action_plan: Callable[..., dict | None],
) -> list[str]:
    prev_plan = load_workspace_action_plan(
        orchestrator.ws,
        "reflection/prev_action_plan.json",
    ) or {}
    prev_issues_by_key: dict[str, str] = {}
    for issue in prev_plan.get("issues_classified", []):
        if issue.get("status") == "fixed":
            continue
        issue_key = str(issue.get("issue_key", "")).strip()
        description = str(issue.get("description", "")).strip()
        if issue_key and description and issue_key not in prev_issues_by_key:
            prev_issues_by_key[issue_key] = description

    current_issue_keys = {
        str(issue.get("issue_key", "")).strip()
        for issue in classified_issues
        if issue.get("issue_key")
    }
    inferred_fixed = [
        description
        for issue_key, description in prev_issues_by_key.items()
        if issue_key not in current_issue_keys
    ]
    return list(dict.fromkeys([*issues_fixed, *inferred_fixed]))


def _extract_quality_score(orchestrator: Any) -> tuple[str, float]:
    supervisor_review = summarize_supervisor_review(orchestrator.ws)
    _, score = extract_supervisor_score(orchestrator.ws)
    return supervisor_review, score


def _log_iteration(
    orchestrator: Any,
    *,
    iteration: int,
    issues_found: list[str],
    issues_fixed: list[str],
    score: float,
    classified_issues: list[dict],
    quality_trajectory: str,
) -> None:
    from sibyl.reflection import IterationLogger

    logger = IterationLogger(orchestrator.ws.root)
    logger.log_iteration(
        iteration=iteration,
        stage="reflection",
        changes=[f"Iteration {iteration} complete"],
        issues_found=issues_found[:10],
        issues_fixed=issues_fixed[:10],
        quality_score=score,
        notes=json.dumps(
            {
                "classified_issues": classified_issues[:10],
                "quality_trajectory": quality_trajectory,
            },
            ensure_ascii=False,
        ),
    )


def _append_research_diary(
    orchestrator: Any,
    *,
    iteration: int,
    issues_found: list[str],
    issues_fixed: list[str],
    quality_trajectory: str,
    supervisor_review: str,
    score: float,
) -> None:
    critic_feedback = summarize_critic_findings(orchestrator.ws)
    reflection_md = orchestrator.ws.read_file("reflection/reflection.md") or ""
    fixed_str = f"**Fixed**: {len(issues_fixed)}\n" if issues_fixed else ""
    trajectory_str = (
        f"**Trajectory**: {quality_trajectory}\n" if quality_trajectory else ""
    )
    diary_entry = (
        f"# Iteration {iteration}\n\n"
        f"**Score**: {score}/10\n"
        f"**Issues**: {len(issues_found)}\n"
        f"{fixed_str}"
        f"{trajectory_str}\n"
        f"## Reflection\n{reflection_md[:1000]}\n\n"
        f"## Review Summary\n{supervisor_review[:500]}\n\n"
        f"## Critique Summary\n{critic_feedback[:500]}\n"
    )
    existing_diary = orchestrator.ws.read_file("logs/research_diary.md") or ""
    orchestrator.ws.write_file(
        "logs/research_diary.md",
        existing_diary + "\n\n" + diary_entry,
    )


def _emit_iteration_complete(
    orchestrator: Any,
    *,
    iteration: int,
    score: float,
    issues_found: list[str],
) -> None:
    EventLogger(orchestrator.ws.root).iteration_complete(
        iteration=iteration,
        score=score,
        issues_count=len(issues_found),
    )


def _record_evolution_outcome(
    orchestrator: Any,
    *,
    iteration: int,
    issues_found: list[str],
    score: float,
    quality_trajectory: str,
    classified_issues: list[dict],
    success_patterns: list[str],
) -> None:
    from sibyl.evolution import EvolutionEngine, sync_workspace_snapshot

    engine = EvolutionEngine()
    engine.record_outcome(
        project=orchestrator.ws.name,
        stage="reflection",
        issues=issues_found,
        score=score,
        notes=f"Iteration {iteration}; trajectory={quality_trajectory}",
        classified_issues=classified_issues[:10],
        success_patterns=success_patterns[:10],
    )
    engine.run_cross_project_evolution()
    sync_workspace_snapshot(orchestrator.ws.root)


def _write_quality_trend(orchestrator: Any) -> None:
    from sibyl.evolution import EvolutionEngine

    engine = EvolutionEngine()
    trend = engine.get_quality_trend(project=orchestrator.ws.name)
    if not trend:
        return

    trend_lines = ["# 质量趋势\n"]
    for entry in trend[-10:]:
        trend_lines.append(f"- {entry['timestamp']}: score={entry['score']}")
    scores = [entry["score"] for entry in trend]
    if len(scores) >= 2:
        delta = scores[-1] - scores[-2]
        direction = "上升" if delta > 0 else ("下降" if delta < 0 else "持平")
        trend_lines.append(f"\n趋势: {direction} (Δ={delta:+.1f})")
    orchestrator.ws.write_file("logs/quality_trend.md", "\n".join(trend_lines))


def _write_self_check_diagnostics(orchestrator: Any) -> None:
    from sibyl.evolution import EvolutionEngine

    engine = EvolutionEngine()
    diagnostics = engine.get_self_check_diagnostics(project=orchestrator.ws.name)
    if diagnostics:
        orchestrator.ws.write_file(
            "logs/self_check_diagnostics.json",
            json.dumps(diagnostics, indent=2, ensure_ascii=False),
        )
        return

    diag_path = orchestrator.ws.project_path("logs/self_check_diagnostics.json")
    if diag_path.exists():
        diag_path.unlink()


def run_post_reflection_hook(
    orchestrator: Any,
    *,
    load_workspace_action_plan: Callable[..., dict | None],
) -> None:
    """Process reflection outputs and persist iteration/evolution side effects."""
    iteration = orchestrator.ws.get_status().iteration
    (
        _action_plan,
        classified_issues,
        issues_found,
        issues_fixed,
        quality_trajectory,
    ) = _load_reflection_payload(
        orchestrator,
        load_workspace_action_plan=load_workspace_action_plan,
    )
    success_patterns = (
        _action_plan.get("success_patterns", [])
        if isinstance(_action_plan, dict)
        else []
    )
    supervisor_review, score = _extract_quality_score(orchestrator)

    try:
        _log_iteration(
            orchestrator,
            iteration=iteration,
            issues_found=issues_found,
            issues_fixed=issues_fixed,
            score=score,
            classified_issues=classified_issues,
            quality_trajectory=quality_trajectory,
        )
    except Exception as exc:
        orchestrator.ws.add_error(f"Reflection logging failed: {exc}")

    try:
        _append_research_diary(
            orchestrator,
            iteration=iteration,
            issues_found=issues_found,
            issues_fixed=issues_fixed,
            quality_trajectory=quality_trajectory,
            supervisor_review=supervisor_review,
            score=score,
        )
    except Exception as exc:
        orchestrator.ws.add_error(f"Diary update failed: {exc}")

    try:
        _emit_iteration_complete(
            orchestrator,
            iteration=iteration,
            score=score,
            issues_found=issues_found,
        )
    except Exception:
        pass

    try:
        if orchestrator.config.evolution_enabled:
            _record_evolution_outcome(
                orchestrator,
                iteration=iteration,
                issues_found=issues_found,
                score=score,
                quality_trajectory=quality_trajectory,
                classified_issues=classified_issues,
                success_patterns=success_patterns,
            )
    except Exception as exc:
        orchestrator.ws.add_error(f"Evolution recording failed: {exc}")

    try:
        if orchestrator.config.evolution_enabled:
            _write_quality_trend(orchestrator)
    except Exception as exc:
        orchestrator.ws.add_error(f"Quality trend recording failed: {exc}")

    try:
        if orchestrator.config.evolution_enabled:
            _write_self_check_diagnostics(orchestrator)
    except Exception as exc:
        orchestrator.ws.add_error(f"Self-check diagnostics failed: {exc}")
