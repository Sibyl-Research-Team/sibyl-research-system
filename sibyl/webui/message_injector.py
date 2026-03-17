"""Send sanitized text into a running Claude Code tmux pane."""

from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_DISALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9 _.,:!?/\-@#%\u4e00-\u9fff\u3000-\u303f]")
_MULTISPACE = re.compile(r"\s+")


def sanitize_for_tmux(message: str) -> str:
    """Remove characters that are unsafe or awkward for tmux send-keys."""
    cleaned = message.replace("\r", " ").replace("\n", " ")
    cleaned = _CONTROL_CHARS.sub("", cleaned)
    cleaned = cleaned.replace("`", "").replace('"', "").replace("'", "")
    cleaned = _DISALLOWED_CHARS.sub("", cleaned)
    cleaned = _MULTISPACE.sub(" ", cleaned)
    return cleaned.strip()


class MessageInjector:
    """Inject text into a tmux pane."""

    def send(self, tmux_pane: str, message: str) -> dict[str, str | bool]:
        clean = sanitize_for_tmux(message)
        if not clean:
            return {"ok": False, "error": "Message empty after sanitization"}
        try:
            result = subprocess.run(
                ["tmux", "send-keys", "-t", tmux_pane, clean, "Enter"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "tmux send-keys timed out"}
        except FileNotFoundError:
            return {"ok": False, "error": "tmux not found"}

        if result.returncode != 0:
            error = result.stderr.strip() or f"tmux exited with {result.returncode}"
            logger.warning("tmux send-keys failed for %s: %s", tmux_pane, error)
            return {"ok": False, "error": error}
        return {"ok": True, "sent": clean}
