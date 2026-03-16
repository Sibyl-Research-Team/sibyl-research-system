"""Lifecycle helpers for orchestrator action generation and stage recording."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

from .action_dispatcher import render_execution_script
from .agent_helpers import resolve_model_tier


_NO_SYNC_TRIGGER = {"init", "quality_gate", "done", "lark_sync"}


def get_next_action(orchestrator: Any, *, action_cls: type[Any]) -> dict:
    """Determine and return the next action based on current state."""
    orchestrator.workspace_path = str(orchestrator.ws.active_root)
    status = orchestrator.ws.get_status()

    if status.stop_requested:
        stopped_at = (
            f"项目已于 {time.strftime('%H:%M', time.localtime(status.stop_requested_at))} 手动停止。"
            if status.stop_requested_at is not None
            else "项目已手动停止。"
        )
        result = asdict(action_cls(
            action_type="stopped",
            description=f"{stopped_at}使用 /sibyl-research:resume 重新进入自治循环。",
            stage=status.stage,
            iteration=status.iteration,
        ))
        result["execution_script"] = render_execution_script(result)
        return result

    if status.paused:
        orchestrator.ws.resume()
        status = orchestrator.ws.get_status()

    stage = status.stage
    topic = orchestrator.ws.read_file("topic.txt") or ""
    action = orchestrator._compute_action(stage, topic, status.iteration)
    if action.iteration == 0:
        action.iteration = status.iteration

    if action.agents:
        for agent in action.agents:
            tier, model = resolve_model_tier(orchestrator.config, agent["name"])
            agent["model_tier"] = tier
            agent["model"] = model

    result = asdict(action)
    result["language"] = orchestrator.config.language

    # Inject pre-compiled execution script for deterministic dispatch
    if not result.get("execution_script"):
        result["execution_script"] = render_execution_script(result)

    return result


def append_pending_sync(orchestrator: Any, stage: str) -> None:
    """Append a sync trigger to lark_sync/pending_sync.jsonl."""
    import datetime

    entry = {
        "trigger_stage": stage,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "iteration": orchestrator.ws.get_status().iteration,
    }
    sync_dir = orchestrator.ws.root / "lark_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    with open(sync_dir / "pending_sync.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def record_result(
    orchestrator: Any,
    stage: str,
    result: str = "",
    score: float | None = None,
) -> None:
    """Record the result of a completed stage and advance state."""
    if stage == "done":
        raise ValueError("Cannot record result for terminal stage 'done'")

    current = orchestrator.ws.get_status().stage
    if stage != current:
        try:
            if orchestrator.STAGES.index(stage) < orchestrator.STAGES.index(current):
                return
        except ValueError:
            pass
        raise ValueError(
            f"Stage mismatch: recording '{stage}' but current is '{current}'"
        )

    if stage == "reflection":
        orchestrator._post_reflection_hook()

    next_stage, new_iteration = orchestrator._get_next_stage(stage, result, score)
    if new_iteration is not None:
        orchestrator.ws.update_stage_and_iteration(next_stage, new_iteration)
    else:
        orchestrator.ws.update_stage(next_stage)

    if score is not None:
        orchestrator.ws.write_file(f"logs/stage_{stage}_score.txt", f"{score}")

    score_str = f" (score={score})" if score is not None else ""
    orchestrator.ws.git_commit(f"sibyl: complete {stage}{score_str}")

    if orchestrator.config.lark_enabled and stage not in _NO_SYNC_TRIGGER:
        append_pending_sync(orchestrator, stage)

    return {"sync_requested": orchestrator.config.lark_enabled and stage not in _NO_SYNC_TRIGGER}
