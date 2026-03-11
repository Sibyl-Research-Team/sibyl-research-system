"""Core CLI helpers extracted from the legacy orchestrator module."""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sibyl._paths import get_system_state_dir
from sibyl.event_logger import EventLogger
from sibyl.workspace import Workspace, workspace_status_from_data

from .dashboard_data import collect_dashboard_data
from .writing_artifacts import extract_section_figure_artifacts
from .workspace_paths import (
    resolve_active_workspace_path,
    resolve_workspace_root,
    workspace_scope_id,
)


_LOOP_ACTION_TYPES = {"experiment_wait", "gpu_poll"}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sentinel_registry_path() -> Path:
    state_dir = get_system_state_dir() / "sentinel"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "session_registry.json"


@contextmanager
def _sentinel_registry_lock():
    lock_path = _sentinel_registry_path().with_suffix(".lock")
    lock_fd = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _load_sentinel_registry_unlocked() -> dict[str, dict]:
    data = _read_json(_sentinel_registry_path())
    workspaces = data.get("workspaces", data)
    if not isinstance(workspaces, dict):
        return {}
    return {
        str(workspace_root): entry
        for workspace_root, entry in workspaces.items()
        if isinstance(entry, dict)
    }


def _save_sentinel_registry_unlocked(workspaces: dict[str, dict]) -> None:
    _write_json_atomic(
        _sentinel_registry_path(),
        {"workspaces": workspaces, "updated_at": time.time()},
    )


def _load_workspace_sentinel_state(workspace_root: Path) -> dict:
    workspace_root = resolve_workspace_root(workspace_root)
    active_root = resolve_active_workspace_path(workspace_root)
    session_data = _read_json(workspace_root / "sentinel_session.json")
    heartbeat = _read_json(workspace_root / "sentinel_heartbeat.json")

    has_running = False
    exp_state_path = active_root / "exp" / "experiment_state.json"
    exp_data = _read_json(exp_state_path)
    for task in exp_data.get("tasks", {}).values():
        if isinstance(task, dict) and task.get("status") == "running":
            has_running = True
            break

    if not has_running:
        gpu_progress = _read_json(active_root / "exp" / "gpu_progress.json")
        has_running = bool(gpu_progress.get("running"))

    raw_status = _read_json(workspace_root / "status.json")
    status = workspace_status_from_data(raw_status)
    should_keep_running = (
        not status.stop_requested and (has_running or status.stage not in {"", "init", "done"})
    )
    ralph_prompt_path = str((workspace_root / ".claude" / "ralph-prompt.txt").resolve())
    return {
        "workspace_path": str(workspace_root),
        "active_workspace_path": str(active_root),
        "workspace_scope": workspace_scope_id(workspace_root),
        "project_name": workspace_root.name,
        "session_id": session_data.get("session_id", ""),
        "tmux_pane": session_data.get("tmux_pane", ""),
        "heartbeat": heartbeat,
        "has_running_experiments": has_running,
        "stage": status.stage,
        "paused": status.paused,
        "stop_requested": status.stop_requested,
        "auto_resume_pending": status.paused and not status.stop_requested,
        "should_keep_running": should_keep_running,
        "saved_at": session_data.get("saved_at", 0),
        "ralph_prompt_path": session_data.get("ralph_prompt_path", ralph_prompt_path),
        "ownership_conflict": bool(session_data.get("ownership_conflict", False)),
        "conflicts": list(session_data.get("conflicts", [])),
    }


def _cleanup_sentinel_registry_unlocked(registry: dict[str, dict]) -> dict[str, dict]:
    cleaned: dict[str, dict] = {}
    for workspace_key, entry in registry.items():
        try:
            workspace_root = resolve_workspace_root(Path(workspace_key))
        except OSError:
            continue
        if not workspace_root.exists():
            continue
        state = _load_workspace_sentinel_state(workspace_root)
        if not state["should_keep_running"]:
            continue
        if not state["session_id"] and not state["tmux_pane"]:
            continue
        cleaned[str(workspace_root)] = {
            "workspace_root": str(workspace_root),
            "project_name": state["project_name"],
            "workspace_scope": state["workspace_scope"],
            "session_id": state["session_id"],
            "tmux_pane": state["tmux_pane"],
            "saved_at": state["saved_at"],
            "ralph_prompt_path": state["ralph_prompt_path"],
        }
    return cleaned


