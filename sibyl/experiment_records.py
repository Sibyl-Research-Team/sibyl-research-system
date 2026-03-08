"""Structured experiment records for Sibyl v4.

JSONL-based experiment database for tracking all experiments.
"""
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class ExperimentRecord:
    experiment_id: str
    project: str
    iteration: int
    method: str
    hyperparams: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)  # ppl, diversity, degeneration
    qualitative: list[str] = field(default_factory=list)  # sample outputs
    status: str = "pending"  # pending, running, completed, failed
    gpu_id: int = -1
    duration: float = 0.0
    seed: int = 42
    timestamp: str = ""
    notes: str = ""
    is_pilot: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ExperimentDB:
    """JSONL-based experiment database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self.db_path.touch()

    def record(self, entry: ExperimentRecord):
        """Append an experiment record."""
        with open(self.db_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def query(self, **filters) -> list[dict]:
        """Query records by field values."""
        results = []
        for record in self._load_all():
            match = all(record.get(k) == v for k, v in filters.items())
            if match:
                results.append(record)
        return results

    def compare(self, experiment_ids: list[str]) -> list[dict]:
        """Compare multiple experiments side by side."""
        all_records = self._load_all()
        return [r for r in all_records if r.get("experiment_id") in experiment_ids]

    def get_best(self, metric: str, minimize: bool = True,
                 **filters) -> dict | None:
        """Get the best experiment by a specific metric."""
        candidates = self.query(**filters) if filters else self._load_all()
        candidates = [c for c in candidates if metric in c.get("metrics", {})]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda x: x["metrics"][metric],
            reverse=not minimize
        )[0]

    def _load_all(self) -> list[dict]:
        """Load all records from the JSONL file."""
        records = []
        if not self.db_path.exists():
            return records
        for line in self.db_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # skip corrupted lines
        return records
