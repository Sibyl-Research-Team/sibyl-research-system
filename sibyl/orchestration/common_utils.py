"""Shared shell, naming, and language helpers for orchestration."""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

from sibyl._paths import REPO_ROOT

from .workspace_paths import project_marker_file, resolve_workspace_root


def pack_skill_args(*parts: object) -> str:
    """Pack positional skill args using shell-safe quoting."""
    return " ".join(
        shlex.quote(str(part))
        for part in parts
        if part is not None and str(part) != ""
    )


def language_label(language: str) -> str:
    """Return a human-readable language label for prompts."""
    return "Chinese" if language == "zh" else "English"


def non_paper_output_requirement(language: str) -> str:
    """Prompt snippet for non-paper artifacts that follow config.language."""
    return f"All non-paper output must be written in {language_label(language)}."


def paper_writing_requirement() -> str:
    """Prompt snippet for paper-related drafts, which are always English."""
    return (
        "All paper outlines, section drafts, critiques, integrated paper text, "
        "and writing reviews must be written in English."
    )


def slugify_project_name(text: str) -> str:
    """Normalize free-form text into a stable workspace slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:60]


def build_repo_python_cli_command(*args: str | Path) -> str:
    """Build a shell-safe repo-local `python -m sibyl.cli ...` command."""
    cmd = shlex.join([sys.executable, "-m", "sibyl.cli", *(str(arg) for arg in args)])
    return f"cd {shlex.quote(str(REPO_ROOT))} && {cmd}"


def self_heal_status_file(workspace_path: str | Path) -> str:
    """Return the project-scoped self-heal monitor status file under /tmp."""
    workspace_root = resolve_workspace_root(workspace_path)
    return project_marker_file(workspace_root, "self_heal_monitor")
