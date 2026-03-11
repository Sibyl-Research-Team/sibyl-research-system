"""Workspace migration helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from sibyl.config import Config
from sibyl.workspace import Workspace

from .config_helpers import load_effective_config, write_project_config
from .constants import RUNTIME_GITIGNORE_LINES
from .workspace_paths import resolve_workspace_root


def infer_topic_for_workspace(ws: Workspace) -> str:
    """Infer a reasonable topic when legacy workspaces are missing topic.txt."""
    spec_path = ws.root / "spec.md"
    if spec_path.exists():
        try:
            spec_text = spec_path.read_text(encoding="utf-8")
            match = re.search(r"^#\s*(.+)", spec_text, re.MULTILINE)
            if match:
                return match.group(1).strip()
        except OSError:
            pass

    proposal = ws.read_file("idea/proposal.md")
    if proposal:
        title_match = re.search(r"^#\s*(.+)", proposal, re.MULTILINE)
        if title_match:
            return title_match.group(1).strip()

    topic = ws.read_file("topic.txt")
    if topic:
        return topic.strip()

    return ws.name.replace("-", " ").title()


def detect_workspace_iteration_dirs(
    workspace_root: Path,
    raw_status: dict,
    default: bool,
) -> bool:
    """Infer iteration directory mode for legacy workspaces."""
    if "iteration_dirs" in raw_status:
        return bool(raw_status.get("iteration_dirs"))
    current_link = workspace_root / "current"
    if current_link.exists():
        return True
    return any(
        child.is_dir() and re.fullmatch(r"iter_\d{3}", child.name)
        for child in workspace_root.iterdir()
    ) or default


def strip_leading_title(markdown: str) -> str:
    lines = markdown.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def build_migrated_spec(ws: Workspace, topic: str) -> str:
    """Build a conservative spec.md for a legacy workspace."""
    proposal = ws.read_file("idea/proposal.md") or ""
    proposal_body = strip_leading_title(proposal)
    lines = [
        f"# 项目: {ws.name}",
        "",
        "## 研究主题",
        topic,
        "",
    ]

    if proposal_body:
        lines.extend([
            "## 背景与当前状态",
            "_以下内容由旧版 `idea/proposal.md` 回填，建议后续继续整理为正式 spec。_",
            "",
            proposal_body,
            "",
        ])
    else:
        lines.extend([
            "## 背景与当前状态",
            "_旧项目迁移自动生成，请补充研究背景、关键约束和目标产出。_",
            "",
            "## 关键约束",
            "- 待补充",
            "",
            "## 目标产出",
            "- 待补充",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def ensure_workspace_gitignore(
    ws: Workspace,
    runtime_gitignore_lines: Sequence[str] = RUNTIME_GITIGNORE_LINES,
) -> bool:
    """Ensure runtime-managed paths are ignored inside the workspace repo."""
    gitignore_path = ws.root / ".gitignore"
    existing_lines: list[str] = []
    if gitignore_path.exists():
        existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()

    changed = False
    for line in runtime_gitignore_lines:
        if line not in existing_lines:
            existing_lines.append(line)
            changed = True

    if changed or not gitignore_path.exists():
        content = "\n".join(existing_lines).rstrip() + "\n"
        gitignore_path.write_text(content, encoding="utf-8")
    return changed


def ensure_workspace_git_repo(
    ws: Workspace,
    changes: list[str],
    warnings: list[str],
    *,
    runtime_gitignore_lines: Sequence[str] = RUNTIME_GITIGNORE_LINES,
) -> None:
    """Initialize a per-workspace git repo without clobbering custom ignores."""
    git_was_present = (ws.root / ".git").exists()
    gitignore_changed = ensure_workspace_gitignore(ws, runtime_gitignore_lines)
    if gitignore_changed:
        changes.append("Updated .gitignore for layered runtime assets")
    elif not (ws.root / ".gitignore").exists():
        changes.append("Created .gitignore for layered runtime assets")

    if git_was_present:
        return

    init_result = subprocess.run(
        ["git", "init"],
        cwd=ws.root,
        capture_output=True,
        text=True,
    )
    if init_result.returncode != 0:
        warnings.append(f"Failed to initialize git repo: {init_result.stderr.strip()}")
        return
    changes.append("Initialized workspace git repository")

    subprocess.run(["git", "add", "."], cwd=ws.root, capture_output=True, text=True)
    commit_result = subprocess.run(
        ["git", "commit", "-m", "feat: initialize Sibyl research project"],
        cwd=ws.root,
        capture_output=True,
        text=True,
    )
    if commit_result.returncode == 0:
        changes.append("Created initial workspace git commit")
        return

    commit_output = f"{commit_result.stdout}\n{commit_result.stderr}".lower()
    if "nothing to commit" not in commit_output:
        warnings.append("Git repo initialized but initial commit failed")


def merge_pending_sync_jsonl(target_path: Path, legacy_path: Path) -> bool:
    """Merge a legacy pending_sync.jsonl into the canonical workspace path."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_lines = (
        target_path.read_text(encoding="utf-8").splitlines()
        if target_path.exists()
        else []
    )
    legacy_lines = (
        legacy_path.read_text(encoding="utf-8").splitlines()
        if legacy_path.exists()
        else []
    )

    merged = list(target_lines)
    for line in legacy_lines:
        if line and line not in merged:
            merged.append(line)

    def _sort_key(line: str) -> tuple[str, str]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return ("", line)
        return (str(payload.get("timestamp") or payload.get("at") or ""), line)

    merged.sort(key=_sort_key)
    if merged == target_lines:
        return False

    content = "\n".join(merged).rstrip()
    if content:
        content += "\n"
    target_path.write_text(content, encoding="utf-8")
    return True


