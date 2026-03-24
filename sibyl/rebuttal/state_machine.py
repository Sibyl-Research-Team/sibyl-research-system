"""Rebuttal state machine: stage transitions with adversarial loop."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .constants import REBUTTAL_STAGES
from .scoring import get_current_round, load_round_score, set_current_round, should_stop


def get_next_stage(
    orchestrator: Any,
    current_stage: str,
    result: str = "",
    score: float | None = None,
) -> tuple[str, int | None]:
    """Compute next rebuttal stage. Returns (next_stage, new_round_or_None)."""
    ws = Path(orchestrator.workspace_path)
    rc = orchestrator.rebuttal_config

    if current_stage == "score_evaluate":
        round_num = get_current_round(ws)
        round_score = load_round_score(ws, round_num)
        avg = round_score.avg_score if round_score else 0.0

        if should_stop(avg, round_num, rc.score_threshold, rc.max_rounds):
            return ("final_synthesis", None)

        # Prepare next round
        next_round = round_num + 1
        _prepare_next_round(ws, next_round, round_score)
        return ("rebuttal_draft", next_round)

    if current_stage == "codex_review" and not rc.codex_enabled:
        return ("score_evaluate", None)

    # Linear progression for all other stages
    try:
        idx = REBUTTAL_STAGES.index(current_stage)
        next_stage = REBUTTAL_STAGES[idx + 1]
        # Skip codex_review if not enabled
        if next_stage == "codex_review" and not rc.codex_enabled:
            next_stage = "score_evaluate"
        return (next_stage, None)
    except (ValueError, IndexError):
        return ("done", None)


def _prepare_next_round(
    workspace_path: Path,
    next_round: int,
    prev_score: Any | None,
) -> None:
    """Set up directory structure and context for the next adversarial round."""
    round_dir = workspace_path / f"rounds/round_{next_round:03d}"
    for subdir in ("team", "synthesis", "sim_review"):
        (round_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Aggregate previous round feedback: scores + sim_review contents
    prev_round_num = next_round - 1
    prev_round_dir = workspace_path / f"rounds/round_{prev_round_num:03d}"
    feedback: dict = {
        "previous_round": prev_round_num,
        "scores": {},
        "avg_score": 0.0,
        "concerns_remaining": 0,
        "sim_review_dir": f"rounds/round_{prev_round_num:03d}/sim_review",
        "sim_reviews": {},
    }
    if prev_score is not None:
        feedback["scores"] = prev_score.per_reviewer if hasattr(prev_score, "per_reviewer") else {}
        feedback["avg_score"] = prev_score.avg_score if hasattr(prev_score, "avg_score") else 0.0
        feedback["concerns_remaining"] = prev_score.concerns_remaining if hasattr(prev_score, "concerns_remaining") else 0

    # Inline simulated reviewer feedback so agents don't need to chase paths
    sim_review_dir = prev_round_dir / "sim_review"
    if sim_review_dir.exists():
        for f in sorted(sim_review_dir.iterdir()):
            if f.suffix == ".md":
                try:
                    feedback["sim_reviews"][f.stem] = f.read_text(encoding="utf-8")
                except OSError:
                    pass
            elif f.suffix == ".json":
                try:
                    feedback[f"sim_reviews_{f.stem}_json"] = json.loads(
                        f.read_text(encoding="utf-8")
                    )
                except (json.JSONDecodeError, OSError):
                    pass

    (round_dir / "prev_round_feedback.json").write_text(
        json.dumps(feedback, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Atomic symlink replacement
    current_link = workspace_path / "rounds/current"
    tmp_link = workspace_path / f"rounds/.current_{next_round}.tmp"
    if tmp_link.is_symlink() or tmp_link.exists():
        tmp_link.unlink()
    tmp_link.symlink_to(f"round_{next_round:03d}")
    os.replace(tmp_link, current_link)

    # Update round number in rebuttal state
    set_current_round(workspace_path, next_round)
