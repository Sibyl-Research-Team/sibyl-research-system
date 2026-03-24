"""Rebuttal-specific configuration via composition over the base Config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RebuttalConfig:
    """Rebuttal-specific config fields. Wraps the base Config via composition."""

    max_rounds: int = 3
    score_threshold: float = 7.0
    word_limit: int = 0  # 0 = no limit; per-reviewer word limit
    codex_enabled: bool = False
    codex_model: str = ""
    language: str = "en"  # Rebuttals default to English

    # Inferred at init time
    reviewer_count: int = 0
    reviewer_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_workspace(cls, workspace_path: Path, base_config: object | None = None) -> "RebuttalConfig":
        """Load rebuttal config from workspace rebuttal_config.yaml."""
        rc = cls()
        if base_config is not None:
            rc.codex_enabled = getattr(base_config, "codex_enabled", False)
            rc.codex_model = getattr(base_config, "codex_model", "")
            rc.language = getattr(base_config, "language", "en")

        config_file = Path(workspace_path) / "rebuttal_config.yaml"
        if config_file.exists():
            data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            for key in ("max_rounds", "score_threshold", "word_limit",
                        "codex_enabled", "codex_model", "language"):
                if key in data:
                    setattr(rc, key, data[key])
            if "reviewer_ids" in data:
                rc.reviewer_ids = data["reviewer_ids"]
                rc.reviewer_count = len(rc.reviewer_ids)

        return rc

    def to_yaml(self) -> str:
        return yaml.safe_dump({
            "max_rounds": self.max_rounds,
            "score_threshold": self.score_threshold,
            "word_limit": self.word_limit,
            "codex_enabled": self.codex_enabled,
            "codex_model": self.codex_model,
            "language": self.language,
            "reviewer_ids": self.reviewer_ids,
        }, allow_unicode=True, sort_keys=False)