def _sentinel_conflicts(
    workspace_root: Path,
    registry: dict[str, dict],
    *,
    session_id: str,
    tmux_pane: str,
) -> list[dict]:
    workspace_key = str(resolve_workspace_root(workspace_root))
    conflicts: list[dict] = []
    for other_workspace, entry in registry.items():
        if other_workspace == workspace_key:
            continue
        reasons: list[str] = []
        if session_id and entry.get("session_id") == session_id:
            reasons.append("session_id")
        if tmux_pane and entry.get("tmux_pane") == tmux_pane:
            reasons.append("tmux_pane")
        if reasons:
            conflicts.append({
                "workspace_path": other_workspace,
                "project_name": entry.get("project_name", Path(other_workspace).name),
                "reasons": reasons,
            })
    return conflicts


def write_sentinel_heartbeat(workspace_path: str, stage: str, action: str) -> None:
    """Write heartbeat file for Sentinel watchdog (best-effort)."""
    hb_path = resolve_workspace_root(workspace_path) / "sentinel_heartbeat.json"
    _write_json_atomic(hb_path, {
        "ts": time.time(),
        "stage": stage,
        "action": action,
    })


def write_breadcrumb(
    workspace_path: str,
    action_dict: dict | None = None,
    *,
    stage: str = "",
    completed: bool = False,
) -> None:
    """Write breadcrumb file for context recovery after compaction/restart."""
    _ = completed
    workspace_root = resolve_workspace_root(workspace_path)
    bc_path = workspace_root / "breadcrumb.json"
    if action_dict:
        action_type = action_dict.get("action_type", "")
        payload = {
            "ts": time.time(),
            "stage": action_dict.get("stage", stage),
            "action_type": action_type,
            "iteration": action_dict.get("iteration", 0),
            "workspace_path": str(workspace_root),
            "in_loop": action_type in _LOOP_ACTION_TYPES,
            "loop_type": action_type if action_type in _LOOP_ACTION_TYPES else "",
            "description": action_dict.get("description", "")[:200],
        }
    else:
        payload = {
            "ts": time.time(),
            "stage": stage,
            "action_type": "completed",
            "workspace_path": str(workspace_root),
            "in_loop": False,
            "loop_type": "",
            "description": f"Stage '{stage}' completed, advancing to next",
        }
    _write_json_atomic(bc_path, payload)


def cli_init(
    topic: str,
    project_name: str | None = None,
    config_path: str | None = None,
    *,
    orchestrator_cls: type[Any],
    event_logger_cls: type[Any],
) -> None:
    """CLI: Initialize a project."""
    from .project_cli import _build_post_init_guide
    from .config_helpers import load_effective_config

    result = orchestrator_cls.init_project(topic, project_name, config_path)
    config = load_effective_config(result["workspace_path"], config_path=config_path)
    result["guide"] = _build_post_init_guide(
        result["workspace_path"],
        result["project_name"],
        topic,
        config,
        has_spec=False,
    )
    print(json.dumps(result, indent=2))
    try:
        event_logger_cls(Path(result["workspace_path"])).project_init(
            topic=topic,
            project_name=result.get("project_name", ""),
        )
    except Exception:
        pass


def cli_next(
    workspace_path: str,
    *,
    orchestrator_cls: type[Any],
    event_logger_cls: type[Any],
) -> None:
    """CLI: Get next action."""
    orchestrator = orchestrator_cls(workspace_path)
    action = orchestrator.get_next_action()
    print(json.dumps(action, indent=2))
    try:
        write_sentinel_heartbeat(workspace_path, action.get("stage", ""), "cli_next")
        write_breadcrumb(workspace_path, action_dict=action)
        action_type = action.get("action_type", "")
        if action_type not in ("done", "stopped", "gpu_poll", "experiment_wait"):
            event_logger_cls(Path(workspace_path)).stage_start(
                stage=action.get("stage", ""),
                iteration=action.get("iteration", 0),
                action_type=action_type,
                description=action.get("description", "")[:200],
            )
    except Exception:
        pass


