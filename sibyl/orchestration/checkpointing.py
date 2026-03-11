"""Checkpoint lifecycle helpers for orchestration stages."""

from __future__ import annotations

from typing import Any

from .constants import CHECKPOINT_DIRS


def get_or_create_checkpoint(
    orchestrator: Any,
    stage: str,
    steps: dict[str, str],
) -> dict | None:
    """Get a validated checkpoint or create a fresh one for a stage."""
    cp_dir = CHECKPOINT_DIRS.get(stage)
    if cp_dir is None:
        return None

    iteration = orchestrator.ws.get_status().iteration
    valid = orchestrator.ws.validate_checkpoint(cp_dir, current_iteration=iteration)
    if valid is not None:
        return {
            "resuming": True,
            "completed_steps": valid["completed"],
            "remaining_steps": valid["remaining"],
            "all_complete": not valid["remaining"],
            "checkpoint_dir": cp_dir,
        }

    orchestrator.ws.create_checkpoint(stage, cp_dir, steps, iteration=iteration)
    return {
        "resuming": False,
        "completed_steps": [],
        "remaining_steps": list(steps.keys()),
        "all_complete": False,
        "checkpoint_dir": cp_dir,
    }
