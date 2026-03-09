"""Self-healing router for Sibyl system.

Routes structured errors to appropriate repair skills,
manages circuit breakers, and tracks fix state.
"""

import json
import time
from pathlib import Path

from sibyl.error_collector import StructuredError

# Error category → repair skill pipeline
SKILL_ROUTE_TABLE: dict[str, list[str] | None] = {
    "import": ["python-patterns", "tdd-workflow"],
    "test":   ["systematic-debugging", "tdd-workflow"],
    "type":   ["python-patterns", "python-review"],
    "state":  ["systematic-debugging", "verification-loop"],
    "config": ["systematic-debugging"],
    "build":  ["build-error-resolver", "tdd-workflow"],
    "prompt": None,  # direct fix, no skill needed
}

# Priority order (lower index = higher priority)
CATEGORY_PRIORITY = ["import", "build", "type", "test", "state", "config", "prompt"]

CIRCUIT_BREAKER_MAX = 3    # max fix attempts before giving up
MAX_FILES_PER_FIX = 5      # max files a single fix can modify
PROTECTED_FILES = [
    "sibyl/orchestrate.py",
]


def _empty_state() -> dict:
    return {
        "pending": [],
        "in_progress": {},
        "fixed": {},
        "circuit_broken": {},
        "attempts": {},  # error_id -> count
    }


class SelfHealRouter:
    """Routes errors to skills and manages repair state."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                # Ensure all keys exist
                for key in _empty_state():
                    if key not in data:
                        data[key] = _empty_state()[key]
                return data
            except (json.JSONDecodeError, OSError):
                pass
        return _empty_state()

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.state_file)

    def route_to_skills(self, error: StructuredError) -> list[str]:
        """Map an error to a list of repair skills."""
        skills = SKILL_ROUTE_TABLE.get(error.category)
        if skills is None:
            # Fallback for unknown categories or prompt errors
            return ["systematic-debugging"]
        return list(skills)

    def deduplicate(self, errors: list[StructuredError]) -> list[StructuredError]:
        """Remove duplicate errors (same error_id)."""
        seen: set[str] = set()
        result = []
        for err in errors:
            if err.error_id not in seen:
                seen.add(err.error_id)
                result.append(err)
        return result

    def prioritize(self, errors: list[StructuredError]) -> list[StructuredError]:
        """Sort errors by category priority."""
        def _priority(err: StructuredError) -> int:
            try:
                return CATEGORY_PRIORITY.index(err.category)
            except ValueError:
                return len(CATEGORY_PRIORITY)

        return sorted(errors, key=_priority)

    def check_circuit_breaker(self, error_id: str) -> bool:
        """Check if an error has exceeded max fix attempts."""
        if error_id in self._state["circuit_broken"]:
            return True
        attempts = self._state["attempts"].get(error_id, 0)
        return attempts >= CIRCUIT_BREAKER_MAX

    def record_fix_attempt(
        self,
        error_id: str,
        success: bool,
        commit_hash: str | None = None,
    ):
        """Record a fix attempt result."""
        if success:
            self._state["fixed"][error_id] = {
                "fixed_at": time.time(),
                "commit": commit_hash or "",
            }
            # Reset attempts on success
            self._state["attempts"].pop(error_id, None)
            self._state["circuit_broken"].pop(error_id, None)
            self._state["in_progress"].pop(error_id, None)
        else:
            count = self._state["attempts"].get(error_id, 0) + 1
            self._state["attempts"][error_id] = count
            self._state["in_progress"].pop(error_id, None)
            if count >= CIRCUIT_BREAKER_MAX:
                self._state["circuit_broken"][error_id] = {
                    "attempts": count,
                    "last_attempt": time.time(),
                }
        self._save_state()

    def generate_repair_task(self, error: StructuredError) -> dict:
        """Generate a repair task JSON for the self-healer agent."""
        skills = self.route_to_skills(error)
        is_protected = any(
            error.file_path and error.file_path.endswith(pf)
            for pf in PROTECTED_FILES
        ) if error.file_path else False

        return {
            "error_id": error.error_id,
            "error_type": error.error_type,
            "category": error.category,
            "message": error.message,
            "traceback": error.traceback,
            "file_path": error.file_path,
            "line_number": error.line_number,
            "stage": error.stage,
            "project": error.project,
            "skills": skills,
            "protected_file": is_protected,
            "max_files": MAX_FILES_PER_FIX,
            "context": error.context,
        }

    def filter_actionable(self, errors: list[StructuredError]) -> list[StructuredError]:
        """Filter out already-fixed and circuit-broken errors."""
        result = []
        for err in errors:
            if err.error_id in self._state["fixed"]:
                continue
            if self.check_circuit_breaker(err.error_id):
                continue
            result.append(err)
        return result

    def get_status(self) -> dict:
        """Return current self-heal state for status display."""
        return {
            "pending": list(self._state["pending"]),
            "in_progress": dict(self._state["in_progress"]),
            "fixed": dict(self._state["fixed"]),
            "circuit_broken": dict(self._state["circuit_broken"]),
            "attempts": dict(self._state["attempts"]),
        }
