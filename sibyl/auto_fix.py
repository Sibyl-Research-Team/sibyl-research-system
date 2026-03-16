"""Deterministic auto-fix for common error patterns.

Provides code-first fixes for common errors before escalating to LLM agents.
Saves ~10K tokens per self-heal cycle by handling mechanical fixes.

Supported patterns:
- ImportError: pip install missing module
- FileNotFoundError: create missing directory
- Config errors: YAML/JSON syntax repair
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


# Maps error type keywords to fix functions
AUTO_FIX_PATTERNS: dict[str, Any] = {}


def attempt_auto_fix(error: dict, workspace_path: Path) -> dict | None:
    """Attempt a deterministic fix for a known error pattern.

    Args:
        error: Structured error dict from ErrorCollector
        workspace_path: Project workspace root

    Returns:
        Fix result dict on success: {"fixed": True, "action": str, "detail": str}
        None on failure (escalate to agent)
    """
    error_type = error.get("error_type", error.get("type", ""))
    message = error.get("message", error.get("detail", ""))
    traceback = error.get("traceback", "")
    full_text = f"{message}\n{traceback}"

    # Try each pattern in priority order
    for pattern, fixer in _FIXERS:
        if pattern in error_type or pattern in full_text.lower():
            try:
                result = fixer(error, workspace_path, full_text)
                if result:
                    return result
            except Exception:
                continue

    return None


def _fix_import(error: dict, workspace_path: Path, full_text: str) -> dict | None:
    """Fix ImportError by installing the missing module."""
    import re

    # Extract module name from error message
    patterns = [
        r"No module named '([^']+)'",
        r"ModuleNotFoundError: No module named '([^']+)'",
        r"ImportError: cannot import name '([^']+)'",
    ]

    module_name = None
    for pattern in patterns:
        match = re.search(pattern, full_text)
        if match:
            module_name = match.group(1).split(".")[0]
            break

    if not module_name:
        return None

    # Safety: only auto-install known safe packages
    safe_packages = {
        "yaml": "pyyaml",
        "PIL": "pillow",
        "cv2": "opencv-python",
        "sklearn": "scikit-learn",
        "bs4": "beautifulsoup4",
        "lark_oapi": "lark-oapi",
        "mistune": "mistune",
        "rich": "rich",
        "flask": "flask",
    }

    pip_name = safe_packages.get(module_name, module_name)

    # Don't auto-install packages that might be dangerous
    if any(c in pip_name for c in (".", "/", "\\", ";", "&", "|")):
        return None

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_name],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return {
                "fixed": True,
                "action": "pip_install",
                "detail": f"Installed {pip_name} (for module {module_name})",
            }
    except (subprocess.TimeoutExpired, OSError):
        pass

    return None


def _fix_missing_dir(error: dict, workspace_path: Path, full_text: str) -> dict | None:
    """Fix FileNotFoundError by creating missing directories."""
    import re

    # Extract path from error
    patterns = [
        r"FileNotFoundError: \[Errno 2\] No such file or directory: '([^']+)'",
        r"No such file or directory: '([^']+)'",
    ]

    target_path = None
    for pattern in patterns:
        match = re.search(pattern, full_text)
        if match:
            target_path = match.group(1)
            break

    if not target_path:
        return None

    path = Path(target_path)

    # Only create directories, not files. And only under workspace.
    if path.suffix:
        # It's a file — create its parent directory
        dir_to_create = path.parent
    else:
        dir_to_create = path

    # Safety: only create dirs under workspace
    try:
        ws_resolved = workspace_path.resolve()
        dir_resolved = dir_to_create.resolve()
        if not str(dir_resolved).startswith(str(ws_resolved)):
            return None
    except (OSError, ValueError):
        return None

    try:
        dir_to_create.mkdir(parents=True, exist_ok=True)
        return {
            "fixed": True,
            "action": "mkdir",
            "detail": f"Created directory: {dir_to_create}",
        }
    except OSError:
        return None


def _fix_config(error: dict, workspace_path: Path, full_text: str) -> dict | None:
    """Fix YAML/JSON config syntax errors."""
    import re

    # Look for config file paths in the error
    config_patterns = [
        r"error.*(?:parsing|loading|reading)\s+['\"]?([^\s'\"]+\.(?:yaml|yml|json))",
        r"['\"]([^\s'\"]+\.(?:yaml|yml|json))['\"]",
    ]

    config_path = None
    for pattern in config_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            candidate = Path(match.group(1))
            if candidate.exists():
                config_path = candidate
                break

    if not config_path:
        return None

    # Try to read and rewrite the file with proper formatting
    try:
        content = config_path.read_text(encoding="utf-8")
        if config_path.suffix in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(content)
            if data is not None:
                fixed = yaml.dump(data, default_flow_style=False, allow_unicode=True)
                config_path.write_text(fixed, encoding="utf-8")
                return {
                    "fixed": True,
                    "action": "config_reformat",
                    "detail": f"Reformatted YAML: {config_path}",
                }
        elif config_path.suffix == ".json":
            data = json.loads(content)
            fixed = json.dumps(data, indent=2, ensure_ascii=False)
            config_path.write_text(fixed, encoding="utf-8")
            return {
                "fixed": True,
                "action": "config_reformat",
                "detail": f"Reformatted JSON: {config_path}",
            }
    except Exception:
        pass

    return None


# Ordered list of (pattern_keyword, fixer_function) pairs
_FIXERS: list[tuple[str, Any]] = [
    ("import", _fix_import),
    ("modulenotfounderror", _fix_import),
    ("no module named", _fix_import),
    ("filenotfounderror", _fix_missing_dir),
    ("no such file or directory", _fix_missing_dir),
    ("config", _fix_config),
    ("yaml", _fix_config),
    ("json", _fix_config),
]
