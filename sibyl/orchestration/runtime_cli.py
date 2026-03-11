"""Runtime-oriented CLI helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sibyl.event_logger import EventLogger

from .config_helpers import load_effective_config
from .workspace_paths import (
    project_marker_file,
    resolve_active_workspace_path,
    resolve_workspace_root,
)


_EXPERIMENT_SUPERVISOR_STATE = "exp/experiment_supervisor_state.json"
_EXPERIMENT_MAIN_WAKE_QUEUE = "exp/experiment_supervisor_main_wake.jsonl"
_EXPERIMENT_MAIN_WAKE_HISTORY = "exp/experiment_supervisor_main_wake_history.jsonl"


def _experiment_supervisor_state_path(workspace_path: str | Path) -> Path:
    active_root = resolve_active_workspace_path(workspace_path)
    return active_root / _EXPERIMENT_SUPERVISOR_STATE


def _experiment_main_wake_queue_path(workspace_path: str | Path) -> Path:
    active_root = resolve_active_workspace_path(workspace_path)
    return active_root / _EXPERIMENT_MAIN_WAKE_QUEUE


def _experiment_main_wake_history_path(workspace_path: str | Path) -> Path:
    active_root = resolve_active_workspace_path(workspace_path)
    return active_root / _EXPERIMENT_MAIN_WAKE_HISTORY


@contextmanager
def _queue_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _parse_iso_datetime(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_json_list(raw: str, fallback_label: str = "") -> list:
    try:
        value = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        value = [fallback_label or raw] if raw else []
    if not isinstance(value, list):
        value = [value]
    return value


def _parse_json_dict(raw: str) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {"raw": raw} if raw else {}
    return value if isinstance(value, dict) else {"value": value}


def _pending_main_wake_count(workspace_path: str | Path) -> int:
    queue_path = _experiment_main_wake_queue_path(workspace_path)
    if not queue_path.exists():
        return 0
    try:
        return sum(1 for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _append_main_wake_event(workspace_path: str | Path, payload: dict) -> None:
    queue_path = _experiment_main_wake_queue_path(workspace_path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _queue_lock(queue_path):
        with open(queue_path, "a", encoding="utf-8") as f:
            f.write(line)


def _drain_main_wake_events(workspace_path: str | Path) -> list[dict]:
    queue_path = _experiment_main_wake_queue_path(workspace_path)
    history_path = _experiment_main_wake_history_path(workspace_path)
    with _queue_lock(queue_path):
        if not queue_path.exists():
            return []
        try:
            raw = queue_path.read_text(encoding="utf-8")
        except OSError:
            return []
        if not raw.strip():
            return []
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(history_path, "a", encoding="utf-8") as history_file:
            history_file.write(raw)
        queue_path.write_text("", encoding="utf-8")

    events: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _build_experiment_status_payload(workspace_path: str) -> dict:
    """Compute a rich experiment status snapshot for UI and supervisors."""
    from sibyl.experiment_recovery import load_experiment_state
    from sibyl.gpu_scheduler import _load_progress, read_monitor_result, read_poll_result

    if not workspace_path:
        return {
            "status": "workspace_required",
            "error": "workspace_path is required for multi-project isolated experiment status",
        }

    project_root = resolve_workspace_root(workspace_path)
    active_root = resolve_active_workspace_path(workspace_path)
    monitor_path = Path(project_marker_file(project_root, "exp_monitor"))
    gpu_poll_path = Path(project_marker_file(project_root, "gpu_free"))

    monitor = read_monitor_result(str(monitor_path))
    result = dict(monitor) if monitor else {"status": "no_monitor"}
    completed, running_ids, running_map, timings = _load_progress(active_root)
    _ = timings

    task_plan_path = active_root / "plan" / "task_plan.json"
    total_tasks = 0
    task_names: dict[str, str] = {}
    task_estimates: dict[str, int] = {}
    if task_plan_path.exists():
        try:
            plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
            for task in plan.get("tasks", []):
                total_tasks += 1
                task_names[task["id"]] = task.get("name", task["id"])
                task_estimates[task["id"]] = task.get("estimated_minutes", 0)
        except (json.JSONDecodeError, OSError):
            pass

    pending_count = max(0, total_tasks - len(completed) - len(running_ids))
    elapsed_sec = int(result.get("elapsed_sec", 0) or 0)
    elapsed_min = elapsed_sec // 60 if elapsed_sec else 0

    exp_state = load_experiment_state(active_root)
    monitor_progress = result.get("progress") if isinstance(result.get("progress"), dict) else {}
    task_progress = dict(monitor_progress)
    for task_id, task in exp_state.tasks.items():
        if task.get("progress"):
            task_progress[task_id] = task["progress"]

    max_remaining_sec = 0
    task_lines: list[str] = []
    running_tasks_detail: list[dict] = []
    for task_id, info in running_map.items():
        gpu_ids = info.get("gpu_ids", [])
        name = task_names.get(task_id, task_id)
        started_at = info.get("started_at", "")
        task_elapsed_min = 0
        start_dt = _parse_iso_datetime(started_at)
        if start_dt is not None:
            task_elapsed_min = int((dt.datetime.now() - start_dt).total_seconds() / 60)
        estimate = task_estimates.get(task_id, 0)
        remaining_sec = 0
        if estimate > 0:
            remaining_sec = max(0, estimate * 60 - task_elapsed_min * 60)
            max_remaining_sec = max(max_remaining_sec, remaining_sec)

        progress = task_progress.get(task_id, {}) if isinstance(task_progress.get(task_id), dict) else {}
        progress_updated_at = progress.get("updated_at", "")
        progress_dt = _parse_iso_datetime(progress_updated_at)
        progress_age_sec = (
            int((dt.datetime.now() - progress_dt).total_seconds())
            if progress_dt is not None
            else None
        )

        gpu_str = ",".join(str(gpu_id) for gpu_id in gpu_ids) if gpu_ids else "?"
        age_suffix = ""
        if progress_age_sec is not None:
            age_suffix = f", progress {max(0, progress_age_sec // 60)}min ago"
        task_lines.append(f"    {name} -> GPU[{gpu_str}] ({task_elapsed_min}min{age_suffix})")
        running_tasks_detail.append({
            "task_id": task_id,
            "name": name,
            "gpu_ids": gpu_ids,
            "elapsed_min": task_elapsed_min,
            "estimate_min": estimate,
            "remaining_min": remaining_sec // 60 if remaining_sec else 0,
            "progress": progress,
            "progress_age_sec": progress_age_sec,
            "started_at": started_at,
        })

    est_remaining_min = int(max_remaining_sec / 60)

    if exp_state.last_recovery_at:
        result["last_recovery_at"] = exp_state.last_recovery_at

    lines = [
        "",
        "+-----------------------------------------+",
        "|      SIBYL - Experiment Monitor          |",
        "+-----------------------------------------+",
    ]

    if total_tasks > 0:
        done_pct = len(completed) / total_tasks
        bar_w = 20
        filled = int(bar_w * done_pct)
        bar = "#" * filled + "." * (bar_w - filled)
        pct_str = f"{int(done_pct * 100)}%"
        lines.append(f"|  [{bar}] {len(completed)}/{total_tasks} ({pct_str})")

    status_label = {
        "all_complete": "ALL DONE",
        "monitoring": "RUNNING",
        "timeout": "TIMEOUT",
        "no_monitor": "INITIALIZING",
    }.get(result["status"], result["status"])
    lines.append(f"|  Status: {status_label}")

    if task_lines:
        lines.append("|  Running:")
        for task_line in task_lines:
            lines.append(f"|  {task_line}")

    if pending_count > 0:
        lines.append(f"|  Queued: {pending_count} tasks waiting")

    free_gpus = read_poll_result(str(gpu_poll_path)) or []
    if free_gpus:
        lines.append(f"|  Free GPUs: {free_gpus}")

    time_parts = []
    if elapsed_min > 0:
        time_parts.append(f"elapsed {elapsed_min}min")
    if est_remaining_min > 0:
        time_parts.append(f"~{est_remaining_min}min remaining")
    if time_parts:
        lines.append(f"|  Time: {', '.join(time_parts)}")

    lines.append("|")
    lines.append("|  System running, please wait...")
    lines.append("+-----------------------------------------+")
    lines.append("")

    monitor_age_sec = None
    if monitor_path.exists():
        monitor_age_sec = int(max(0, time.time() - monitor_path.stat().st_mtime))
    gpu_poll_age_sec = None
    if gpu_poll_path.exists():
        gpu_poll_age_sec = int(max(0, time.time() - gpu_poll_path.stat().st_mtime))

    result["display"] = "\n".join(lines)
    result["completed_count"] = len(completed)
    result["running_count"] = len(running_ids)
    result["pending_count"] = pending_count
    result["total_tasks"] = total_tasks
    result["elapsed_min"] = elapsed_min
    result["estimated_remaining_min"] = est_remaining_min
    result["task_progress"] = task_progress
    result["running_tasks"] = running_tasks_detail
    result["completed_tasks"] = sorted(completed)
    result["free_gpus"] = free_gpus
    result["monitor_age_sec"] = monitor_age_sec
    result["gpu_poll_age_sec"] = gpu_poll_age_sec
    result["workspace_path"] = str(project_root)
    result["active_workspace_path"] = str(active_root)
    return result


def cli_experiment_status(workspace_path: str = "") -> dict[str, Any]:
    """Check experiment status with rich progress information."""
    result = _build_experiment_status_payload(workspace_path)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    try:
        if workspace_path:
            active_root = resolve_active_workspace_path(workspace_path)
            monitor_persist = {key: value for key, value in result.items() if key != "display"}
            monitor_persist["snapshot_at"] = time.time()
            persist_path = active_root / "exp" / "monitor_status.json"
            persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = persist_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(monitor_persist, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(persist_path)
    except Exception:
        pass
    return result


def cli_experiment_supervisor_claim(
    workspace_path: str,
    owner_id: str,
    stale_after_sec: int = 900,
) -> None:
    """Claim the project-scoped experiment supervisor lease."""
    now = time.time()
    state_path = _experiment_supervisor_state_path(workspace_path)
    current = _load_json(state_path)
    active_owner = str(current.get("owner_id", "")).strip()
    last_heartbeat_at = float(current.get("last_heartbeat_at", 0) or 0)
    is_fresh = bool(active_owner) and (now - last_heartbeat_at) < stale_after_sec
    already_owner = active_owner == owner_id
    can_claim = already_owner or not is_fresh

    if can_claim:
        payload = {
            "owner_id": owner_id,
            "status": "running",
            "started_at": current.get("started_at", now) if already_owner else now,
            "last_heartbeat_at": now,
            "workspace_path": str(resolve_workspace_root(workspace_path)),
            "active_workspace_path": str(resolve_active_workspace_path(workspace_path)),
            "last_summary": current.get("last_summary", ""),
            "last_actions": list(current.get("last_actions", [])),
            "last_recommendations": list(current.get("last_recommendations", [])),
        }
        _write_json_atomic(state_path, payload)
    else:
        payload = current

    print(json.dumps({
        "should_start": can_claim,
        "already_owner": already_owner,
        "active_owner": active_owner,
        "stale_after_sec": stale_after_sec,
        "state_path": str(state_path),
        "last_heartbeat_at": last_heartbeat_at,
    }, indent=2, ensure_ascii=False))


def cli_experiment_supervisor_heartbeat(
    workspace_path: str,
    owner_id: str,
    summary: str = "",
    actions_json: str = "[]",
    recommendations_json: str = "[]",
) -> None:
    """Update the experiment supervisor heartbeat and latest advice."""
    state_path = _experiment_supervisor_state_path(workspace_path)
    current = _load_json(state_path)
    current_owner = str(current.get("owner_id", "")).strip()
    if current_owner and current_owner != owner_id:
        print(json.dumps({
            "status": "not_owner",
            "owner_id": current_owner,
            "state_path": str(state_path),
        }, indent=2, ensure_ascii=False))
        return

    actions = _parse_json_list(actions_json, fallback_label="action")
    recommendations = _parse_json_list(recommendations_json, fallback_label="recommendation")

    payload = {
        "owner_id": owner_id,
        "status": "running",
        "started_at": current.get("started_at", time.time()),
        "last_heartbeat_at": time.time(),
        "workspace_path": str(resolve_workspace_root(workspace_path)),
        "active_workspace_path": str(resolve_active_workspace_path(workspace_path)),
        "last_summary": summary,
        "last_actions": actions,
        "last_recommendations": recommendations,
    }
    _write_json_atomic(state_path, payload)
    print(json.dumps({
        "status": "ok",
        "state_path": str(state_path),
        "owner_id": owner_id,
    }, indent=2, ensure_ascii=False))


def cli_experiment_supervisor_notify_main(
    workspace_path: str,
    owner_id: str,
    kind: str = "resolution",
    summary: str = "",
    *,
    details_json: str = "{}",
    actions_json: str = "[]",
    recommendations_json: str = "[]",
    urgency: str = "high",
    requires_main_system: bool = False,
) -> None:
    """Queue a structured wake-up request for the main control-plane session."""
    state_path = _experiment_supervisor_state_path(workspace_path)
    current = _load_json(state_path)
    current_owner = str(current.get("owner_id", "")).strip()
    if current_owner and current_owner != owner_id:
        print(json.dumps({
            "status": "not_owner",
            "owner_id": current_owner,
            "state_path": str(state_path),
        }, indent=2, ensure_ascii=False))
        return

    details = _parse_json_dict(details_json)
    actions = _parse_json_list(actions_json, fallback_label="action")
    recommendations = _parse_json_list(recommendations_json, fallback_label="recommendation")
    requires_main = bool(requires_main_system or kind in {"needs_main_system", "blocked", "escalation"})
    now = time.time()
    event_id = f"wake-{int(now * 1000)}-{owner_id or 'supervisor'}"
    payload = {
        "event_id": event_id,
        "owner_id": owner_id,
        "kind": kind,
        "summary": summary,
        "details": details,
        "actions": actions,
        "recommendations": recommendations,
        "urgency": urgency,
        "requires_main_system": requires_main,
        "created_at": now,
        "created_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
        "workspace_path": str(resolve_workspace_root(workspace_path)),
        "active_workspace_path": str(resolve_active_workspace_path(workspace_path)),
    }
    _append_main_wake_event(workspace_path, payload)

    try:
        EventLogger(Path(resolve_workspace_root(workspace_path))).log(
            "main_wake_request",
            stage=_load_json(resolve_workspace_root(workspace_path) / "status.json").get("stage", ""),
            owner_id=owner_id,
            kind=kind,
            urgency=urgency,
            requires_main_system=requires_main,
            summary=summary,
        )
    except Exception:
        pass

    print(json.dumps({
        "status": "queued",
        "wake_requested": True,
        "event_id": event_id,
        "kind": kind,
        "urgency": urgency,
        "requires_main_system": requires_main,
        "queue_depth": _pending_main_wake_count(workspace_path),
        "queue_path": str(_experiment_main_wake_queue_path(workspace_path)),
    }, indent=2, ensure_ascii=False))


def cli_experiment_supervisor_release(
    workspace_path: str,
    owner_id: str,
    final_status: str = "idle",
    summary: str = "",
) -> None:
    """Release the experiment supervisor lease."""
    state_path = _experiment_supervisor_state_path(workspace_path)
    current = _load_json(state_path)
    current_owner = str(current.get("owner_id", "")).strip()
    if current_owner and current_owner != owner_id:
        print(json.dumps({
            "status": "not_owner",
            "owner_id": current_owner,
            "state_path": str(state_path),
        }, indent=2, ensure_ascii=False))
        return

    payload = {
        "owner_id": "",
        "status": final_status,
        "started_at": current.get("started_at", 0),
        "last_heartbeat_at": time.time(),
        "workspace_path": str(resolve_workspace_root(workspace_path)),
        "active_workspace_path": str(resolve_active_workspace_path(workspace_path)),
        "last_summary": summary or current.get("last_summary", ""),
        "last_actions": list(current.get("last_actions", [])),
        "last_recommendations": list(current.get("last_recommendations", [])),
    }
    _write_json_atomic(state_path, payload)
    print(json.dumps({
        "status": "released",
        "final_status": final_status,
        "state_path": str(state_path),
    }, indent=2, ensure_ascii=False))


def cli_experiment_supervisor_drain_wake(workspace_path: str) -> None:
    """Drain and return any pending wake-up events from the experiment supervisor."""
    events = _drain_main_wake_events(workspace_path)
    requires_attention = any(
        bool(event.get("requires_main_system"))
        or str(event.get("urgency", "")).lower() in {"high", "critical"}
        or str(event.get("kind", "")).lower() in {"needs_main_system", "blocked", "escalation"}
        for event in events
    )
    try:
        if events:
            EventLogger(Path(resolve_workspace_root(workspace_path))).log(
                "main_wake_drain",
                stage=_load_json(resolve_workspace_root(workspace_path) / "status.json").get("stage", ""),
                event_count=len(events),
                requires_main_system=requires_attention,
            )
    except Exception:
        pass
    print(json.dumps({
        "wake_requested": bool(events),
        "requires_main_system": requires_attention,
        "event_count": len(events),
        "events": events,
    }, indent=2, ensure_ascii=False))


def cli_experiment_supervisor_snapshot(workspace_path: str) -> None:
    """Return a structured snapshot for the background experiment supervisor."""
    status = _build_experiment_status_payload(workspace_path)
    state_path = _experiment_supervisor_state_path(workspace_path)
    supervisor_state = _load_json(state_path)
    config = load_effective_config(workspace_path=workspace_path)
    workspace_status = _load_json(resolve_workspace_root(workspace_path) / "status.json")

    overrun_tasks: list[dict] = []
    stale_progress_tasks: list[dict] = []
    runtime_slack_ratio = 1.5
    monitor_poll_sec = 300
    if isinstance(status.get("poll_interval_sec"), int):
        monitor_poll_sec = int(status["poll_interval_sec"])
    progress_stale_sec = max(900, monitor_poll_sec * 3)

    for task in status.get("running_tasks", []):
        estimate_min = int(task.get("estimate_min", 0) or 0)
        elapsed_min = int(task.get("elapsed_min", 0) or 0)
        if estimate_min > 0 and elapsed_min > int(estimate_min * runtime_slack_ratio):
            overrun_tasks.append({
                "task_id": task.get("task_id", ""),
                "elapsed_min": elapsed_min,
                "estimate_min": estimate_min,
                "runtime_ratio": round(elapsed_min / estimate_min, 2),
            })
        progress_age_sec = task.get("progress_age_sec")
        if progress_age_sec is not None and progress_age_sec > progress_stale_sec:
            stale_progress_tasks.append({
                "task_id": task.get("task_id", ""),
                "progress_age_sec": progress_age_sec,
                "elapsed_min": elapsed_min,
                "estimate_min": estimate_min,
            })

    payload = {
        "workspace_path": str(resolve_workspace_root(workspace_path)),
        "active_workspace_path": str(resolve_active_workspace_path(workspace_path)),
        "stage": workspace_status.get("stage", ""),
        "supervisor_state": supervisor_state,
        "main_wake_queue_depth": _pending_main_wake_count(workspace_path),
        "experiment_status": status,
        "drift": {
            "runtime_slack_ratio": runtime_slack_ratio,
            "progress_stale_sec": progress_stale_sec,
            "overrun_tasks": overrun_tasks,
            "stale_progress_tasks": stale_progress_tasks,
            "pending_main_wake": _pending_main_wake_count(workspace_path) > 0,
            "needs_gpu_refresh": status.get("gpu_poll_age_sec") is None or int(status.get("gpu_poll_age_sec") or 0) > max(config.gpu_poll_interval_sec, 180),
            "can_dispatch_now": bool(status.get("pending_count", 0) and status.get("free_gpus")),
        },
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cli_record_gpu_poll(
    workspace_path: str,
    nvidia_smi_output: str,
    source: str = "experiment_supervisor",
) -> dict[str, Any]:
    """Parse and persist a fresh GPU availability snapshot."""
    from sibyl.gpu_scheduler import parse_free_gpus, parse_gpu_snapshot, write_poll_result

    workspace_root = resolve_workspace_root(workspace_path)
    config = load_effective_config(workspace_path=workspace_path)
    marker_file = project_marker_file(workspace_root, "gpu_free")
    snapshot = parse_gpu_snapshot(nvidia_smi_output)
    free_gpus = parse_free_gpus(
        nvidia_smi_output,
        threshold_mb=config.gpu_free_threshold_mb,
        max_gpus=config.max_gpus,
        aggressive_mode=config.gpu_aggressive_mode,
        aggressive_threshold_pct=config.gpu_aggressive_threshold_pct,
    )
    existing = _load_json(Path(marker_file))
    poll_count = int(existing.get("poll_count", 0) or 0) + 1
    payload = write_poll_result(
        marker_file,
        free_gpus=free_gpus,
        poll_count=poll_count,
        snapshot=snapshot,
        source=source,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def cli_requeue_experiment_task(
    workspace_path: str,
    task_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """Clear a task's running lease so the scheduler can retry it."""
    from sibyl.experiment_recovery import mark_task_for_retry

    active_root = resolve_active_workspace_path(workspace_path)
    task = mark_task_for_retry(active_root, task_id, reason=reason)
    payload = {
        "status": "ok",
        "task_id": task_id,
        "reason": reason,
        "task": task,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def cli_dispatch_tasks(
    workspace_path: str,
    *,
    orchestrator_factory: Callable[[str], Any],
    skill_builder: Callable[[Any, str, str, list[int], str], dict],
) -> dict[str, Any]:
    """Dynamic dispatch: find free GPUs and return next task assignments."""
    from sibyl.experiment_recovery import register_dispatched_tasks
    from sibyl.gpu_scheduler import claim_next_batch, get_running_gpu_ids, read_poll_result

    orchestrator = orchestrator_factory(workspace_path)
    status = orchestrator.ws.get_status()
    stage = status.stage
    if stage not in ("pilot_experiments", "experiment_cycle"):
        payload = {"dispatch": [], "reason": "not_experiment_stage"}
        print(json.dumps(payload))
        return payload

    mode = "PILOT" if stage == "pilot_experiments" else "FULL"
    active_root = orchestrator.ws.active_root
    active_workspace = str(active_root)

    if orchestrator.config.gpu_poll_enabled:
        polled = read_poll_result(project_marker_file(orchestrator.ws.root, "gpu_free"))
        if not polled:
            payload = {"dispatch": [], "reason": "awaiting_gpu_poll"}
            print(json.dumps(payload))
            return payload
        all_gpu_ids = polled[:orchestrator.config.max_gpus]
    else:
        all_gpu_ids = list(range(orchestrator.config.max_gpus))

    occupied = set(get_running_gpu_ids(active_root))
    free_gpus = [gpu_id for gpu_id in all_gpu_ids if gpu_id not in occupied]
    if not free_gpus:
        payload = {"dispatch": [], "reason": "no_free_gpus"}
        print(json.dumps(payload))
        return payload

    info = claim_next_batch(
        active_root,
        free_gpus,
        mode,
        gpus_per_task=orchestrator.config.gpus_per_task,
        max_parallel_tasks=orchestrator.config.max_parallel_tasks,
    )
    if info is None:
        payload = {"dispatch": [], "reason": "all_done"}
        print(json.dumps(payload))
        return payload

    batch = info["batch"]
    if not batch:
        payload = {"dispatch": [], "reason": "no_ready_tasks"}
        print(json.dumps(payload))
        return payload

    task_gpu_map = {}
    for assignment in batch:
        for task_id in assignment["task_ids"]:
            task_gpu_map[task_id] = assignment["gpu_ids"]
    remote_project_dir = f"{orchestrator.config.remote_base}/projects/{orchestrator.ws.name}"
    register_dispatched_tasks(active_root, task_gpu_map, remote_project_dir)

    skills = []
    for assignment in batch:
        task_ids = ",".join(assignment["task_ids"])
        gpu_ids = assignment["gpu_ids"]
        skills.append(skill_builder(orchestrator, mode, active_workspace, gpu_ids, task_ids))

    gpu_summary = ", ".join(
        f"{assignment['task_ids'][0]}→GPU{assignment['gpu_ids']}"
        for assignment in batch
    )
    payload = {
        "dispatch": batch,
        "skills": skills,
        "description": f"动态调度: {gpu_summary}",
        "estimated_minutes": info["estimated_minutes"],
    }
    print(json.dumps(payload, indent=2))

    try:
        all_task_ids = [task_id for assignment in batch for task_id in assignment["task_ids"]]
        all_gpu_ids_used = [gpu_id for assignment in batch for gpu_id in assignment["gpu_ids"]]
        EventLogger(Path(workspace_path)).task_dispatch(
            task_ids=all_task_ids,
            gpu_ids=all_gpu_ids_used,
            iteration=status.iteration,
        )
    except Exception:
        pass
    return payload


def cli_recover_experiments(
    workspace_path: str,
    *,
    orchestrator_factory: Callable[[str], Any],
) -> None:
    """Detect and prepare recovery for interrupted experiments."""
    from sibyl.experiment_recovery import (
        generate_detection_script,
        get_running_tasks,
        load_experiment_state,
        migrate_from_gpu_progress,
        save_experiment_state,
    )

    active_root = resolve_active_workspace_path(workspace_path)
    state = load_experiment_state(active_root)
    if not state.tasks:
        state = migrate_from_gpu_progress(active_root)
        if state.tasks:
            save_experiment_state(active_root, state)

    running = get_running_tasks(state)
    if not running:
        print(json.dumps({
            "status": "no_recovery_needed",
            "total_tasks": len(state.tasks),
        }, indent=2))
        return

    orchestrator = orchestrator_factory(workspace_path)
    remote_project_dir = f"{orchestrator.config.remote_base}/projects/{orchestrator.ws.name}"
    script = generate_detection_script(remote_project_dir, running)
    print(json.dumps({
        "status": "has_running_tasks",
        "running_tasks": running,
        "detection_script": script,
        "ssh_server": orchestrator.config.ssh_server,
        "instructions": (
            "Run the detection_script on the remote server via SSH, "
            "then pass the output to cli_apply_recovery."
        ),
    }, indent=2))


def cli_apply_recovery(workspace_path: str, ssh_output: str) -> None:
    """Apply recovery based on SSH detection output."""
    from sibyl.experiment_recovery import (
        load_experiment_state,
        parse_detection_output,
        recover_from_detection,
        save_experiment_state,
        sync_to_gpu_progress,
    )

    active_root = resolve_active_workspace_path(workspace_path)
    state = load_experiment_state(active_root)
    detection = parse_detection_output(ssh_output)
    result = recover_from_detection(state, detection)

    save_experiment_state(active_root, state)
    sync_to_gpu_progress(active_root, state)

    output = asdict(result)
    output["status"] = "recovered"
    print(json.dumps(output, indent=2))