def cli_record(
    workspace_path: str,
    stage: str,
    result: str = "",
    score: float | None = None,
    *,
    orchestrator_cls: type[Any],
    event_logger_cls: type[Any],
) -> None:
    """CLI: Record stage result."""
    orchestrator = orchestrator_cls(workspace_path)
    prev_status = orchestrator.ws.get_status()
    stage_started_at = prev_status.stage_started_at

    orchestrator.record_result(stage, result, score)
    new_status = orchestrator.ws.get_status()
    output = {"status": "ok", "new_stage": new_status.stage}
    no_sync_trigger = {"init", "quality_gate", "done", "lark_sync"}
    if orchestrator.config.lark_enabled and stage not in no_sync_trigger:
        output["sync_requested"] = True
    print(json.dumps(output))
    try:
        write_sentinel_heartbeat(workspace_path, stage, "cli_record")
        write_breadcrumb(workspace_path, stage=stage, completed=True)
        duration = (time.time() - stage_started_at) if stage_started_at else None
        event_logger_cls(Path(workspace_path)).stage_end(
            stage=stage,
            iteration=prev_status.iteration,
            duration_sec=duration,
            score=score,
            next_stage=new_status.stage,
        )
    except Exception:
        pass


def cli_pause(
    workspace_path: str,
    reason: str = "rate_limit",
    *,
    orchestrator_cls: type[Any],
    event_logger_cls: type[Any],
) -> None:
    """CLI: Write a legacy pause marker or manual stop marker."""
    orchestrator = orchestrator_cls(workspace_path)
    orchestrator.ws.pause(reason)
    status = orchestrator.ws.get_status()
    status_value = "stopped" if reason == "user_stop" else "paused"
    print(json.dumps({"status": status_value, "stage": status.stage}))
    try:
        event_logger_cls(Path(workspace_path)).pause(
            reason=reason,
            stage=status.stage,
            iteration=status.iteration,
        )
    except Exception:
        pass


def cli_resume(
    workspace_path: str,
    *,
    orchestrator_cls: type[Any],
    event_logger_cls: type[Any],
) -> None:
    """CLI: Clear stop/pause markers and resume a project."""
    orchestrator = orchestrator_cls(workspace_path)
    orchestrator.ws.resume()
    stop_file = resolve_workspace_root(workspace_path) / "sentinel_stop.json"
    stop_file.unlink(missing_ok=True)
    status = orchestrator.ws.get_status()
    print(json.dumps({"status": "resumed", "stage": status.stage}))
    try:
        event_logger_cls(Path(workspace_path)).resume(
            stage=status.stage,
            iteration=status.iteration,
        )
    except Exception:
        pass


def cli_status(
    workspace_path: str,
) -> None:
    """CLI: Get project status."""
    workspace_root = resolve_workspace_root(workspace_path)
    ws = Workspace.open_existing(workspace_root.parent, workspace_root.name)
    status = ws.get_project_metadata()
    status["topic"] = ws.read_file("topic.txt") or ""
    sync_status_path = ws.root / "lark_sync" / "sync_status.json"
    if sync_status_path.exists():
        try:
            status["lark_sync_status"] = json.loads(sync_status_path.read_text())
        except (json.JSONDecodeError, OSError):
            status["lark_sync_status"] = {"error": "corrupted sync_status.json"}
    print(json.dumps(status, indent=2))


def cli_checkpoint(
    workspace_path: str,
    stage: str,
    step_id: str,
    *,
    checkpoint_dirs: dict[str, str],
) -> None:
    """CLI: Mark a checkpoint sub-step as completed."""
    checkpoint_dir = checkpoint_dirs.get(stage)
    if checkpoint_dir is None:
        print(json.dumps({
            "status": "error",
            "message": f"No checkpoint support for stage '{stage}'",
        }))
        return

    ws_path = Path(workspace_path)
    ws = Workspace(ws_path.parent, ws_path.name)
    artifacts: list[str] | None = None
    has_figures_block = True
    if stage == "writing_sections":
        section_md = ws.read_file(f"writing/sections/{step_id}.md") or ""
        artifacts, has_figures_block = extract_section_figure_artifacts(section_md)
        if not has_figures_block:
            artifacts = None

    result = ws.complete_checkpoint_step(
        checkpoint_dir,
        step_id,
        artifacts=artifacts,
        require_artifacts_metadata=(stage == "writing_sections"),
    )

    payload = {
        "status": "ok",
        "stage": stage,
        "step": step_id,
        "completed": result["completed"],
    }
    if stage == "writing_sections" and not has_figures_block:
        payload["message"] = "section 缺少 <!-- FIGURES --> block，checkpoint 未标记完成"
    elif not result["completed"]:
        payload["message"] = "checkpoint 未标记完成，请补齐缺失产物后重试"
    if result["missing_files"]:
        payload["missing_files"] = result["missing_files"]
    print(json.dumps(payload))
    try:
        status = ws.get_status()
        EventLogger(ws.root).checkpoint_step(
            stage=stage,
            step_id=step_id,
            iteration=status.iteration,
        )
    except Exception:
        pass


