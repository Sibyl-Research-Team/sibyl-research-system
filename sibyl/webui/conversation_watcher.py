"""Incremental reader for Claude Code conversation JSONL files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DISPLAYABLE_TYPES = {"assistant", "user", "system", "result"}


class ConversationWatcher:
    """Read new displayable JSONL entries from a Claude conversation file."""

    def __init__(self, jsonl_path: Path):
        self.path = Path(jsonl_path)
        self._offset = 0
        self._mtime_ns = 0
        self._inode: int | None = None

    def _iter_displayable_entries(self, text: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Skipping corrupt Claude JSONL line in %s", self.path)
                continue
            if payload.get("type") in DISPLAYABLE_TYPES:
                entries.append(payload)
        return entries

    def seek_to_end(self) -> None:
        """Prime the watcher to start from the current EOF position."""
        if not self.path.exists():
            self._offset = 0
            self._mtime_ns = 0
            self._inode = None
            return
        try:
            stat = self.path.stat()
        except OSError:
            return
        self._offset = stat.st_size
        self._mtime_ns = stat.st_mtime_ns
        self._inode = getattr(stat, "st_ino", None)

    def read_new_entries(self) -> list[dict[str, Any]]:
        """Read entries appended since the previous call."""
        if not self.path.exists():
            return []
        try:
            stat = self.path.stat()
            current_size = stat.st_size
            current_mtime_ns = stat.st_mtime_ns
            current_inode = getattr(stat, "st_ino", None)
        except OSError:
            return []
        file_replaced = self._inode is not None and current_inode != self._inode
        file_rewritten = self._mtime_ns and current_mtime_ns != self._mtime_ns
        if current_size < self._offset or (
            current_size <= self._offset and (file_replaced or file_rewritten)
        ):
            self._offset = 0

        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                handle.seek(self._offset)
                new_data = handle.read()
                self._offset = handle.tell()
                self._mtime_ns = current_mtime_ns
                self._inode = current_inode
        except OSError:
            return []

        if not new_data:
            return []
        return self._iter_displayable_entries(new_data)

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        """Return the last N displayable entries and move the offset to EOF."""
        if not self.path.exists():
            return []
        try:
            content = self.path.read_text(encoding="utf-8")
            stat = self.path.stat()
            self._offset = stat.st_size
            self._mtime_ns = stat.st_mtime_ns
            self._inode = getattr(stat, "st_ino", None)
        except OSError:
            return []
        entries = self._iter_displayable_entries(content)
        return entries[-n:]
