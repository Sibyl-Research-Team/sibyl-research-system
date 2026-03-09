"""Tests for experiment recovery module."""

import json

import pytest

from sibyl.experiment_recovery import (
    ExperimentState,
    load_experiment_state,
    save_experiment_state,
    register_task,
    generate_detection_script,
    parse_detection_output,
)


class TestExperimentStateIO:
    """Task 1: Core data model and I/O."""

    def test_load_nonexistent_returns_empty(self, tmp_path):
        state = load_experiment_state(tmp_path)
        assert isinstance(state, ExperimentState)
        assert state.schema_version == 1
        assert state.tasks == {}
        assert state.last_recovery_at == ""
        assert state.recovery_log == []

    def test_save_and_load_roundtrip(self, tmp_path):
        state = ExperimentState(
            schema_version=1,
            tasks={"t1": {"status": "running", "gpu_ids": [0, 1]}},
            last_recovery_at="2026-03-09T10:00:00",
            recovery_log=["recovered t1"],
        )
        save_experiment_state(tmp_path, state)

        # Verify file exists
        state_file = tmp_path / "exp" / "experiment_state.json"
        assert state_file.exists()

        loaded = load_experiment_state(tmp_path)
        assert loaded.schema_version == 1
        assert loaded.tasks == {"t1": {"status": "running", "gpu_ids": [0, 1]}}
        assert loaded.last_recovery_at == "2026-03-09T10:00:00"
        assert loaded.recovery_log == ["recovered t1"]

    def test_register_task(self, tmp_path):
        state = load_experiment_state(tmp_path)
        register_task(state, "train_baseline", [0, 1], pid_file="/tmp/train.pid")

        assert "train_baseline" in state.tasks
        task = state.tasks["train_baseline"]
        assert task["status"] == "running"
        assert task["gpu_ids"] == [0, 1]
        assert task["pid_file"] == "/tmp/train.pid"
        assert "registered_at" in task


class TestRecoveryScriptGeneration:
    """Task 2: SSH batch detection script generation and parsing."""

    def test_generate_detection_script(self):
        script = generate_detection_script(
            "/home/user/project", ["train_a", "train_b"]
        )
        assert 'cd "/home/user/project"' in script
        assert "train_a" in script
        assert "train_b" in script
        assert "DONE:" in script
        assert "RUNNING:" in script
        assert "DEAD:" in script
        assert "UNKNOWN:" in script

    def test_parse_detection_output_done(self):
        output = 'DONE:train_a:{"exit_code": 0, "elapsed": 120}'
        result = parse_detection_output(output)
        assert "train_a" in result
        assert result["train_a"]["detected_status"] == "done"
        assert result["train_a"]["done_info"]["exit_code"] == 0

    def test_parse_detection_output_running(self):
        output = 'RUNNING:train_a:{"epoch": 5, "loss": 0.3}'
        result = parse_detection_output(output)
        assert result["train_a"]["detected_status"] == "running"
        assert result["train_a"]["progress"]["epoch"] == 5

    def test_parse_detection_output_dead(self):
        output = "DEAD:train_a:12345"
        result = parse_detection_output(output)
        assert result["train_a"]["detected_status"] == "dead"
        assert result["train_a"]["dead_pid"] == "12345"

    def test_parse_detection_output_unknown(self):
        output = "UNKNOWN:train_a"
        result = parse_detection_output(output)
        assert result["train_a"]["detected_status"] == "unknown"

    def test_parse_multiline_output(self):
        output = (
            'DONE:train_a:{"exit_code": 0}\n'
            'RUNNING:train_b:{"epoch": 3}\n'
            "DEAD:train_c:99999\n"
            "UNKNOWN:train_d\n"
        )
        result = parse_detection_output(output)
        assert len(result) == 4
        assert result["train_a"]["detected_status"] == "done"
        assert result["train_b"]["detected_status"] == "running"
        assert result["train_c"]["detected_status"] == "dead"
        assert result["train_d"]["detected_status"] == "unknown"
