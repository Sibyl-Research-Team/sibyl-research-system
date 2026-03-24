"""Rebuttal scoring: round evaluation, trajectory tracking, stop conditions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class RoundScore:
    round_num: int
    per_reviewer: dict[str, float] = field(default_factory=dict)
    avg_score: float = 0.0
    concerns_addressed: int = 0
    concerns_remaining: int = 0
    new_concerns_raised: int = 0
    delta_from_previous: float = 0.0


def load_round_score(workspace_path: str | Path, round_num: int) -> RoundScore | None:
    """Load scores.json for a given round."""
    workspace_path = Path(workspace_path)
    # Check both the numbered dir and the current symlink
    scores_file = workspace_path / f"rounds/round_{round_num:03d}/scores.json"
    if not scores_file.exists():
        # Fallback: check rounds/current/ (agents write to current symlink)
        current_scores = workspace_path / "rounds/current/scores.json"
        if current_scores.exists():
            scores_file = current_scores
        else:
            return None
    try:
        data = json.loads(scores_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return RoundScore(
        round_num=round_num,
        per_reviewer=data.get("per_reviewer", {}),
        avg_score=data.get("avg_score", 0.0),
        concerns_addressed=data.get("concerns_addressed", 0),
        concerns_remaining=data.get("concerns_remaining", 0),
        new_concerns_raised=data.get("new_concerns_raised", 0),
        delta_from_previous=data.get("delta_from_previous", 0.0),
    )


def save_round_score(workspace_path: Path, score: RoundScore) -> None:
    """Persist round scores."""
    scores_dir = workspace_path / f"rounds/round_{score.round_num:03d}"
    scores_dir.mkdir(parents=True, exist_ok=True)
    scores_file = scores_dir / "scores.json"
    scores_file.write_text(
        json.dumps(asdict(score), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_score_trajectory(workspace_path: Path) -> list[dict]:
    """Load all round scores as a trajectory list."""
    trajectory = []
    output_file = workspace_path / "output/score_trajectory.json"
    if output_file.exists():
        try:
            data = json.loads(output_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    round_num = 1
    while True:
        score = load_round_score(workspace_path, round_num)
        if score is None:
            break
        trajectory.append(asdict(score))
        round_num += 1
    return trajectory


def save_score_trajectory(workspace_path: Path, trajectory: list[dict]) -> None:
    """Persist the full score trajectory."""
    output_dir = workspace_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "score_trajectory.json").write_text(
        json.dumps(trajectory, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_current_round(workspace_path: str | Path) -> int:
    """Determine the current round number from rebuttal state."""
    workspace_path = Path(workspace_path)
    state_file = workspace_path / "rebuttal_state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return data.get("round", 1)
        except (json.JSONDecodeError, OSError):
            pass
    return 1


def set_current_round(workspace_path: str | Path, round_num: int) -> None:
    """Update the current round number in rebuttal state."""
    workspace_path = Path(workspace_path)
    state_file = workspace_path / "rebuttal_state.json"
    data = {}
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data["round"] = round_num
    state_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def should_stop(avg_score: float, round_num: int,
                threshold: float, max_rounds: int) -> bool:
    """Dual stop condition: score >= threshold OR round >= max_rounds."""
    return avg_score >= threshold or round_num >= max_rounds
