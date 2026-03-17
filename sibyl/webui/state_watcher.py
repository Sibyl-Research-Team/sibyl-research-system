"""Workspace state watcher helpers for monitor invalidation events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FILE_CATEGORIES = {
    "status.json": "status_changed",
    "events.jsonl": "event_logged",
    "gpu_progress.json": "experiment_updated",
    "experiment_state.json": "experiment_updated",
    "sentinel_heartbeat.json": "heartbeat_updated",
}


def categorize_change(path_str: str) -> str | None:
    """Return the notification category for a changed file path."""
    return _FILE_CATEGORIES.get(Path(path_str).name)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_state_snapshot(workspace_root: Path) -> dict[str, dict[str, Any]]:
    """Read a lightweight snapshot used for refresh/invalidation messages."""
    root = Path(workspace_root)
    return {
        "status": _read_json(root / "status.json"),
        "gpu_progress": _read_json(root / "exp" / "gpu_progress.json"),
        "experiment_state": _read_json(root / "exp" / "experiment_state.json"),
    }
