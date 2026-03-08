"""Shared workspace management - the communication backbone between agents."""
import json
import shutil
import subprocess
import time
from pathlib import Path
import dataclasses
from dataclasses import dataclass, asdict, field


@dataclass
class WorkspaceStatus:
    stage: str = "init"
    started_at: float = 0.0
    updated_at: float = 0.0
    iteration: int = 0
    errors: list[dict] = field(default_factory=list)
    paused_at: float = 0.0  # 0 = not paused, >0 = pause timestamp


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
        ├── context/
        │   └── literature.md
        ├── codex/
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
            "writing/sections", "writing/critique", "writing/figures", "writing/latex",
            "context", "codex",
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
        tmp = self.root / "status.json.tmp"
        tmp.write_text(json.dumps(asdict(status), indent=2), encoding="utf-8")
        tmp.replace(self.root / "status.json")  # atomic on POSIX

    def get_status(self) -> WorkspaceStatus:
        try:
            data = json.loads((self.root / "status.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            tmp = self.root / "status.json.tmp"
            if tmp.exists():
                try:
                    data = json.loads(tmp.read_text(encoding="utf-8"))
                    known = {f.name for f in dataclasses.fields(WorkspaceStatus)}
                    return WorkspaceStatus(**{k: v for k, v in data.items() if k in known})
                except (json.JSONDecodeError, OSError):
                    pass
            return WorkspaceStatus(started_at=time.time())
        known = {f.name for f in dataclasses.fields(WorkspaceStatus)}
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

    def update_stage_and_iteration(self, stage: str, iteration: int):
        """Atomically update both stage and iteration in a single write."""
        status = self.get_status()
        status.stage = stage
        status.iteration = iteration
        self._save_status(status)

    def add_error(self, error: str):
        status = self.get_status()
        status.errors.append({"time": time.time(), "error": error})
        self._save_status(status)

    def pause(self, reason: str = "rate_limit"):
        status = self.get_status()
        status.paused_at = time.time()
        self._save_status(status)
        self.write_file("logs/pause_log.jsonl",
            (self.read_file("logs/pause_log.jsonl") or "") +
            json.dumps({"time": time.time(), "reason": reason,
                         "stage": status.stage, "iteration": status.iteration},
                        ensure_ascii=False) + "\n")

    def resume(self):
        status = self.get_status()
        status.paused_at = 0.0
        self._save_status(status)

    def is_paused(self) -> bool:
        return self.get_status().paused_at > 0

    def _check_path(self, rel_path: str) -> Path:
        """Resolve rel_path under workspace root and guard against traversal."""
        resolved = (self.root / rel_path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError(
                f"Path traversal detected: '{rel_path}' resolves outside workspace"
            )
        return resolved

    def write_file(self, rel_path: str, content: str):
        path = self._check_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_file(self, rel_path: str) -> str | None:
        path = self._check_path(rel_path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_files(self, rel_dir: str = "") -> list[str]:
        root_resolved = self.root.resolve()
        target = self._check_path(rel_dir).resolve() if rel_dir else root_resolved
        if not target.exists():
            return []
        return [
            str(p.relative_to(root_resolved))
            for p in target.rglob("*") if p.is_file() and not p.is_symlink()
        ]

    def write_json(self, rel_path: str, data: dict | list):
        self.write_file(rel_path, json.dumps(data, indent=2, ensure_ascii=False))

    def read_json(self, rel_path: str) -> dict | list | None:
        content = self.read_file(rel_path)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
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

    # ══════════════════════════════════════════════
    # Git version management
    # ══════════════════════════════════════════════

    def git_init(self):
        """Initialize git repo in workspace if not already initialized."""
        if (self.root / ".git").exists():
            return
        subprocess.run(["git", "init"], cwd=self.root, capture_output=True)
        gitignore = "*.pyc\n__pycache__/\n.DS_Store\n"
        (self.root / ".gitignore").write_text(gitignore, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: initialize Sibyl research project"],
            cwd=self.root, capture_output=True,
        )

    def git_commit(self, message: str):
        """Stage all changes and commit."""
        if not (self.root / ".git").exists():
            self.git_init()
        subprocess.run(["git", "add", "."], cwd=self.root, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.root, capture_output=True,
        )
        if result.returncode != 0:  # there are staged changes
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.root, capture_output=True,
            )

    def git_tag(self, tag: str, message: str = ""):
        """Create a git tag."""
        if not (self.root / ".git").exists():
            return
        cmd = ["git", "tag", "-a", tag, "-m", message or tag]
        subprocess.run(cmd, cwd=self.root, capture_output=True)

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
