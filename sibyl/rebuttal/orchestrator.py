"""RebuttalOrchestrator — independent state machine for rebuttal pipeline."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sibyl.orchestration.config_helpers import load_effective_config
from sibyl.orchestration.models import Action
from sibyl.workspace import Workspace

from . import actions as _actions
from .config import RebuttalConfig
from .constants import REBUTTAL_STAGES
from . import scoring as _scoring
from . import state_machine as _state_machine


class RebuttalOrchestrator:
    """State-machine orchestrator for the adversarial rebuttal pipeline.

    Independent from FarsOrchestrator but follows identical patterns
    for Action generation, team dispatch, and CLI interaction.
    """

    STAGES = REBUTTAL_STAGES

    def __init__(self, workspace_path: str | Path):
        ws_path = Path(workspace_path).expanduser().resolve()
        self.config = load_effective_config(workspace_path=ws_path)
        self.rebuttal_config = RebuttalConfig.from_workspace(ws_path, self.config)
        self.ws = Workspace.open_existing(ws_path.parent, ws_path.name)
        self.workspace_path = str(self.ws.root)

    def get_next_action(self) -> dict:
        """Determine and return the next action based on current state."""
        status = self.ws.get_status()
        stage = status.stage
        action = self._compute_action(stage)
        result = asdict(action)
        result["language"] = self.rebuttal_config.language
        result["round"] = _scoring.get_current_round(Path(self.workspace_path))
        return result

    def record_result(self, stage: str, result: str = "",
                      score: float | None = None) -> dict:
        """Record stage completion and advance state."""
        current = self.ws.get_status().stage
        if stage != current:
            raise ValueError(
                f"Stage mismatch: recording '{stage}' but current is '{current}'"
            )

        next_stage, new_round = _state_machine.get_next_stage(
            self, stage, result, score,
        )

        # Update stage via Workspace (preserves all WorkspaceStatus fields)
        self.ws.update_stage(next_stage)

        # Round is managed by state_machine._prepare_next_round via rebuttal_state.json
        current_round = _scoring.get_current_round(Path(self.workspace_path))
        return {
            "status": "ok",
            "new_stage": next_stage,
            "round": current_round,
        }

    def get_status(self) -> dict:
        """Get current rebuttal project status."""
        ws_path = Path(self.workspace_path)
        status = self.ws.get_status()
        trajectory = _scoring.load_score_trajectory(ws_path)
        current_round = _scoring.get_current_round(ws_path)
        rc = self.rebuttal_config

        return {
            "stage": status.stage,
            "round": current_round,
            "max_rounds": rc.max_rounds,
            "score_threshold": rc.score_threshold,
            "word_limit": rc.word_limit,
            "reviewer_count": rc.reviewer_count,
            "reviewer_ids": rc.reviewer_ids,
            "codex_enabled": rc.codex_enabled,
            "score_trajectory": trajectory,
        }

    def _compute_action(self, stage: str) -> Action:
        """Dispatch to action builder by stage name."""
        ws = self.workspace_path

        dispatch = {
            "init": lambda: Action(
                action_type="bash",
                bash_command="echo 'Rebuttal workspace initialized'",
                description="Rebuttal 项目初始化完成",
                stage="init",
            ),
            "parse_reviews": lambda: _actions.build_parse_reviews_action(ws),
            "strategy": lambda: _actions.build_strategy_action(ws),
            "rebuttal_draft": lambda: _actions.build_rebuttal_draft_action(self, ws),
            "simulated_review": lambda: _actions.build_simulated_review_action(self, ws),
            "codex_review": lambda: _actions.build_codex_review_action(self, ws),
            "score_evaluate": lambda: _actions.build_score_evaluate_action(self, ws),
            "final_synthesis": lambda: _actions.build_final_synthesis_action(self, ws),
        }

        if stage in dispatch:
            return dispatch[stage]()

        if stage == "done":
            return Action(action_type="done", description="Rebuttal complete", stage="done")

        return Action(action_type="done", description=f"Unknown stage: {stage}", stage="done")
