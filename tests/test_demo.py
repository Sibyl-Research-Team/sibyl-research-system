"""Tests for the tiny remote smoke demo scaffold."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sibyl.demo import (
    RemoteParallelSmokeDemo,
    build_remote_bootstrap_script,
    scaffold_remote_parallel_smoke,
    validate_remote_parallel_smoke,
)
from sibyl.workspace import Workspace


class TestRemoteParallelSmokeDemo:
    def test_scaffold_creates_workspace_assets(self, tmp_path):
        spec = RemoteParallelSmokeDemo(
            project_name="demo-smoke",
            workspaces_dir=tmp_path,
            ssh_server="default",
            remote_base="/remote/base",
            remote_conda_path="/remote/conda/bin/conda",
            remote_conda_env_name="base",
            gpt2_source_path="/models/gpt2",
            qwen_source_path="/models/qwen",
        )

        result = scaffold_remote_parallel_smoke(spec)
        ws_root = Path(result["workspace_path"])

        assert ws_root == tmp_path / "demo-smoke"
        assert (ws_root / "spec.md").exists()
        assert (ws_root / "shared" / "demo_prompts.jsonl").exists()
        assert (ws_root / "shared" / "remote_bootstrap.sh").exists()
        assert (ws_root / "current").is_symlink()

        config = yaml.safe_load((ws_root / "config.yaml").read_text(encoding="utf-8"))
        assert config["ssh_server"] == "default"
        assert config["remote_base"] == "/remote/base"
        assert config["iteration_dirs"] is True
        assert config["max_parallel_tasks"] == 2
        assert config["remote_conda_env_name"] == "base"

        spec_text = (ws_root / "spec.md").read_text(encoding="utf-8")
        assert "shared/checkpoints/gpt2_local" in spec_text
        assert "shared/checkpoints/qwen2_5_1_5b_instruct_local" in spec_text

    def test_bootstrap_script_registers_shared_checkpoints(self):
        spec = RemoteParallelSmokeDemo(
            remote_base="/remote/base",
            gpt2_source_path="/models/gpt2",
            qwen_source_path="/models/qwen",
        )
        script = build_remote_bootstrap_script(spec)

        assert "shared/checkpoints/gpt2_local" in script
        assert "shared/checkpoints/qwen2_5_1_5b_instruct_local" in script
        assert "/models/gpt2" in script
        assert "/models/qwen" in script
        assert "registry.json" in script

    def test_validator_reports_missing_outputs_on_fresh_scaffold(self, tmp_path):
        spec = RemoteParallelSmokeDemo(project_name="demo-smoke", workspaces_dir=tmp_path)
        result = scaffold_remote_parallel_smoke(spec)

        report = validate_remote_parallel_smoke(result["workspace_path"])

        assert report["ok"] is False
        assert "plan/task_plan.json" in report["output_missing"]
        assert "writing/latex/main.pdf" in report["output_missing"]

    def test_validator_accepts_minimal_complete_demo_workspace(self, tmp_path):
        spec = RemoteParallelSmokeDemo(project_name="demo-smoke", workspaces_dir=tmp_path)
        result = scaffold_remote_parallel_smoke(spec)
        ws = Workspace(tmp_path, "demo-smoke", iteration_dirs=True)
        ws.write_file(
            "plan/task_plan.json",
            json.dumps(
                {
                    "tasks": [
                        {"id": "gpt2", "gpu_count": 1, "estimated_minutes": 2},
                        {"id": "qwen", "gpu_count": 1, "estimated_minutes": 2},
                    ]
                }
            ),
        )
        ws.write_file(
            "exp/gpu_progress.json",
            json.dumps(
                {
                    "completed": ["gpt2", "qwen"],
                    "failed": [],
                    "running": {},
                    "timings": {},
                }
            ),
        )
        ws.write_file("writing/paper.md", "# Demo Paper\n")
        ws.write_file("writing/review.md", "SCORE: 9.0\n")
        ws.write_file("writing/latex/main.tex", "\\documentclass{article}\n")
        ws.write_file("writing/latex/main.pdf", "pdf")
        ws.write_file("reflection/lessons_learned.md", "- demo\n")

        report = validate_remote_parallel_smoke(result["workspace_path"])

        assert report["ok"] is True
        assert report["task_count"] == 2
        assert report["parallel_task_count"] == 2
        assert report["completed_task_count"] == 2
