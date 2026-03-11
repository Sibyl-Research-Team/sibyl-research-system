"""Shared workspace management - the communication backbone between agents."""
import json
import shutil
import subprocess
import time
from pathlib import Path
import dataclasses
from dataclasses import dataclass, asdict, field

from sibyl.runtime_assets import (
    GENERATED_CLAUDE_HEADER,
    WORKSPACE_PROJECT_MEMORY,
    WORKSPACE_PROJECT_PROMPT_OVERLAYS,
    WORKSPACE_SYSTEM_META,
    ensure_workspace_runtime_assets,
)


@dataclass
class WorkspaceStatus:
    stage: str = "init"
    started_at: float = 0.0
    updated_at: float = 0.0
    iteration: int = 0
    errors: list[dict] = field(default_factory=list)
    paused: bool = False
    paused_at: float | None = None
    stop_requested: bool = False
    stop_requested_at: float | None = None
    iteration_dirs: bool = False  # True = iteration subdirectory mode
    stage_started_at: float | None = None  # timestamp when current stage began


def _normalize_status_flag(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", "", "none", "null"}:
            return False
    return fallback


def _normalize_status_timestamp(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def workspace_status_from_data(data: dict | None) -> WorkspaceStatus:
    """Normalize old/new status.json formats into the current schema."""
    raw = data or {}
    known = {f.name for f in dataclasses.fields(WorkspaceStatus)}
    filtered = {k: v for k, v in raw.items() if k in known}

    paused_at = _normalize_status_timestamp(raw.get("paused_at"))
    stop_requested_at = _normalize_status_timestamp(raw.get("stop_requested_at"))
    stop_requested = _normalize_status_flag(
        raw.get("stop_requested"),
        stop_requested_at is not None,
    )
    paused = _normalize_status_flag(
        raw.get("paused"),
        paused_at is not None,
    )

    # Manual stop dominates legacy pause markers; only one state should be active.
    if stop_requested:
        paused = False

    filtered["paused"] = paused
    filtered["paused_at"] = paused_at if paused else None
    filtered["stop_requested"] = stop_requested
    filtered["stop_requested_at"] = stop_requested_at if stop_requested else None
    return WorkspaceStatus(**filtered)


class Workspace:
    """Shared filesystem workspace for a single research project.

    Structure (v4):
        <project_name>/
        ├── status.json
        ├── config.yaml              # project-level config overrides
        ├── CLAUDE.md               # generated effective system+project instructions
        ├── .claude/                # runtime links to system-managed Claude assets
        ├── .sibyl/project/         # project-private memory + overlays
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

    # Standard subdirectories for a workspace or iteration
    _STANDARD_DIRS = [
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
    _PROJECT_SCOPED_FILES = {
        "status.json",
        "config.yaml",
        "topic.txt",
        "spec.md",
        ".gitignore",
        "CLAUDE.md",
    }
    _PROJECT_SCOPED_PREFIXES = (
        "shared/",
        "logs/",
        "current/",
        "iter_",
        ".claude/",
        ".sibyl/",
        ".venv",
        ".git/",
    )

    def __init__(self, base_dir: Path, project_name: str,
                 iteration_dirs: bool = False):
        self.root = base_dir / project_name
        self.name = project_name
        self._init_iteration_dirs = iteration_dirs
        self._init_dirs()

    @classmethod
    def open_existing(
        cls,
        base_dir: Path | str,
        project_name: str,
        iteration_dirs: bool | None = None,
    ) -> "Workspace":
        """Open an existing workspace without mutating runtime assets."""
        root = Path(base_dir) / project_name
        if not root.is_dir():
            raise FileNotFoundError(f"Workspace not found: {root}")

        status_path = root / "status.json"
        if not status_path.exists():
            raise FileNotFoundError(f"Workspace missing status.json: {root}")

        inferred_iteration_dirs = iteration_dirs
        if inferred_iteration_dirs is None:
            try:
                raw_status = json.loads(status_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                inferred_iteration_dirs = False
            else:
                inferred_iteration_dirs = workspace_status_from_data(raw_status).iteration_dirs

        ws = cls.__new__(cls)
        ws.root = root
        ws.name = project_name
        ws._init_iteration_dirs = bool(inferred_iteration_dirs)
        return ws

    def _ensure_standard_dirs(self, base_dir: Path):
        for d in self._STANDARD_DIRS:
            (base_dir / d).mkdir(parents=True, exist_ok=True)

    def _default_iteration_dir(self) -> Path:
        status_path = self.root / "status.json"
        if status_path.exists():
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
                iteration = int(data.get("iteration", 0) or 0)
                if iteration > 0:
                    iter_dir = self.root / f"iter_{iteration:03d}"
                    if iter_dir.exists():
                        return iter_dir
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                pass
        return self.root / "iter_001"

    def _init_dirs(self):
        # Always create shared/ directory
        (self.root / "shared").mkdir(parents=True, exist_ok=True)

        if self._init_iteration_dirs:
            current_link = self.root / "current"
            active_iter_dir = None
            if current_link.is_symlink():
                try:
                    resolved = current_link.resolve()
                except OSError:
                    resolved = None
                if resolved and resolved.exists():
                    active_iter_dir = resolved
            if active_iter_dir is None:
                active_iter_dir = self._default_iteration_dir()
            self._ensure_standard_dirs(active_iter_dir)
            if not current_link.exists():
                current_link.symlink_to(active_iter_dir.name)
            (self.root / "logs" / "iterations").mkdir(parents=True, exist_ok=True)
        else:
            self._ensure_standard_dirs(self.root)

        # init status
        status_path = self.root / "status.json"
        if not status_path.exists():
            status = WorkspaceStatus(
                started_at=time.time(),
                iteration_dirs=self._init_iteration_dirs,
            )
            self._save_status(status)

        ensure_workspace_runtime_assets(self.root)

    def start_new_iteration(self, iteration: int):
        """Create a new iteration directory and update current symlink.

        Copies shared files from shared/ and lessons from previous iteration.
        """
        iter_name = f"iter_{iteration:03d}"
        iter_dir = self.root / iter_name
        for d in self._STANDARD_DIRS:
            (iter_dir / d).mkdir(parents=True, exist_ok=True)

        # Update current symlink
        current_link = self.root / "current"
        if current_link.is_symlink():
            current_link.unlink()
        elif current_link.exists():
            shutil.rmtree(current_link)
        current_link.symlink_to(iter_name)

        # Copy shared files into new iteration
        shared_files = ["literature.md", "references.json"]
        for fname in shared_files:
            src = self.root / "shared" / fname
            if src.exists():
                dst = iter_dir / "context" / fname
                shutil.copy2(src, dst)

        # Copy lessons_learned.md from previous iteration
        prev_name = f"iter_{iteration - 1:03d}"
        prev_lessons = self.root / prev_name / "reflection" / "lessons_learned.md"
        if prev_lessons.exists():
            dst = iter_dir / "reflection" / "lessons_learned.md"
            shutil.copy2(prev_lessons, dst)

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
                    return workspace_status_from_data(data)
                except (json.JSONDecodeError, OSError):
                    pass
            return WorkspaceStatus(started_at=time.time())
        return workspace_status_from_data(data)

    def update_stage(self, stage: str):
        status = self.get_status()
        status.stage = stage
        status.stage_started_at = time.time()
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
        status.stage_started_at = time.time()
        self._save_status(status)


    def add_error(self, error: str):
        status = self.get_status()
        status.errors.append({"time": time.time(), "error": error})
        self._save_status(status)

    def pause(self, reason: str = "rate_limit"):
        status = self.get_status()
        now = time.time()
        if reason == "user_stop":
            status.paused = False
            status.paused_at = None
            status.stop_requested = True
            status.stop_requested_at = now
        else:
            status.paused = True
            status.paused_at = now
            status.stop_requested = False
            status.stop_requested_at = None
        self._save_status(status)
        self.write_file("logs/pause_log.jsonl",
            (self.read_file("logs/pause_log.jsonl") or "") +
            json.dumps({"time": now, "reason": reason,
                         "stage": status.stage, "iteration": status.iteration},
                        ensure_ascii=False) + "\n")

    def resume(self):
        status = self.get_status()
        status.paused = False
        status.paused_at = None
        status.stop_requested = False
        status.stop_requested_at = None
        self._save_status(status)

    def is_paused(self) -> bool:
        return self.get_status().paused

    def is_stop_requested(self) -> bool:
        return self.get_status().stop_requested

    @property
    def active_root(self) -> Path:
        """Return the active working directory for research artifacts."""
        status = self.get_status()
        if status.iteration_dirs and (self.root / "current").exists():
            return self.root / "current"
        return self.root

    def project_path(self, rel_path: str = "") -> Path:
        """Resolve a path relative to the project root."""
        return self._resolve_under(self.root, rel_path)

    def active_path(self, rel_path: str = "") -> Path:
        """Resolve a path relative to the active iteration/current workspace."""
        return self._resolve_under(self.active_root, rel_path)

    def _resolve_under(self, base: Path, rel_path: str) -> Path:
        resolved = (base / rel_path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError(
                f"Path traversal detected: '{rel_path}' resolves outside workspace"
            )
        return resolved

    def _is_project_scoped_path(self, rel_path: str) -> bool:
        return (
            rel_path in self._PROJECT_SCOPED_FILES
            or any(rel_path.startswith(prefix) for prefix in self._PROJECT_SCOPED_PREFIXES)
        )

    def _check_path(self, rel_path: str) -> Path:
        """Resolve rel_path under workspace root and guard against traversal."""
        base = self.root if self._is_project_scoped_path(rel_path) else self.active_root
        return self._resolve_under(base, rel_path)

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
        status = self.get_status()
        if status.iteration_dirs:
            # In iteration_dirs mode, data already lives in iter_NNN/.
            # Sync shared files (literature, references) back to shared/.
            iter_dir = self.root / f"iter_{iteration:03d}"
            for fname in ["literature.md", "references.json"]:
                src = iter_dir / "context" / fname
                if src.exists():
                    dst = self.root / "shared" / fname
                    shutil.copy2(src, dst)
            # Sync experiment_db.jsonl to shared/
            exp_db = iter_dir / "exp" / "experiment_db.jsonl"
            if exp_db.exists():
                shared_db = self.root / "shared" / "experiment_db.jsonl"
                # Append new entries rather than overwrite
                with open(exp_db, encoding="utf-8") as f:
                    new_data = f.read()
                with open(shared_db, "a", encoding="utf-8") as f:
                    f.write(new_data)
        else:
            # Classic mode: copy artifacts to logs/iterations/
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
        gitignore = (
            "*.pyc\n"
            "__pycache__/\n"
            ".DS_Store\n"
            ".venv/\n"
            "CLAUDE.md\n"
            ".claude/agents\n"
            ".claude/skills\n"
            ".claude/settings.local.json\n"
            ".sibyl/system.json\n"
        )
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

    # ══════════════════════════════════════════════
    # Checkpoint tracking (sub-step progress within a stage)
    # ══════════════════════════════════════════════

    def _checkpoint_path(self, checkpoint_dir: str) -> Path:
        return self._check_path(f"{checkpoint_dir}/.checkpoint.json")

    def create_checkpoint(self, stage: str, checkpoint_dir: str,
                          steps: dict[str, str], iteration: int):
        """Create a new checkpoint for a stage with sub-steps.

        Args:
            stage: Pipeline stage name
            checkpoint_dir: Relative dir for .checkpoint.json
            steps: {step_id: relative_file_path} mapping
            iteration: Current iteration number
        """
        cp = {
            "version": 1,
            "stage": stage,
            "iteration": iteration,
            "stage_started_at": time.time(),
            "steps": {
                step_id: {
                    "status": "pending",
                    "file": file_path,
                    "completed_at": 0.0,
                    "file_mtime": 0.0,
                    "file_size": 0,
                    "artifacts": [],
                }
                for step_id, file_path in steps.items()
            },
        }
        self.write_json(f"{checkpoint_dir}/.checkpoint.json", cp)

    def load_checkpoint(self, checkpoint_dir: str) -> dict | None:
        return self.read_json(f"{checkpoint_dir}/.checkpoint.json")

    def _snapshot_checkpoint_file(self, relative_path: str) -> dict | None:
        """Return metadata snapshot for a checkpoint-tracked file."""
        file_path = self._check_path(relative_path)
        if not file_path.exists():
            return None
        stat = file_path.stat()
        if stat.st_size == 0:
            return None
        return {
            "path": relative_path,
            "file_mtime": stat.st_mtime,
            "file_size": stat.st_size,
        }

    def _is_checkpoint_snapshot_valid(self, snapshot: dict,
                                      started_at: float) -> bool:
        """Validate a checkpoint-tracked file snapshot."""
        file_path = self._check_path(snapshot["path"])
        if not file_path.exists():
            return False
        stat = file_path.stat()
        if stat.st_mtime < started_at:
            return False
        if stat.st_size == 0 or stat.st_size != snapshot["file_size"]:
            return False
        return True

    def complete_checkpoint_step(self, checkpoint_dir: str, step_id: str,
                                 artifacts: list[str] | None = None,
                                 require_artifacts_metadata: bool = False):
        """Mark a sub-step as completed with file validation data."""
        cp = self.load_checkpoint(checkpoint_dir)
        if cp is None or step_id not in cp["steps"]:
            return {"completed": False, "missing_files": []}
        step = cp["steps"][step_id]
        primary_snapshot = self._snapshot_checkpoint_file(step["file"])
        if primary_snapshot is None:
            return {"completed": False, "missing_files": [step["file"]]}

        artifact_snapshots = []
        missing_files = []
        if require_artifacts_metadata and artifacts is None:
            return {"completed": False, "missing_files": []}
        for artifact in artifacts or []:
            snapshot = self._snapshot_checkpoint_file(artifact)
            if snapshot is None:
                missing_files.append(artifact)
                continue
            artifact_snapshots.append(snapshot)
        if missing_files:
            return {"completed": False, "missing_files": missing_files}

        step["status"] = "completed"
        step["completed_at"] = time.time()
        step["file_mtime"] = primary_snapshot["file_mtime"]
        step["file_size"] = primary_snapshot["file_size"]
        step["artifacts"] = artifact_snapshots
        self.write_json(f"{checkpoint_dir}/.checkpoint.json", cp)
        return {"completed": True, "missing_files": []}

    def validate_checkpoint(self, checkpoint_dir: str,
                            current_iteration: int | None = None) -> dict | None:
        """Validate checkpoint, return {completed: [...], remaining: [...]}.

        Returns None if no checkpoint or iteration mismatch (stale).
        A step is valid only if:
          1. status == "completed"
          2. Target file exists
          3. file mtime >= stage_started_at
          4. file size matches recorded size and > 0
        """
        cp = self.load_checkpoint(checkpoint_dir)
        if cp is None:
            return None
        if current_iteration is not None and cp["iteration"] != current_iteration:
            return None

        completed = []
        remaining = []
        started_at = cp["stage_started_at"]

        for step_id, step in cp["steps"].items():
            if step["status"] != "completed":
                remaining.append(step_id)
                continue
            primary_snapshot = {
                "path": step["file"],
                "file_mtime": step["file_mtime"],
                "file_size": step["file_size"],
            }
            if not self._is_checkpoint_snapshot_valid(primary_snapshot, started_at):
                remaining.append(step_id)
                continue
            if any(
                not self._is_checkpoint_snapshot_valid(artifact, started_at)
                for artifact in step.get("artifacts", [])
            ):
                remaining.append(step_id)
                continue
            completed.append(step_id)

        return {"completed": completed, "remaining": remaining}

    def clear_checkpoint(self, checkpoint_dir: str):
        path = self._checkpoint_path(checkpoint_dir)
        if path.exists():
            path.unlink()

    def has_checkpoint(self, checkpoint_dir: str) -> bool:
        return self._checkpoint_path(checkpoint_dir).exists()

    def get_project_metadata(self) -> dict:
        """Return a summary of the project for status dashboards."""
        status = self.get_status()
        files = self.list_files()
        has_paper = self.active_path("writing/paper.md").exists()
        has_proposal = self.active_path("idea/proposal.md").exists()
        pilot_results = self.list_files("exp/results/pilots")
        full_results = self.list_files("exp/results/full")
        runtime = self.get_runtime_metadata()
        return {
            "name": self.name,
            "stage": status.stage,
            "iteration": status.iteration,
            "paused": status.paused,
            "stop_requested": status.stop_requested,
            "errors": len(status.errors),
            "total_files": len(files),
            "has_proposal": has_proposal,
            "has_paper": has_paper,
            "pilot_results": len(pilot_results),
            "full_results": len(full_results),
            "started_at": status.started_at,
            "updated_at": status.updated_at,
            "stage_started_at": status.stage_started_at,
            "migration_needed": runtime["migration_needed"],
            "runtime_ready": runtime["runtime_ready"],
            "runtime": runtime,
        }

    def get_runtime_metadata(self) -> dict:
        """Return workspace/runtime composition health for dashboards and migration."""
        warnings: list[str] = []
        system_root = ""

        system_meta_path = self.root / WORKSPACE_SYSTEM_META
        if system_meta_path.exists():
            try:
                system_root = json.loads(system_meta_path.read_text(encoding="utf-8")).get(
                    "system_root", ""
                )
            except (json.JSONDecodeError, OSError):
                warnings.append("Corrupted .sibyl/system.json")
        else:
            warnings.append("Missing .sibyl/system.json")

        project_memory_path = self.root / WORKSPACE_PROJECT_MEMORY
        overlays_dir = self.root / WORKSPACE_PROJECT_PROMPT_OVERLAYS
        claude_path = self.root / "CLAUDE.md"
        agents_link = self.root / ".claude" / "agents"
        skills_link = self.root / ".claude" / "skills"
        settings_link = self.root / ".claude" / "settings.local.json"
        venv_link = self.root / ".venv"

        status_path = self.root / "status.json"
        legacy_status_schema = False
        if status_path.exists():
            try:
                raw_status = json.loads(status_path.read_text(encoding="utf-8"))
                legacy_status_schema = (
                    "paused" not in raw_status
                    or "stop_requested" not in raw_status
                    or "stage_started_at" not in raw_status
                    or "resume_after_sync" in raw_status
                )
            except (json.JSONDecodeError, OSError):
                warnings.append("Corrupted status.json")

        topic_exists = (self.root / "topic.txt").exists()
        config_exists = (self.root / "config.yaml").exists()
        spec_exists = (self.root / "spec.md").exists()
        git_initialized = (self.root / ".git").exists()
        gitignore_exists = (self.root / ".gitignore").exists()
        nested_project_dir = self.root / self.name
        nested_project_dir_exists = nested_project_dir.exists()
        if nested_project_dir_exists:
            warnings.append(f"Nested project directory found: {nested_project_dir.name}/")

        if not topic_exists:
            warnings.append("Missing topic.txt")
        if not config_exists:
            warnings.append("Missing config.yaml")
        if not spec_exists:
            warnings.append("Missing spec.md")
        if not git_initialized:
            warnings.append("Missing workspace git repo")
        if git_initialized and not gitignore_exists:
            warnings.append("Missing .gitignore")
        if legacy_status_schema:
            warnings.append("Legacy status.json schema")

        claude_generated = False
        if claude_path.exists():
            try:
                claude_generated = claude_path.read_text(encoding="utf-8").startswith(
                    GENERATED_CLAUDE_HEADER
                )
            except OSError:
                warnings.append("Unreadable CLAUDE.md")
        else:
            warnings.append("Missing CLAUDE.md")

        project_overlay_count = 0
        if overlays_dir.exists():
            project_overlay_count = len(list(overlays_dir.glob("*.md")))
        else:
            warnings.append("Missing .sibyl/project/prompt_overlays")

        if not project_memory_path.exists():
            warnings.append("Missing .sibyl/project/MEMORY.md")
        if not agents_link.is_symlink() and agents_link.exists():
            warnings.append(".claude/agents is not a symlink")
        if not skills_link.is_symlink() and skills_link.exists():
            warnings.append(".claude/skills is not a symlink")
        if not settings_link.is_symlink() and settings_link.exists():
            warnings.append(".claude/settings.local.json is not a symlink")
        if not venv_link.is_symlink() and venv_link.exists():
            warnings.append(".venv is not a symlink")

        links_ok = all(
            path.is_symlink()
            for path in (agents_link, skills_link, settings_link, venv_link)
        )
        project_layer_ok = project_memory_path.exists() and overlays_dir.exists()
        runtime_ready = bool(system_root) and links_ok and project_layer_ok and claude_generated
        scaffold_ready = (
            topic_exists
            and config_exists
            and spec_exists
            and git_initialized
            and not nested_project_dir_exists
        )
        migration_needed = legacy_status_schema or not runtime_ready or not scaffold_ready

        return {
            "runtime_ready": runtime_ready,
            "scaffold_ready": scaffold_ready,
            "migration_needed": migration_needed,
            "legacy_status_schema": legacy_status_schema,
            "system_root": system_root,
            "project_memory_path": str(project_memory_path),
            "project_memory_exists": project_memory_path.exists(),
            "project_overlay_count": project_overlay_count,
            "claude_md_generated": claude_generated,
            "claude_md_path": str(claude_path),
            "links": {
                "agents": agents_link.is_symlink(),
                "skills": skills_link.is_symlink(),
                "settings": settings_link.is_symlink(),
                "venv": venv_link.is_symlink(),
            },
            "topic_exists": topic_exists,
            "config_exists": config_exists,
            "spec_exists": spec_exists,
            "nested_project_dir_exists": nested_project_dir_exists,
            "git_initialized": git_initialized,
            "gitignore_exists": gitignore_exists,
            "warnings": warnings,
        }
