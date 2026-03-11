"""Helpers for scaffolding and validating a tiny end-to-end Sibyl demo."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

import yaml

from sibyl._paths import REPO_ROOT
from sibyl.orchestration.workspace_paths import (
    load_workspace_iteration_dirs,
    resolve_workspace_root,
)
from sibyl.workspace import Workspace
DEMO_ROOT = REPO_ROOT / "demos" / "remote_parallel_smoke"


@dataclass
class RemoteParallelSmokeDemo:
    project_name: str = "remote-parallel-smoke"
    workspaces_dir: Path = Path("workspaces")
    ssh_server: str = "default"
    remote_base: str = "/home/ccwang/sibyl_system"
    remote_conda_path: str = "/home/ccwang/miniforge3/bin/conda"
    remote_conda_env_name: str = "base"
    gpt2_source_path: str = "/home/ccwang/sibyl_system/models/gpt2"
    qwen_source_path: str = "/home/ccwang/sibyl_system/models/Qwen2.5-1.5B-Instruct"
    max_gpus: int = 2
    max_parallel_tasks: int = 2
    gpu_poll_interval_sec: int = 30
    gpu_aggressive_threshold_pct: int = 80
    language: str = "zh"
    codex_enabled: bool = False
    lark_enabled: bool = False

    @property
    def gpt2_shared_path(self) -> str:
        return "shared/checkpoints/gpt2_local"

    @property
    def qwen_shared_path(self) -> str:
        return "shared/checkpoints/qwen2_5_1_5b_instruct_local"

    @property
    def demo_prompts_path(self) -> str:
        return "shared/demo_prompts.jsonl"

    @property
    def topic(self) -> str:
        return (
            "在远程 GPU 服务器上对 GPT-2 与 Qwen2.5-1.5B-Instruct 做极小型并行推理基准，"
            "完整验证 Sibyl 的远程实验、GPU 调度、实验监控、写作与 LaTeX 链路。"
        )


def _render_template(template_path: Path, mapping: dict[str, str]) -> str:
    text = template_path.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace(f"__{key.upper()}__", str(value))
    return text


def _demo_mapping(spec: RemoteParallelSmokeDemo) -> dict[str, str]:
    return {
        "project_name": spec.project_name,
        "topic": spec.topic,
        "ssh_server": spec.ssh_server,
        "remote_base": spec.remote_base,
        "remote_conda_path": spec.remote_conda_path,
        "remote_conda_env_name": spec.remote_conda_env_name,
        "gpt2_source_path": spec.gpt2_source_path,
        "qwen_source_path": spec.qwen_source_path,
        "gpt2_shared_path": spec.gpt2_shared_path,
        "qwen_shared_path": spec.qwen_shared_path,
        "demo_prompts_path": spec.demo_prompts_path,
        "max_gpus": spec.max_gpus,
        "max_parallel_tasks": spec.max_parallel_tasks,
    }


def build_remote_parallel_demo_config(spec: RemoteParallelSmokeDemo) -> dict:
    return {
        "language": spec.language,
        "ssh_server": spec.ssh_server,
        "remote_base": spec.remote_base,
        "max_gpus": spec.max_gpus,
        "gpus_per_task": 1,
        "max_parallel_tasks": spec.max_parallel_tasks,
        "gpu_poll_enabled": True,
        "gpu_free_threshold_mb": 2000,
        "gpu_poll_interval_sec": spec.gpu_poll_interval_sec,
        "gpu_poll_max_attempts": 20,
        "gpu_aggressive_mode": True,
        "gpu_aggressive_threshold_pct": spec.gpu_aggressive_threshold_pct,
        "experiment_timeout": 180,
        "pilot_samples": 8,
        "pilot_timeout": 180,
        "pilot_seeds": [42],
        "full_seeds": [42],
        "debate_rounds": 2,
        "writing_revision_rounds": 2,
        "idea_exp_cycles": 2,
        "review_enabled": True,
        "writing_mode": "parallel",
        "experiment_mode": "ssh_mcp",
        "codex_enabled": spec.codex_enabled,
        "lark_enabled": spec.lark_enabled,
        "iteration_dirs": True,
        "remote_env_type": "conda",
        "remote_conda_path": spec.remote_conda_path,
        "remote_conda_env_name": spec.remote_conda_env_name,
    }


def build_remote_registry_patch(spec: RemoteParallelSmokeDemo) -> dict:
    return {
        "checkpoints": {
            "gpt2_local": {
                "type": "checkpoint",
                "name": "gpt2",
                "path": spec.gpt2_shared_path,
                "target": spec.gpt2_source_path,
                "source": "preexisting_remote_weight",
                "demo": spec.project_name,
            },
            "qwen2_5_1_5b_instruct_local": {
                "type": "checkpoint",
                "name": "Qwen2.5-1.5B-Instruct",
                "path": spec.qwen_shared_path,
                "target": spec.qwen_source_path,
                "source": "preexisting_remote_weight",
                "demo": spec.project_name,
            },
        }
    }


def build_remote_bootstrap_script(spec: RemoteParallelSmokeDemo) -> str:
    patch_json = json.dumps(build_remote_registry_patch(spec), ensure_ascii=False)
    gpt2_link = f"{spec.remote_base}/{spec.gpt2_shared_path}"
    qwen_link = f"{spec.remote_base}/{spec.qwen_shared_path}"
    return f"""#!/usr/bin/env bash
