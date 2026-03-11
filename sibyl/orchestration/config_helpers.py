"""Config loading and persistence helpers for orchestration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from sibyl._paths import REPO_ROOT
from sibyl.config import Config

from .workspace_paths import resolve_workspace_root


def _find_root_config_path(workspace_root: Path | None = None) -> Path | None:
    """Locate the system/root config without depending on the caller's cwd alone."""
    search_roots: list[Path] = []
    if workspace_root is not None:
        search_roots.extend([workspace_root.parent, *workspace_root.parent.parents])
    search_roots.extend([Path.cwd().resolve(), *Path.cwd().resolve().parents])
    search_roots.append(REPO_ROOT.resolve())

    seen: set[Path] = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        candidate = root / "config.yaml"
        if candidate.exists():
            return candidate
    return None


def load_effective_config(
    workspace_path: str | Path | None = None,
    config_path: str | None = None,
) -> Config:
    """Load effective config with explicit path > project config > root config."""
    if config_path:
        return Config.from_yaml(config_path)

    workspace_root = resolve_workspace_root(workspace_path) if workspace_path else None
    project_config = workspace_root / "config.yaml" if workspace_root else None
    root_config = _find_root_config_path(workspace_root)

    if root_config and project_config and project_config.exists():
        return Config.from_yaml_chain(str(root_config), str(project_config))
    if project_config and project_config.exists():
        return Config.from_yaml(str(project_config))
    if root_config:
        return Config.from_yaml(str(root_config))
    return Config()


def write_project_config(ws: Any, config: Config) -> None:
    """Persist a stable project config snapshot scoped to the workspace parent."""
    project_cfg = deepcopy(config)
    project_cfg.workspaces_dir = Path(ws.root).resolve().parent
    ws.write_file("config.yaml", project_cfg.to_commented_yaml())
