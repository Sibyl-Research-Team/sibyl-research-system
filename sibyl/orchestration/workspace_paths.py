"""Workspace path and marker helpers for orchestration code."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def resolve_workspace_root(workspace_path: str | Path) -> Path:
    """Normalize a workspace path to the stable project root."""
    workspace_root = Path(workspace_path)
    if workspace_root.name == "current" and (workspace_root.parent / "status.json").exists():
        workspace_root = workspace_root.parent
    return workspace_root.resolve()


def workspace_scope_id(workspace_path: str | Path) -> str:
    """Return a stable workspace-scoped identifier for cross-process markers."""
    workspace_root = resolve_workspace_root(workspace_path)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", workspace_root.name).strip("-") or "sibyl"
    digest = hashlib.sha1(str(workspace_root).encode("utf-8")).hexdigest()[:10]
    return f"{safe_name}_{digest}"


def project_marker_file(workspace_path: str | Path, suffix: str) -> str:
    """Build a per-workspace marker file path under /tmp."""
    safe_suffix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", suffix).strip("-") or "marker"
    return f"/tmp/sibyl_{workspace_scope_id(workspace_path)}_{safe_suffix}.json"


def load_workspace_iteration_dirs(workspace_path: str | Path, default: bool = False) -> bool:
    """Read iteration_dirs from workspace status when available."""
    status_path = resolve_workspace_root(workspace_path) / "status.json"
    if not status_path.exists():
        return default
    try:
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        return bool(status_data.get("iteration_dirs", default))
    except (json.JSONDecodeError, OSError, TypeError):
        return default


def resolve_active_workspace_path(workspace_path: str | Path) -> Path:
    """Normalize a workspace path to the active iteration workspace."""
    workspace_root = resolve_workspace_root(workspace_path)
    if load_workspace_iteration_dirs(workspace_root):
        current_path = workspace_root / "current"
        if current_path.exists():
            return current_path
    return workspace_root