set -euo pipefail

REMOTE_BASE={shlex.quote(spec.remote_base)}
PROJECT_NAME={shlex.quote(spec.project_name)}

mkdir -p "$REMOTE_BASE/shared/checkpoints" "$REMOTE_BASE/shared/datasets" "$REMOTE_BASE/projects/$PROJECT_NAME"
ln -sfn {shlex.quote(spec.gpt2_source_path)} {shlex.quote(gpt2_link)}
ln -sfn {shlex.quote(spec.qwen_source_path)} {shlex.quote(qwen_link)}

python3 - <<'PY'
import json
from pathlib import Path

registry_path = Path({spec.remote_base!r}) / "shared" / "registry.json"
registry_path.parent.mkdir(parents=True, exist_ok=True)
if registry_path.exists():
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {{}}
else:
    data = {{}}

patch = json.loads({patch_json!r})
for section, items in patch.items():
    bucket = data.setdefault(section, {{}})
    bucket.update(items)

registry_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\\n",
    encoding="utf-8",
)
PY

echo "Remote smoke demo bootstrap complete for $PROJECT_NAME"
echo "Shared checkpoints:"
echo "  - {spec.gpt2_shared_path} -> {spec.gpt2_source_path}"
echo "  - {spec.qwen_shared_path} -> {spec.qwen_source_path}"
"""


def build_demo_contract(spec: RemoteParallelSmokeDemo) -> dict:
    return {
        "demo_name": "remote_parallel_smoke",
        "project_name": spec.project_name,
        "required_setup_files": [
            "spec.md",
            "config.yaml",
            "shared/demo_prompts.jsonl",
            "shared/remote_bootstrap.sh",
            "shared/remote_registry_patch.json",
            "idea/references_seed.md",
        ],
        "required_runtime_outputs": [
            "plan/task_plan.json",
            "exp/gpu_progress.json",
            "writing/paper.md",
            "writing/review.md",
            "writing/latex/main.tex",
            "writing/latex/main.pdf",
            "reflection/lessons_learned.md",
        ],
        "minimum_parallel_tasks": 2,
        "required_visual_outputs": [
            "writing/figures",
            "writing/latex/figures",
        ],
    }


def scaffold_remote_parallel_smoke(spec: RemoteParallelSmokeDemo) -> dict:
    ws = Workspace(spec.workspaces_dir, spec.project_name, iteration_dirs=True)
    mapping = _demo_mapping(spec)

    ws.write_file(
        "config.yaml",
        yaml.safe_dump(
            build_remote_parallel_demo_config(spec),
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    ws.write_file("spec.md", _render_template(DEMO_ROOT / "spec.template.md", mapping))
    ws.write_file("topic.txt", spec.topic)
    ws.write_file(
        "idea/references_seed.md",
        _render_template(DEMO_ROOT / "references_seed.md", mapping),
    )
    ws.write_file(
        "shared/demo_prompts.jsonl",
        (DEMO_ROOT / "demo_prompts.jsonl").read_text(encoding="utf-8"),
    )
    ws.write_file(
        "shared/demo_contract.json",
        json.dumps(build_demo_contract(spec), ensure_ascii=False, indent=2) + "\n",
    )
    ws.write_file(
        "shared/remote_registry_patch.json",
        json.dumps(build_remote_registry_patch(spec), ensure_ascii=False, indent=2) + "\n",
    )
    ws.write_file("shared/remote_bootstrap.sh", build_remote_bootstrap_script(spec))
    ws.write_file(
        "shared/demo_runbook.md",
        _render_template(DEMO_ROOT / "README.md", mapping),
    )
    ws.update_stage("init")
    ws.git_init()

    bootstrap_path = ws.root / "shared" / "remote_bootstrap.sh"
    bootstrap_path.chmod(0o755)

    return {
        "project_name": spec.project_name,
        "workspace_path": str(ws.root),
        "spec_path": str(ws.root / "spec.md"),
        "project_config_path": str(ws.root / "config.yaml"),
        "bootstrap_script_path": str(bootstrap_path),
        "demo_prompts_path": str(ws.root / "shared" / "demo_prompts.jsonl"),
    }


def validate_remote_parallel_smoke(workspace_path: str | Path) -> dict:
    ws_root = resolve_workspace_root(workspace_path)
    ws = Workspace(
        ws_root.parent,
        ws_root.name,
        iteration_dirs=load_workspace_iteration_dirs(ws_root, False),
    )
    contract = build_demo_contract(
        RemoteParallelSmokeDemo(project_name=ws_root.name, workspaces_dir=ws_root.parent)
    )

    def _exists(rel_path: str) -> bool:
        path = ws.project_path(rel_path) if ws._is_project_scoped_path(rel_path) else ws.active_path(rel_path)
        return path.exists()

    setup_missing = [path for path in contract["required_setup_files"] if not _exists(path)]
    output_missing = [
        path for path in contract["required_runtime_outputs"] if not _exists(path)
    ]

    task_count = 0
    parallel_task_count = 0
    completed_task_count = 0
    section_count = 0

    task_plan = ws.active_path("plan/task_plan.json")
    if task_plan.exists():
        try:
            data = json.loads(task_plan.read_text(encoding="utf-8"))
            tasks = data.get("tasks", [])
            task_count = len(tasks)
            parallel_task_count = sum(
                1
                for task in tasks
                if int(task.get("gpu_count", 0) or 0) == 1
            )
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    gpu_progress = ws.active_path("exp/gpu_progress.json")
    if gpu_progress.exists():
        try:
            data = json.loads(gpu_progress.read_text(encoding="utf-8"))
            completed_task_count = len(data.get("completed", []))
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    sections_dir = ws.active_path("writing/sections")
    if sections_dir.exists():
        section_count = len(list(sections_dir.glob("*.md")))

    ok = (
        not setup_missing
        and not output_missing
        and task_count >= contract["minimum_parallel_tasks"]
        and parallel_task_count >= contract["minimum_parallel_tasks"]
        and completed_task_count >= contract["minimum_parallel_tasks"]
    )

    return {
        "workspace_path": str(ws_root),
        "setup_missing": setup_missing,
        "output_missing": output_missing,
        "task_count": task_count,
        "parallel_task_count": parallel_task_count,
        "completed_task_count": completed_task_count,
        "section_count": section_count,
        "ok": ok,
    }