def cleanup_legacy_nested_workspace_dir(
    ws: Workspace,
    changes: list[str],
    warnings: list[str],
) -> None:
    """Flatten supported legacy nested workspace artifacts back into the root."""
    nested_root = ws.root / ws.name
    if not nested_root.exists() or not nested_root.is_dir():
        return

    supported_files = {"lark_sync/pending_sync.jsonl"}
    unsupported_files: list[str] = []
    for path in nested_root.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(nested_root).as_posix()
            if rel_path not in supported_files:
                unsupported_files.append(rel_path)

    if unsupported_files:
        warnings.append(
            "Legacy nested workspace directory contains unsupported files: "
            + ", ".join(sorted(unsupported_files))
        )
        return

    legacy_pending = nested_root / "lark_sync" / "pending_sync.jsonl"
    if legacy_pending.exists():
        merged = merge_pending_sync_jsonl(
            ws.root / "lark_sync" / "pending_sync.jsonl",
            legacy_pending,
        )
        if merged:
            changes.append("Merged legacy nested lark_sync/pending_sync.jsonl into workspace root")

    shutil.rmtree(nested_root)
    changes.append("Removed legacy nested workspace directory")


def migrate_workspace(
    workspace_path: str | Path,
) -> dict:
    """Migrate one project workspace onto the layered runtime scaffold."""
    ws_path = resolve_workspace_root(workspace_path)
    if not ws_path.exists():
        return {"error": f"Workspace not found: {workspace_path}"}

    raw_status: dict = {}
    status_path = ws_path / "status.json"
    if status_path.exists():
        try:
            raw_status = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw_status = {}
    default_cfg = load_effective_config(workspace_path=ws_path)
    iteration_dirs = detect_workspace_iteration_dirs(
        ws_path,
        raw_status,
        default_cfg.iteration_dirs,
    )

    runtime_scaffold_was_ready = all(
        (ws_path / rel_path).exists() or (ws_path / rel_path).is_symlink()
        for rel_path in (
            ".sibyl/system.json",
            ".sibyl/project/MEMORY.md",
            ".sibyl/project/prompt_overlays",
            "CLAUDE.md",
            ".claude/agents",
            ".claude/skills",
            ".claude/settings.local.json",
            ".venv",
        )
    )

    ws = Workspace(ws_path.parent, ws_path.name, iteration_dirs=iteration_dirs)
    changes: list[str] = []
    warnings: list[str] = []

    if not (ws.root / "topic.txt").exists():
        topic = infer_topic_for_workspace(ws)
        ws.write_file("topic.txt", topic)
        changes.append(f"Created topic.txt: {topic}")
    else:
        topic = (ws.read_file("topic.txt") or "").strip() or infer_topic_for_workspace(ws)

    config_path = ws.root / "config.yaml"
    if not config_path.exists():
        write_project_config(ws, default_cfg)
        changes.append("Created project config snapshot")
    else:
        current_cfg = load_effective_config(workspace_path=ws.root)
        expected_workspaces_dir = ws.root.parent.resolve()
        if current_cfg.workspaces_dir != expected_workspaces_dir:
            write_project_config(ws, current_cfg)
            changes.append("Normalized project config workspaces_dir to workspace parent")

    if not (ws.root / "spec.md").exists():
        ws.write_file("spec.md", build_migrated_spec(ws, topic))
        changes.append("Created spec.md from legacy workspace state")

    ensure_workspace_git_repo(
        ws,
        changes,
        warnings,
    )
    cleanup_legacy_nested_workspace_dir(ws, changes, warnings)

    normalized_status = ws.get_status()
    normalized_status.iteration_dirs = iteration_dirs
    if normalized_status.stage_started_at is None and normalized_status.updated_at:
        normalized_status.stage_started_at = normalized_status.updated_at
        changes.append("Backfilled stage_started_at from updated_at")
    if normalized_status.iteration == 0 and normalized_status.stage == "done":
        normalized_status.iteration = 1
        changes.append("Set iteration to 1 for completed legacy project")

    normalized_payload = asdict(normalized_status)
    if raw_status != normalized_payload:
        ws._save_status(normalized_status)
        changes.append("Normalized status.json to current schema")

    runtime_after = ws.get_runtime_metadata()
    if not runtime_scaffold_was_ready:
        changes.append("Installed layered runtime scaffold")

    warnings.extend(runtime_after["warnings"])
    return {
        "project_name": ws.name,
        "workspace_path": str(ws.root),
        "changes": changes,
        "warnings": warnings,
        "runtime": runtime_after,
        "status": {
            "stage": ws.get_status().stage,
            "iteration": ws.get_status().iteration,
        },
    }