def cli_sentinel_session(
    workspace_path: str,
    session_id: str,
    tmux_pane: str = "",
) -> None:
    """CLI: Save Claude Code session ownership for Sentinel and Ralph loop isolation."""
    workspace_root = resolve_workspace_root(workspace_path)
    payload = {
        "workspace_path": str(workspace_root),
        "workspace_scope": workspace_scope_id(workspace_root),
        "project_name": workspace_root.name,
        "session_id": session_id,
        "tmux_pane": tmux_pane,
        "saved_at": time.time(),
        "ralph_prompt_path": str((workspace_root / ".claude" / "ralph-prompt.txt").resolve()),
    }

    with _sentinel_registry_lock():
        registry = _cleanup_sentinel_registry_unlocked(_load_sentinel_registry_unlocked())
        conflicts = _sentinel_conflicts(
            workspace_root,
            registry,
            session_id=session_id,
            tmux_pane=tmux_pane,
        )
        payload["ownership_conflict"] = bool(conflicts)
        payload["conflicts"] = conflicts

        workspace_key = str(workspace_root)
        if conflicts or (not session_id and not tmux_pane):
            registry.pop(workspace_key, None)
        else:
            registry[workspace_key] = {
                "workspace_root": workspace_key,
                "project_name": workspace_root.name,
                "workspace_scope": payload["workspace_scope"],
                "session_id": session_id,
                "tmux_pane": tmux_pane,
                "saved_at": payload["saved_at"],
                "ralph_prompt_path": payload["ralph_prompt_path"],
            }
        _save_sentinel_registry_unlocked(registry)

    _write_json_atomic(workspace_root / "sentinel_session.json", payload)
    print(json.dumps({
        "status": "conflict" if payload["ownership_conflict"] else "ok",
        "workspace_path": str(workspace_root),
        "project_name": workspace_root.name,
        "session_id": session_id,
        "tmux_pane": tmux_pane,
        "ownership_conflict": payload["ownership_conflict"],
        "conflicts": payload["conflicts"],
        "ralph_prompt_path": payload["ralph_prompt_path"],
    }, indent=2))


def cli_sentinel_config(
    workspace_path: str,
) -> None:
    """CLI: Get Sentinel configuration for watchdog script."""
    workspace_root = resolve_workspace_root(workspace_path)
    state = _load_workspace_sentinel_state(workspace_root)

    with _sentinel_registry_lock():
        registry = _cleanup_sentinel_registry_unlocked(_load_sentinel_registry_unlocked())
        _save_sentinel_registry_unlocked(registry)
        conflicts = _sentinel_conflicts(
            workspace_root,
            registry,
            session_id=state["session_id"],
            tmux_pane=state["tmux_pane"],
        )

    state["conflicts"] = conflicts or state["conflicts"]
    state["ownership_conflict"] = bool(state["ownership_conflict"] or conflicts)
    state["watchdog_allowed"] = not state["ownership_conflict"]
    print(json.dumps(state, indent=2))


def cli_list_projects(
    workspaces_dir: str | None = None,
    *,
    workspace_cls: type[Any],
) -> None:
    """CLI: List all projects."""
    if workspaces_dir is None:
        from .config_helpers import load_effective_config

        ws_dir = load_effective_config().workspaces_dir
    else:
        ws_dir = Path(workspaces_dir)
    if not ws_dir.exists():
        print(json.dumps([]))
        return

    projects = []
    for child in sorted(ws_dir.iterdir()):
        if child.is_dir() and (child / "status.json").exists():
            try:
                ws = workspace_cls.open_existing(ws_dir, child.name)
                meta = ws.get_project_metadata()
                meta["topic"] = ws.read_file("topic.txt") or ""
                projects.append(meta)
            except Exception:
                continue
    print(json.dumps(projects, indent=2))


def cli_dashboard_data(
    workspace_path: str,
    events_tail: int = 50,
) -> None:
    """CLI: Aggregate all monitoring data for frontend dashboard."""
    payload = collect_dashboard_data(workspace_path, events_tail=events_tail)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
