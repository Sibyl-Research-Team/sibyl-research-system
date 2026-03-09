"""Tests for experiment recovery module."""

import json

import pytest

from sibyl.experiment_recovery import (
    ExperimentState,
    RecoveryResult,
    load_experiment_state,
    save_experiment_state,
    register_task,
    generate_detection_script,
    parse_detection_output,
    get_running_tasks,
    recover_from_detection,
    sync_to_gpu_progress,
    migrate_from_gpu_progress,
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


def _make_state_with_tasks(**task_statuses):
    """Helper: create ExperimentState with tasks at given statuses."""
    tasks = {}
    for tid, status in task_statuses.items():
        tasks[tid] = {"status": status, "gpu_ids": [0], "pid_file": "", "registered_at": ""}
    return ExperimentState(tasks=tasks)


class TestRecoveryLogic:
    """Task 3: Core recovery logic."""

    def test_get_running_tasks_filters_correctly(self):
        state = _make_state_with_tasks(
            t1="running", t2="completed", t3="running", t4="failed"
        )
        running = get_running_tasks(state)
        assert sorted(running) == ["t1", "t3"]

    def test_recover_done_marks_completed(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "done", "done_info": {"exit_code": 0}}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "completed"
        assert "t1" in result.recovered_completed

    def test_recover_done_failed_marks_failed(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "done", "done_info": {"exit_code": 1}}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result.recovered_failed

    def test_recover_running_keeps_running_with_progress(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "running", "progress": {"epoch": 5}}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "running"
        assert "t1" in result.still_running
        assert result.progress["t1"] == {"epoch": 5}

    def test_recover_dead_marks_failed(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "dead", "dead_pid": "12345"}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result.recovered_failed

    def test_recover_unknown_marks_failed(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "unknown"}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result.recovered_failed

    def test_recovery_result_needs_monitor(self):
        state = _make_state_with_tasks(t1="running", t2="running")
        detection = {
            "t1": {"detected_status": "done", "done_info": {"exit_code": 0}},
            "t2": {"detected_status": "running", "progress": {}},
        }
        result = recover_from_detection(state, detection)
        assert result.needs_monitor is True

        # All done -> no monitor needed
        state2 = _make_state_with_tasks(t1="running")
        detection2 = {"t1": {"detected_status": "done", "done_info": {"exit_code": 0}}}
        result2 = recover_from_detection(state2, detection2)
        assert result2.needs_monitor is False

    def test_recovery_log_appended(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "dead", "dead_pid": "999"}}
        recover_from_detection(state, detection)
        assert len(state.recovery_log) == 1
        assert "t1" in state.recovery_log[0]
        assert state.last_recovery_at != ""


def _write_gpu_progress(tmp_path, data):
    """Helper: write gpu_progress.json."""
    p = tmp_path / "exp" / "gpu_progress.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _read_gpu_progress(tmp_path):
    """Helper: read gpu_progress.json."""
    p = tmp_path / "exp" / "gpu_progress.json"
    return json.loads(p.read_text(encoding="utf-8"))


class TestStateSyncWithGpuProgress:
    """Task 4: State sync with gpu_progress.json."""

    def test_sync_completed_removes_from_gpu_running(self, tmp_path):
        # gpu_progress has t1 in running
        _write_gpu_progress(tmp_path, {
            "completed": [],
            "failed": [],
            "running": {"t1": {"gpu_ids": [0], "started_at": "2026-01-01"}},
            "timings": {},
        })
        # experiment_state has t1 as completed
        state = ExperimentState(tasks={
            "t1": {"status": "completed", "gpu_ids": [0]},
        })
        sync_to_gpu_progress(tmp_path, state)

        gp = _read_gpu_progress(tmp_path)
        assert "t1" not in gp.get("running", {})
        assert "t1" in gp["completed"]

    def test_sync_failed_removes_from_gpu_progress(self, tmp_path):
        _write_gpu_progress(tmp_path, {
            "completed": [],
            "failed": [],
            "running": {"t1": {"gpu_ids": [0], "started_at": "2026-01-01"}},
            "timings": {},
        })
        state = ExperimentState(tasks={
            "t1": {"status": "failed", "gpu_ids": [0]},
        })
        sync_to_gpu_progress(tmp_path, state)

        gp = _read_gpu_progress(tmp_path)
        assert "t1" not in gp.get("running", {})
        assert "t1" in gp["failed"]

    def test_sync_running_backfills_gpu_progress(self, tmp_path):
        # gpu_progress exists but t1 is NOT in running map
        _write_gpu_progress(tmp_path, {
            "completed": [],
            "failed": [],
            "running": {},
            "timings": {},
        })
        state = ExperimentState(tasks={
            "t1": {"status": "running", "gpu_ids": [2, 3], "registered_at": "2026-01-01"},
        })
        sync_to_gpu_progress(tmp_path, state)

        gp = _read_gpu_progress(tmp_path)
        assert "t1" in gp["running"]
        assert gp["running"]["t1"]["gpu_ids"] == [2, 3]

    def test_migrate_from_gpu_progress_only(self, tmp_path):
        _write_gpu_progress(tmp_path, {
            "completed": ["t1", "t2"],
            "failed": ["t3"],
            "running": {"t4": {"gpu_ids": [0, 1], "started_at": "2026-01-01T00:00:00"}},
            "timings": {},
        })
        state = migrate_from_gpu_progress(tmp_path)

        assert state.tasks["t1"]["status"] == "completed"
        assert state.tasks["t2"]["status"] == "completed"
        assert state.tasks["t3"]["status"] == "failed"
        assert state.tasks["t4"]["status"] == "running"
        assert state.tasks["t4"]["gpu_ids"] == [0, 1]


class TestMonitorProgressReading:
    def test_monitor_script_reads_progress(self):
        from sibyl.gpu_scheduler import experiment_monitor_script
        script = experiment_monitor_script(
            ssh_server="cs8000d",
            remote_project_dir="/home/user/project",
            task_ids=["task_a"],
        )
        assert "_PROGRESS.json" in script
        assert "progress" in script
