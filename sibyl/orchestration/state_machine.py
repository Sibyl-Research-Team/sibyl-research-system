"""State-transition helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .review_artifacts import extract_supervisor_score
from .constants import CHECKPOINT_DIRS
from .prompt_loader import _load_workspace_action_plan
from .workspace_paths import project_marker_file


def parse_quality_gate_params(orchestrator: Any) -> tuple[float, float, int]:
    """Parse quality gate parameters from supervisor review and reflection plan."""
    _, score = extract_supervisor_score(orchestrator.ws)
    threshold = 8.0
    max_iters = orchestrator.config.max_iterations
    max_iters_cap = orchestrator.config.max_iterations_cap
    if max_iters_cap > 0:
        max_iters_cap = max(max_iters_cap, max_iters)
    action_plan = _load_workspace_action_plan(orchestrator.ws, persist_normalized=True)
    if action_plan:
        value = action_plan.get("suggested_threshold_adjustment")
        if isinstance(value, (int, float)) and 1.0 <= value <= 10.0:
            threshold = float(value)
        value = action_plan.get("suggested_max_iterations")
        if (
            isinstance(value, int)
            and value >= 2
            and (max_iters_cap <= 0 or value <= max_iters_cap)
        ):
            max_iters = value
    return score, threshold, max_iters


def is_pipeline_done(orchestrator: Any) -> tuple[bool, float, float, int, int]:
    """Determine if the pipeline should terminate."""
    score, threshold, max_iters = parse_quality_gate_params(orchestrator)
    iteration = orchestrator.ws.get_status().iteration
    done = (score >= threshold and iteration >= 2) or iteration >= max_iters
    return done, score, threshold, max_iters, iteration


def get_next_stage(
    orchestrator: Any,
    current_stage: str,
    result: str = "",
    score: float | None = None,
) -> tuple[str, int | None]:
    """Determine the next stage based on current stage and result."""
    return natural_next_stage(orchestrator, current_stage, result, score)


def natural_next_stage(
    orchestrator: Any,
    current_stage: str,
    result: str = "",
    score: float | None = None,
) -> tuple[str, int | None]:
    """Compute the next stage, including loop/iteration side effects."""
    if current_stage == "experiment_decision":
        decision = orchestrator.ws.read_file("supervisor/experiment_analysis.md")
        if decision is None:
            orchestrator.ws.add_error("PIVOT check: supervisor/experiment_analysis.md not found")
            decision = ""
        if "DECISION: PIVOT" in decision.upper():
            cycle = get_current_cycle(orchestrator)
            if cycle < orchestrator.config.idea_exp_cycles:
                iteration = orchestrator.ws.get_status().iteration
                orchestrator.ws.write_file(
                    f"logs/idea_exp_cycle_{cycle + 1}.marker",
                    f"PIVOT at iteration {iteration}",
                )
                prepare_idea_refinement_round(
                    orchestrator,
                    f"experiment_decision pivot round {cycle + 1}",
                )
                return ("idea_debate", None)
            orchestrator.ws.add_error(
                "PIVOT requested but cycle limit reached "
                f"({cycle}/{orchestrator.config.idea_exp_cycles})"
            )

    if current_stage == "idea_validation_decision":
        payload = load_idea_validation_decision(orchestrator)
        decision = str(payload.get("decision", "ADVANCE")).upper() or "ADVANCE"
        selected_candidate_id = str(payload.get("selected_candidate_id", "")).strip()
        if decision not in {"ADVANCE", "REFINE", "PIVOT"}:
            orchestrator.ws.add_error(
                f"Unknown idea validation decision '{decision}', falling back to ADVANCE"
            )
            decision = "ADVANCE"

        if decision in {"REFINE", "PIVOT"}:
            validation_round = get_current_validation_round(orchestrator)
            if (
                orchestrator.config.idea_validation_rounds > 0
                and validation_round >= orchestrator.config.idea_validation_rounds
            ):
                orchestrator.ws.add_error(
                    "Idea validation requested more refinement rounds than allowed "
                    f"({validation_round}/{orchestrator.config.idea_validation_rounds}); "
                    "advancing with current best candidate"
                )
            else:
                next_round = validation_round + 1
                orchestrator.ws.write_file(
                    f"logs/idea_validation_round_{next_round}.marker",
                    (
                        f"{decision} after pilot validation round {next_round} "
                        f"(selected={selected_candidate_id or 'none'})"
                    ),
                )
                prepare_idea_refinement_round(
                    orchestrator,
                    f"idea_validation_decision {decision.lower()} round {next_round}",
                )
                return ("idea_debate", None)

        apply_candidate_selection(orchestrator, selected_candidate_id)
        return ("experiment_cycle", None)

    if current_stage in ("pilot_experiments", "experiment_cycle"):
        from sibyl.gpu_scheduler import get_batch_info, get_running_gpu_ids
        from sibyl.experiment_recovery import (
            get_running_tasks as get_exp_running,
            load_experiment_state,
        )

        exp_mode = "PILOT" if current_stage == "pilot_experiments" else "FULL"
        exp_state = load_experiment_state(orchestrator.ws.active_root)
        exp_running = get_exp_running(exp_state)
        if exp_running:
            return (current_stage, None)
        running_gpus = get_running_gpu_ids(orchestrator.ws.active_root)
        if running_gpus:
            return (current_stage, None)
        info = get_batch_info(
            orchestrator.ws.active_root,
            list(range(orchestrator.config.max_gpus)),
            exp_mode,
            gpus_per_task=orchestrator.config.gpus_per_task,
        )
        if info is not None and len(info["batch"]) > 0:
            return (current_stage, None)

    if current_stage == "writing_final_review":
        review = orchestrator.ws.read_file("writing/review.md") or ""
        match = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", review, re.IGNORECASE)
        review_score = float(match.group(1)) if match else 5.0
        critique_dir = orchestrator.ws.active_path("writing/critique")
        if critique_dir.exists():
            revision_rounds = len([
                path for path in critique_dir.iterdir()
                if path.is_file() and path.name.startswith("revision_round_")
            ])
        else:
            revision_rounds = 0
        max_revisions = orchestrator.config.writing_revision_rounds
        if review_score < 7.0 and revision_rounds < max_revisions:
            orchestrator.ws.write_file(
                f"writing/critique/revision_round_{revision_rounds + 1}.marker",
                f"Revision round {revision_rounds + 1}, score={review_score}",
            )
            return ("writing_integrate", None)

    if current_stage == "idea_debate":
        if orchestrator.config.codex_enabled and orchestrator.config.codex_idea_rounds > 0:
            verdict = load_codex_idea_verdict(orchestrator)
            if verdict == "REVISE":
                codex_round = get_current_codex_idea_round(orchestrator)
                if codex_round < orchestrator.config.codex_idea_rounds:
                    orchestrator.ws.write_file(
                        f"logs/codex_idea_round_{codex_round + 1}.marker",
                        f"Codex REVISE at idea_debate round {codex_round + 1}",
                    )
                    prepare_idea_refinement_round(
                        orchestrator,
                        f"codex idea revision round {codex_round + 1}",
                    )
                    return ("idea_debate", None)
                orchestrator.ws.add_error(
                    "Codex requested REVISE but codex_idea_rounds limit reached "
                    f"({codex_round}/{orchestrator.config.codex_idea_rounds}); advancing"
                )

    if current_stage == "init":
        return ("literature_search", None)

    if current_stage == "reflection" and not orchestrator.config.lark_enabled:
        return ("quality_gate", None)

    if current_stage == "writing_latex" and not orchestrator.config.review_enabled:
        return ("reflection", None)

    if current_stage == "pilot_experiments":
        reset_experiment_runtime_state(orchestrator)
        if orchestrator.config.idea_validation_rounds > 0:
            return ("idea_validation_decision", None)
        return ("experiment_cycle", None)

    if current_stage == "quality_gate":
        is_done, qg_score, threshold, max_iters, iteration = is_pipeline_done(orchestrator)
        if is_done:
            orchestrator.ws.git_tag(
                f"v{iteration}",
                f"Iteration {iteration} complete, score={qg_score}",
            )
            return ("done", None)

        orchestrator.ws.git_tag(
            f"iter-{iteration}",
            f"End of iteration {iteration}, score={qg_score}",
        )
        try:
            orchestrator.ws.archive_iteration(iteration)
        except OSError as exc:
            orchestrator.ws.add_error(f"Archive failed for iteration {iteration}: {exc}")
        if orchestrator.ws.get_status().iteration_dirs:
            orchestrator.ws.start_new_iteration(iteration + 1)
        else:
            clear_iteration_artifacts(orchestrator, iteration)
        return ("literature_search", iteration + 1)

    try:
        idx = orchestrator.STAGES.index(current_stage)
        if idx + 1 < len(orchestrator.STAGES):
            return (orchestrator.STAGES[idx + 1], None)
    except ValueError:
        orchestrator.ws.add_error(f"Unknown stage '{current_stage}', forcing done")
        return ("done", None)
    return (current_stage, None)


def clear_iteration_artifacts(orchestrator: Any, iteration: int = 0) -> None:
    """Clear stale working-directory artifacts between iterations."""
    lessons_path = orchestrator.ws.active_path("reflection/lessons_learned.md")
    lessons_content = None
    if lessons_path.exists():
        lessons_content = lessons_path.read_text(encoding="utf-8")

    action_plan_path = orchestrator.ws.active_path("reflection/action_plan.json")
    action_plan_content = None
    if action_plan_path.exists():
        action_plan_content = action_plan_path.read_text(encoding="utf-8")

    dirs_to_clear = [
        "idea/perspectives",
        "idea/debate",
        "idea/result_debate",
        "plan",
        "writing/sections",
        "writing/critique",
        "supervisor",
        "critic",
        "reflection",
    ]
    for subdir in dirs_to_clear:
        target = orchestrator.ws.active_path(subdir)
        if target.exists():
            try:
                shutil.rmtree(target)
                target.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    gpu_progress = orchestrator.ws.active_path("exp/gpu_progress.json")
    if gpu_progress.exists():
        try:
            gpu_progress.unlink()
        except OSError:
            pass

    exp_state_path = orchestrator.ws.active_path("exp/experiment_state.json")
    if exp_state_path.exists():
        try:
            history_dir = orchestrator.ws.active_path("exp/history")
            history_dir.mkdir(parents=True, exist_ok=True)
            archive_name = f"experiment_state_iter_{iteration:03d}.json"
            shutil.copy2(exp_state_path, history_dir / archive_name)
            exp_state_path.unlink()
        except OSError:
            pass

    logs_dir = orchestrator.ws.project_path("logs")
    if logs_dir.exists():
        for marker in logs_dir.glob("idea_exp_cycle_*.marker"):
            try:
                marker.unlink()
            except OSError:
                pass
        for marker in logs_dir.glob("idea_validation_round_*.marker"):
            try:
                marker.unlink()
            except OSError:
                pass
        for marker in logs_dir.glob("codex_idea_round_*.marker"):
            try:
                marker.unlink()
            except OSError:
                pass

    for cp_dir in CHECKPOINT_DIRS.values():
        orchestrator.ws.clear_checkpoint(cp_dir)

    if lessons_content:
        orchestrator.ws.write_file("reflection/lessons_learned.md", lessons_content)
    if action_plan_content:
        orchestrator.ws.write_file("reflection/prev_action_plan.json", action_plan_content)


def reset_experiment_runtime_state(orchestrator: Any) -> None:
    """Clear transient experiment scheduler state before the full stage."""
    from sibyl.gpu_scheduler import sync_workspace_gpu_leases

    gpu_progress = orchestrator.ws.active_path("exp/gpu_progress.json")
    if gpu_progress.exists():
        try:
            gpu_progress.unlink()
        except OSError:
            pass

    results_dir = orchestrator.ws.active_path("exp/results")
    if results_dir.exists():
        for marker in results_dir.glob("*_DONE"):
            try:
                marker.unlink()
            except OSError:
                pass

    for suffix in ("exp_monitor", "gpu_free"):
        marker_path = Path(project_marker_file(orchestrator.ws.root, suffix))
        try:
            marker_path.unlink()
        except OSError:
            pass

    exp_state_path = orchestrator.ws.active_path("exp/experiment_state.json")
    if exp_state_path.exists():
        try:
            exp_state_path.unlink()
        except OSError:
            pass

    sync_workspace_gpu_leases(orchestrator.ws.active_root, {})


def get_current_codex_idea_round(orchestrator: Any) -> int:
    """Get current Codex-guided idea refinement round count."""
    logs_dir = orchestrator.ws.project_path("logs")
    if not logs_dir.exists():
        return 0
    return len(list(logs_dir.glob("codex_idea_round_*.marker")))


def load_codex_idea_verdict(orchestrator: Any) -> str:
    """Load the Codex idea-debate verdict (APPROVE or REVISE).

    Returns "APPROVE" if the review is missing, unparseable, or doesn't
    contain a recognized verdict — the pipeline should not block on Codex failures.
    """
    content = orchestrator.ws.read_file("codex/idea_debate_review.md")
    if not content:
        return "APPROVE"
    match = re.search(r"VERDICT:\s*(APPROVE|REVISE)", content, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return "APPROVE"


def get_current_cycle(orchestrator: Any) -> int:
    """Get current idea-experiment cycle number."""
    logs_dir = orchestrator.ws.project_path("logs")
    if not logs_dir.exists():
        return 0
    return len(list(logs_dir.glob("idea_exp_cycle_*.marker")))


def get_current_validation_round(orchestrator: Any) -> int:
    """Get current pilot-guided idea refinement round count."""
    logs_dir = orchestrator.ws.project_path("logs")
    if not logs_dir.exists():
        return 0
    return len(list(logs_dir.glob("idea_validation_round_*.marker")))


def prepare_idea_refinement_round(orchestrator: Any, reason: str) -> None:
    """Clear idea-debate transient artifacts so a refinement round can rerun."""
    for subdir in ("idea/perspectives", "idea/debate"):
        target = orchestrator.ws.active_path(subdir)
        try:
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    # Clear stale Codex verdict so the next round gets a fresh review
    codex_review = orchestrator.ws.active_path("codex/idea_debate_review.md")
    try:
        if codex_review.exists():
            codex_review.unlink()
    except OSError:
        pass
    cp_dir = CHECKPOINT_DIRS.get("idea_debate")
    if cp_dir:
        orchestrator.ws.clear_checkpoint(cp_dir)
    orchestrator.ws.write_file("logs/idea_refinement_state.txt", reason)


def load_json_artifact(orchestrator: Any, relative_path: str) -> dict | None:
    """Best-effort JSON loader for workspace artifacts."""
    content = orchestrator.ws.read_file(relative_path)
    if not content:
        return None
    try:
        data = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        orchestrator.ws.add_error(f"Failed to parse JSON artifact: {relative_path}")
        return None
    return data if isinstance(data, dict) else None


def load_idea_validation_decision(orchestrator: Any) -> dict:
    """Load idea validation decision with JSON-first, markdown-fallback parsing."""
    payload = load_json_artifact(orchestrator, "supervisor/idea_validation_decision.json") or {}

    decision = str(payload.get("decision", "")).upper()
    if decision in {"ADVANCE", "REFINE", "PIVOT"}:
        return payload

    content = orchestrator.ws.read_file("supervisor/idea_validation_decision.md") or ""
    match = re.search(r"DECISION:\s*(ADVANCE|REFINE|PIVOT)", content, re.IGNORECASE)
    if match:
        payload["decision"] = match.group(1).upper()
    selected = re.search(
        r"SELECTED_CANDIDATE:\s*([A-Za-z0-9_.-]+)",
        content,
        re.IGNORECASE,
    )
    if selected and "selected_candidate_id" not in payload:
        payload["selected_candidate_id"] = selected.group(1)
    confidence = re.search(r"CONFIDENCE:\s*(\d+(?:\.\d+)?)", content, re.IGNORECASE)
    if confidence and "confidence" not in payload:
        payload["confidence"] = float(confidence.group(1))
    return payload


def task_matches_candidate(task: dict, selected_candidate_id: str) -> bool:
    """Return True when a task should survive candidate selection."""
    if not selected_candidate_id:
        return True
    candidate_id = task.get("candidate_id")
    if not candidate_id:
        return True
    if isinstance(candidate_id, list):
        return selected_candidate_id in candidate_id or "shared" in candidate_id
    return candidate_id in {selected_candidate_id, "shared"}


def apply_candidate_selection(orchestrator: Any, selected_candidate_id: str) -> None:
    """Filter task_plan.json down to the chosen candidate plus shared tasks."""
    if not selected_candidate_id:
        return

    task_plan_path = orchestrator.ws.active_path("plan/task_plan.json")
    if not task_plan_path.exists():
        return

    try:
        plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        orchestrator.ws.add_error("Failed to parse plan/task_plan.json during candidate selection")
        return

    tasks = plan.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        return

    filtered = [
        task for task in tasks
        if isinstance(task, dict) and task_matches_candidate(task, selected_candidate_id)
    ]
    if not filtered:
        orchestrator.ws.add_error(
            "Candidate selection produced an empty task plan; keeping the original plan"
        )
        return

    kept_ids = {task.get("id") for task in filtered if task.get("id")}
    for task in filtered:
        deps = task.get("depends_on")
        if isinstance(deps, list):
            task["depends_on"] = [dep for dep in deps if dep in kept_ids]

    plan["tasks"] = filtered
    orchestrator.ws.write_file(
        "plan/task_plan.json",
        json.dumps(plan, indent=2, ensure_ascii=False),
    )
    orchestrator.ws.write_file(
        "plan/selected_candidate.json",
        json.dumps(
            {
                "selected_candidate_id": selected_candidate_id,
                "kept_task_count": len(filtered),
            },
            indent=2,
            ensure_ascii=False,
        ),
    )