def cli_migrate(
    workspace_path: str,
) -> None:
    """Migrate a legacy project to the layered runtime structure."""
    print(json.dumps(migrate_workspace(workspace_path), indent=2, ensure_ascii=False))


def cli_migrate_all(
    *,
    workspaces_dir: str | None = None,
) -> None:
    """Migrate every detected project under a workspaces directory."""
    cfg = load_effective_config()
    ws_dir = Path(workspaces_dir).expanduser() if workspaces_dir else cfg.workspaces_dir
    ws_dir = ws_dir.resolve()
    if not ws_dir.exists():
        print(json.dumps({"error": f"Workspaces dir not found: {ws_dir}"}))
        return

    results = []
    for project_dir in sorted(ws_dir.iterdir()):
        if not project_dir.is_dir() or not (project_dir / "status.json").exists():
            continue
        results.append(migrate_workspace(project_dir))

    print(json.dumps({
        "workspaces_dir": str(ws_dir),
        "total": len(results),
        "migrated": [
            {
                "project_name": result.get("project_name", ""),
                "changes": result.get("changes", []),
                "warnings": result.get("warnings", []),
                "migration_needed": result.get("runtime", {}).get("migration_needed", False),
            }
            for result in results
        ],
    }, indent=2, ensure_ascii=False))


def cli_migrate_server(project_name: str, ssh_connection: str = "default") -> None:
    """Generate server-side migration commands for a project."""
    _ = ssh_connection
    if not re.fullmatch(r"[a-zA-Z0-9_\-]{1,60}", project_name):
        print(json.dumps({"error": f"Invalid project_name: {project_name!r}"}))
        return

    config = Config()
    remote_base = config.remote_base
    project_dir = f"{remote_base}/projects/{project_name}"
    commands = [
        f"# === 服务器端 v5 迁移: {project_name} ===",
        f"mkdir -p {project_dir}/{{idea,plan,exp/code,exp/results/pilots,exp/results/full,exp/logs,writing/latex,writing/sections,writing/figures,supervisor,critic,reflection,logs/iterations,lark_sync,shared}}",
        "",
        "# 创建共享资源目录",
        f"mkdir -p {remote_base}/shared/{{datasets,checkpoints}}",
        f'test -f {remote_base}/shared/registry.json || echo \'{{}}\' > {remote_base}/shared/registry.json',
        "",
        "# 迁移实验代码",
        f"cp -r {remote_base}/exp/code/* {project_dir}/exp/code/ 2>/dev/null || true",
        "",
        "# 迁移实验日志",
        f"cp -r {remote_base}/exp/logs/* {project_dir}/exp/logs/ 2>/dev/null || true",
        "",
        "# 迁移研究想法",
        f"cp -r {remote_base}/idea/* {project_dir}/idea/ 2>/dev/null || true",
        "",
        "# 迁移迭代日志",
        f"cp -r {remote_base}/logs/* {project_dir}/logs/ 2>/dev/null || true",
        "",
        "# 迁移论文草稿",
        f"cp -r {remote_base}/writing/* {project_dir}/writing/ 2>/dev/null || true",
        "",
        "# 创建状态文件",
        f'echo \'{{"stage": "done", "started_at": 0, "updated_at": 0, "iteration": 1, "errors": [], "paused": false, "paused_at": null, "stop_requested": false, "stop_requested_at": null, "iteration_dirs": false, "stage_started_at": 0}}\' > {project_dir}/status.json',
        "",
        "# 保留共享资源的符号链接",
        f"ln -sf {remote_base}/models {project_dir}/models 2>/dev/null || true",
        f"ln -sf {remote_base}/src {project_dir}/src 2>/dev/null || true",
        "",
        f"echo '迁移完成: {project_dir}'",
    ]

    print(json.dumps({
        "project_name": project_name,
        "remote_project_dir": project_dir,
        "commands": commands,
        "instructions": (
            "使用 mcp__ssh-mcp-server__execute-command 依次执行上述命令。\n"
            "模型和源码目录通过符号链接共享，避免重复存储。\n"
            "迁移后，新项目将在 projects/ 子目录下创建，互不干扰。"
        ),
    }, indent=2))
