"""Dashboard aggregation helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from sibyl.event_logger import EventLogger
from sibyl.workspace import Workspace

from .constants import CHECKPOINT_DIRS, PIPELINE_STAGES
from .workspace_paths import resolve_workspace_root


def collect_dashboard_data(workspace_path: str | Path, events_tail: int = 50) -> dict:
    """Aggregate dashboard data for the web UI and CLI consumers."""
    from sibyl.gpu_scheduler import _load_progress

    workspace_root = resolve_workspace_root(workspace_path)
    ws = Workspace.open_existing(workspace_root.parent, workspace_root.name)
    el = EventLogger(ws.root)

    project_status = ws.get_project_metadata()
    project_status["topic"] = ws.read_file("topic.txt") or ""

    stage_durations = el.get_stage_durations()
    agent_summary = el.get_agent_summary()
    recent_events = el.tail(events_tail)

    experiment_progress = {}
    try:
        completed, running_ids, running_map, timings = _load_progress(ws.active_root)
        experiment_progress["gpu_progress"] = {
            "completed": sorted(completed),
            "running": sorted(running_ids),
            "running_map": running_map,
            "timings": timings,
        }
    except Exception:
        pass

    exp_state_path = ws.active_path("exp/experiment_state.json")
    if exp_state_path.exists():
        try:
            experiment_progress["experiment_state"] = json.loads(
                exp_state_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            pass

    monitor_path = ws.active_path("exp/monitor_status.json")
    if monitor_path.exists():
        try:
            experiment_progress["monitor"] = json.loads(
                monitor_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            pass

    checkpoints = {}
    for stage_name, cp_dir in CHECKPOINT_DIRS.items():
        if ws.has_checkpoint(cp_dir):
            checkpoints[stage_name] = ws.validate_checkpoint(cp_dir)

    quality_trend = []
    try:
        from sibyl.reflection import IterationLogger

        il = IterationLogger(ws.root)
        history = il.get_history()
        quality_trend = [
            {
                "iteration": h["iteration"],
                "score": h["quality_score"],
                "timestamp": h["timestamp"],
            }
            for h in history
        ]
    except Exception:
        pass

    lark_sync = None
    sync_path = ws.root / "lark_sync" / "sync_status.json"
    if sync_path.exists():
        try:
            lark_sync = json.loads(sync_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    errors = []
    errors_path = ws.root / "logs" / "errors.jsonl"
    if errors_path.exists():
        try:
            lines = errors_path.read_text(encoding="utf-8").strip().split("\n")
            for line in lines[-20:]:
                if line.strip():
                    errors.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "status": project_status,
        "runtime": ws.get_runtime_metadata(),
        "stages": PIPELINE_STAGES,
        "stage_durations": stage_durations,
        "agent_summary": agent_summary,
        "recent_events": recent_events,
        "experiment_progress": experiment_progress,
        "checkpoints": checkpoints,
        "quality_trend": quality_trend,
        "lark_sync_status": lark_sync,
        "errors": errors,
    }
