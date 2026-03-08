"""Reflection and iteration logging for the Sibyl pipeline.

Handles:
- Post-stage reflection
- Iteration logging
- Experience consolidation
- Style learning from reference papers
"""
import json
import time
from pathlib import Path


class IterationLogger:
    """Logs each iteration of the pipeline with improvements and issues."""

    def __init__(self, workspace_root: Path):
        self.log_dir = workspace_root / "logs" / "iterations"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_iteration(self, iteration: int, stage: str, changes: list[str],
                      issues_found: list[str], issues_fixed: list[str],
                      quality_score: float, notes: str = ""):
        entry = {
            "iteration": iteration,
            "stage": stage,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "changes": changes,
            "issues_found": issues_found,
            "issues_fixed": issues_fixed,
            "quality_score": quality_score,
            "notes": notes,
        }

        log_file = self.log_dir / f"iter_{iteration:03d}_{stage}.json"
        log_file.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

        # Append to master log
        master_log = self.log_dir / "master_log.jsonl"
        with open(master_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    def get_history(self) -> list[dict]:
        master_log = self.log_dir / "master_log.jsonl"
        if not master_log.exists():
            return []
        entries = []
        for line in master_log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def get_latest_score(self, stage: str) -> float | None:
        history = self.get_history()
        for entry in reversed(history):
            if entry["stage"] == stage:
                return entry["quality_score"]
        return None
