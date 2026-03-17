"""Flask Blueprint for WebUI monitoring endpoints."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify

from sibyl._paths import get_system_state_dir
from sibyl.event_logger import EventLogger
from sibyl.webui.conversation_watcher import ConversationWatcher
from sibyl.webui.session_registry import SessionRegistry

logger = logging.getLogger(__name__)

monitor_bp = Blueprint("webui-monitor", __name__, url_prefix="/api/monitor")


def _get_ws_dir() -> Path:
    return Path(current_app.config["SIBYL_WS_DIR"])


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return payload if isinstance(payload, dict) else default


def _read_gpu_leases() -> dict[str, Any]:
    lease_path = get_system_state_dir() / "scheduler" / "gpu_leases.json"
    return _read_json(lease_path, {"leases": {}, "updated_at": None})


def _collect_active_agents(workspaces_dir: Path) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    now = time.time()
    if not workspaces_dir.exists():
        return active

    for project_dir in sorted(workspaces_dir.iterdir()):
        if not project_dir.is_dir() or not (project_dir / "status.json").exists():
            continue
        starts: dict[tuple[str, str, int], dict[str, Any]] = {}
        for event in EventLogger(project_dir).read_all():
            if event.get("event") == "agent_start":
                key = (
                    str(event.get("agent", "")),
                    str(event.get("stage", "")),
                    int(event.get("iteration", 0) or 0),
                )
                starts[key] = event
            elif event.get("event") == "agent_end":
                key = (
                    str(event.get("agent", "")),
                    str(event.get("stage", "")),
                    int(event.get("iteration", 0) or 0),
                )
                starts.pop(key, None)

        for (_agent, _stage, _iteration), event in starts.items():
            started_at = float(event.get("ts", now) or now)
            active.append({
                "project": project_dir.name,
                "agent": event.get("agent", ""),
                "stage": event.get("stage", ""),
                "iteration": int(event.get("iteration", 0) or 0),
                "model_tier": event.get("model_tier", ""),
                "started_at": started_at,
                "duration_sec": max(0.0, now - started_at),
            })

    active.sort(key=lambda item: item["started_at"], reverse=True)
    return active


def _estimate_cost_usd(_model: str, _input_tokens: int, _output_tokens: int) -> float:
    return 0.0


def _collect_cost_timeline(workspaces_dir: Path) -> dict[str, Any]:
    timeline: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "cost_estimate_usd": 0.0}

    registry = SessionRegistry(workspaces_dir)
    for session in registry.list_sessions():
        conversation_path = session.get("conversation_jsonl")
        if not conversation_path:
            continue
        watcher = ConversationWatcher(Path(conversation_path))
        for entry in watcher.tail(10_000):
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message", {}) or {}
            usage = message.get("usage", {}) or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            if input_tokens == 0 and output_tokens == 0:
                continue
            model = str(message.get("model", ""))
            cost_estimate_usd = _estimate_cost_usd(model, input_tokens, output_tokens)
            totals["input_tokens"] += input_tokens
            totals["output_tokens"] += output_tokens
            totals["cost_estimate_usd"] += cost_estimate_usd
            timeline.append({
                "project": session["project"],
                "session_id": session["session_id"],
                "timestamp": entry.get("timestamp"),
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_estimate_usd": cost_estimate_usd,
            })

    timeline.sort(key=lambda item: item.get("timestamp") or "")
    totals["cost_estimate_usd"] = round(totals["cost_estimate_usd"], 6)
    return {"timeline": timeline, "totals": totals}


@monitor_bp.get("/gpu")
def gpu_overview():
    return jsonify(_read_gpu_leases())


@monitor_bp.get("/agents")
def active_agents():
    return jsonify({"agents": _collect_active_agents(_get_ws_dir())})


@monitor_bp.get("/cost")
def cost_overview():
    return jsonify(_collect_cost_timeline(_get_ws_dir()))
