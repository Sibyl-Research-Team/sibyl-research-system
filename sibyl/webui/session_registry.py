"""Map Sibyl projects to Claude Code sessions and conversation logs."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionRegistry:
    """Discover project-to-session mappings from sentinel session files."""

    def __init__(self, workspaces_dir: Path):
        self.workspaces_dir = Path(workspaces_dir)
        self._claude_home = Path(os.environ.get("HOME", "~")).expanduser() / ".claude"

    def _read_session_file(self, sentinel_path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(sentinel_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _find_conversation_jsonl(self, session_id: str) -> Path | None:
        projects_dir = self._claude_home / "projects"
        if not projects_dir.exists():
            return None
        for candidate in projects_dir.rglob(f"{session_id}.jsonl"):
            if candidate.is_file():
                return candidate
        return None

    def get_session(self, project_name: str) -> dict[str, Any] | None:
        sentinel_path = self.workspaces_dir / project_name / "sentinel_session.json"
        if not sentinel_path.exists():
            return None

        payload = self._read_session_file(sentinel_path)
        if not payload:
            return None

        session_id = payload.get("session_id") or payload.get("claude_session_id")
        if not session_id:
            return None

        result: dict[str, Any] = {
            "project": project_name,
            "session_id": session_id,
            "tmux_pane": payload.get("tmux_pane", ""),
            "conversation_jsonl": None,
        }
        conversation_path = self._find_conversation_jsonl(session_id)
        if conversation_path is not None:
            result["conversation_jsonl"] = str(conversation_path)
        return result

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        if not self.workspaces_dir.exists():
            return sessions
        for child in sorted(self.workspaces_dir.iterdir()):
            if not child.is_dir() or not (child / "status.json").exists():
                continue
            session = self.get_session(child.name)
            if session:
                sessions.append(session)
        return sessions
