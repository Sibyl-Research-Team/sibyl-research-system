"""Shared workspace management - the communication backbone between agents."""
import json
import shutil
import time
from pathlib import Path
from dataclasses import dataclass, asdict, field


@dataclass
class WorkspaceStatus:
    stage: str = "init"
    started_at: float = 0.0
    updated_at: float = 0.0
    iteration: int = 0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class Workspace:
    """Shared filesystem workspace for a single research project.

    Structure (v4):
        <project_name>/
        ├── status.json
        ├── config.yaml              # project-level config overrides
        ├── environment/
        │   └── requirements.txt
        ├── idea/
        │   ├── proposal.md           # final synthesized proposal
        │   ├── alternatives.md       # backup ideas for pivot
        │   ├── references.json
        │   ├── hypotheses.md
        │   ├── perspectives/         # per-agent independent ideas
        │   ├── debate/               # cross-critique records
        │   └── result_debate/        # post-experiment discussion
        ├── plan/
        │   ├── methodology.md
        │   ├── task_plan.json
        │   └── pilot_plan.json
        ├── exp/
        │   ├── code/
        │   ├── results/
        │   │   ├── pilots/
        │   │   └── full/
        │   ├── logs/
        │   └── experiment_db.jsonl
        ├── writing/
        │   ├── outline.md
        │   ├── sections/
        │   ├── critique/
        │   ├── paper.md
        │   ├── review.md
        │   └── figures/
        ├── supervisor/
        ├── critic/
        ├── reflection/
        ├── logs/
        │   ├── iterations/
        │   ├── research_diary.md
        │   └── evolution_log.jsonl
        └── lark_sync/
    """

    def __init__(self, base_dir: Path, project_name: str):
        self.root = base_dir / project_name
        self.name = project_name
        self._init_dirs()

    def _init_dirs(self):
        dirs = [
            "environment",
            "idea", "idea/perspectives", "idea/debate", "idea/result_debate",
            "plan",
            "exp/code", "exp/results/pilots", "exp/results/full", "exp/logs",
            "writing/sections", "writing/critique", "writing/figures",
            "supervisor", "critic", "reflection",
            "logs/iterations",
            "lark_sync",
        ]
        for d in dirs:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        # init status
        status_path = self.root / "status.json"
        if not status_path.exists():
            self._save_status(WorkspaceStatus(started_at=time.time()))

    def _save_status(self, status: WorkspaceStatus):
        status.updated_at = time.time()
        with open(self.root / "status.json", "w") as f:
            json.dump(asdict(status), f, indent=2)

    def get_status(self) -> WorkspaceStatus:
        with open(self.root / "status.json") as f:
            data = json.load(f)
        # Handle legacy status files missing new fields
        known = {f.name for f in WorkspaceStatus.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return WorkspaceStatus(**filtered)

    def update_stage(self, stage: str):
        status = self.get_status()
        status.stage = stage
        self._save_status(status)

    def update_iteration(self, iteration: int):
        status = self.get_status()
        status.iteration = iteration
        self._save_status(status)

    def add_error(self, error: str):
        status = self.get_status()
        status.errors.append({"time": time.time(), "error": error})
        self._save_status(status)

    def write_file(self, rel_path: str, content: str):
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_file(self, rel_path: str) -> str | None:
        path = self.root / rel_path
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_files(self, rel_dir: str = "") -> list[str]:
        target = self.root / rel_dir
        if not target.exists():
            return []
        return [
            str(p.relative_to(self.root))
            for p in target.rglob("*") if p.is_file()
        ]

    def write_json(self, rel_path: str, data: dict | list):
        self.write_file(rel_path, json.dumps(data, indent=2, ensure_ascii=False))

    def read_json(self, rel_path: str) -> dict | list | None:
        content = self.read_file(rel_path)
        if content:
            return json.loads(content)
        return None

    def archive_iteration(self, iteration: int):
        """Archive current iteration artifacts before starting a new one."""
        archive_dir = self.root / "logs" / "iterations" / f"iter_{iteration:03d}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ["idea", "plan", "exp/results", "writing", "supervisor", "critic"]:
            src = self.root / subdir
            if src.exists():
                dst = archive_dir / subdir.replace("/", "_")
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, dirs_exist_ok=True)

    def get_project_metadata(self) -> dict:
        """Return a summary of the project for status dashboards."""
        status = self.get_status()
        files = self.list_files()
        has_paper = (self.root / "writing" / "paper.md").exists()
        has_proposal = (self.root / "idea" / "proposal.md").exists()
        pilot_results = self.list_files("exp/results/pilots")
        full_results = self.list_files("exp/results/full")
        return {
            "name": self.name,
            "stage": status.stage,
            "iteration": status.iteration,
            "errors": len(status.errors),
            "total_files": len(files),
            "has_proposal": has_proposal,
            "has_paper": has_paper,
            "pilot_results": len(pilot_results),
            "full_results": len(full_results),
            "started_at": status.started_at,
            "updated_at": status.updated_at,
        }
