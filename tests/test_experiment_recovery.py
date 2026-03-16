"""Tests for experiment recovery module."""

import json

from sibyl.experiment_recovery import (
    ExperimentState,
    load_experiment_state,
    save_experiment_state,
    register_task,
    register_dispatched_tasks,
    generate_detection_script,
    parse_detection_output,
    get_running_tasks,
    recover_from_detection,
    sync_to_gpu_progress,
    mark_tasks_completed,
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

    def test_register_dispatched_tasks_updates_both_state_files(self, tmp_path):
        task_gpu_map = {"train_baseline": [0, 1], "train_ablation": [2]}

        state = register_dispatched_tasks(
            tmp_path,
            task_gpu_map,
            "/remote/projects/demo",
        )

        assert sorted(state.tasks) == ["train_ablation", "train_baseline"]
        assert state.tasks["train_baseline"]["pid_file"] == "/remote/projects/demo/exp/results/train_baseline.pid"

        saved = load_experiment_state(tmp_path)
        assert sorted(saved.tasks) == ["train_ablation", "train_baseline"]

        gp = _read_gpu_progress(tmp_path)
        assert sorted(gp["running"]) == ["train_ablation", "train_baseline"]
        assert gp["running"]["train_baseline"]["gpu_ids"] == [0, 1]


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

    def test_recover_done_failed_retries_then_fails(self):
        # First failure: auto-retry resets to pending
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "done", "done_info": {"exit_code": 1}}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "pending"
        assert "t1" in result.retried
        assert state.tasks["t1"]["retry_count"] == 1

        # Second failure: retries exhausted, marked failed
        state.tasks["t1"]["status"] = "running"  # simulating re-dispatch
        result2 = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result2.recovered_failed

    def test_recover_done_failed_no_retry_when_disabled(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "done", "done_info": {"exit_code": 1}}}
        result = recover_from_detection(state, detection, max_retries=0)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result.recovered_failed

    def test_recover_running_keeps_running_with_progress(self):
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "running", "progress": {"epoch": 5}}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "running"
        assert "t1" in result.still_running
        assert result.progress["t1"] == {"epoch": 5}

    def test_recover_dead_retries_then_fails(self):
        # First failure: auto-retry resets to pending
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "dead", "dead_pid": "12345"}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "pending"
        assert "t1" in result.retried
        assert state.tasks["t1"]["retry_count"] == 1

        # Second failure: retries exhausted
        state.tasks["t1"]["status"] = "running"
        result2 = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result2.recovered_failed

    def test_recover_unknown_retries_then_fails(self):
        # First failure: auto-retry resets to pending
        state = _make_state_with_tasks(t1="running")
        detection = {"t1": {"detected_status": "unknown"}}
        result = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "pending"
        assert "t1" in result.retried
        assert state.tasks["t1"]["retry_count"] == 1

        # Second failure: retries exhausted
        state.tasks["t1"]["status"] = "running"
        result2 = recover_from_detection(state, detection)
        assert state.tasks["t1"]["status"] == "failed"
        assert "t1" in result2.recovered_failed

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


class TestMarkTasksCompleted:
    """Tests for daemon-driven mark_tasks_completed."""

    def test_marks_running_tasks_completed(self, tmp_path):
        state = _make_state_with_tasks(t1="running", t2="running", t3="completed")
        save_experiment_state(tmp_path, state)
        _write_gpu_progress(tmp_path, {
            "completed": ["t3"],
            "failed": [],
            "running": {
                "t1": {"gpu_ids": [0], "started_at": "2026-01-01"},
                "t2": {"gpu_ids": [1], "started_at": "2026-01-01"},
            },
            "timings": {},
        })

        result = mark_tasks_completed(tmp_path, ["t1", "t2"])
        assert result["completed_count"] == 2
        assert sorted(result["completed"]) == ["t1", "t2"]

        # Verify experiment_state.json updated
        updated = load_experiment_state(tmp_path)
        assert updated.tasks["t1"]["status"] == "completed"
        assert updated.tasks["t2"]["status"] == "completed"
        assert updated.tasks["t3"]["status"] == "completed"
        assert len(updated.recovery_log) == 2

        # Verify gpu_progress.json synced
        gp = _read_gpu_progress(tmp_path)
        assert "t1" in gp["completed"]
        assert "t2" in gp["completed"]
        assert "t1" not in gp.get("running", {})

    def test_marks_failed_tasks(self, tmp_path):
        state = _make_state_with_tasks(t1="running", t2="running")
        save_experiment_state(tmp_path, state)
        _write_gpu_progress(tmp_path, {
            "completed": [], "failed": [],
            "running": {
                "t1": {"gpu_ids": [0], "started_at": "2026-01-01"},
                "t2": {"gpu_ids": [1], "started_at": "2026-01-01"},
            },
            "timings": {},
        })

        result = mark_tasks_completed(tmp_path, ["t1"], failed_ids=["t2"])
        assert result["completed_count"] == 1
        assert result["failed_count"] == 1

        updated = load_experiment_state(tmp_path)
        assert updated.tasks["t1"]["status"] == "completed"
        assert updated.tasks["t2"]["status"] == "failed"

    def test_skips_already_completed_tasks(self, tmp_path):
        state = _make_state_with_tasks(t1="completed", t2="running")
        save_experiment_state(tmp_path, state)
        _write_gpu_progress(tmp_path, {
            "completed": ["t1"], "failed": [],
            "running": {"t2": {"gpu_ids": [0], "started_at": "2026-01-01"}},
            "timings": {},
        })

        result = mark_tasks_completed(tmp_path, ["t1", "t2"])
        assert result["completed_count"] == 1
        assert result["completed"] == ["t2"]

    def test_noop_when_empty(self, tmp_path):
        state = _make_state_with_tasks(t1="running")
        save_experiment_state(tmp_path, state)

        result = mark_tasks_completed(tmp_path, [])
        assert result["completed_count"] == 0
        assert result["failed_count"] == 0

        # State should not have been written (no log entries)
        updated = load_experiment_state(tmp_path)
        assert updated.recovery_log == []


class TestEndToEndRecovery:
    """Full pipeline: register → simulate interrupt → recover."""

    def test_full_recovery_pipeline(self, tmp_path):
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
            load_experiment_state, generate_detection_script,
            parse_detection_output, recover_from_detection,
            sync_to_gpu_progress,
        )
        from sibyl.gpu_scheduler import register_running_tasks, _load_progress

        # Phase 1: Register tasks (simulating orchestrator dispatch)
        state = ExperimentState()
        register_task(state, "train_baseline", gpu_ids=[0, 1], pid_file="/tmp/train_baseline.pid")
        register_task(state, "train_ablation", gpu_ids=[2], pid_file="/tmp/train_ablation.pid")
        register_task(state, "train_extra", gpu_ids=[3], pid_file="/tmp/train_extra.pid")
        save_experiment_state(tmp_path, state)
        register_running_tasks(tmp_path, {
            "train_baseline": [0, 1],
            "train_ablation": [2],
            "train_extra": [3],
        })

        # Phase 2: Generate detection script
        script = generate_detection_script("/home/user/project", [
            "train_baseline", "train_ablation", "train_extra",
        ])
        assert "train_baseline" in script

        # Phase 3: Simulate SSH output (as if script ran on server)
        ssh_output = (
            'DONE:train_baseline:{"status":"success","summary":"loss=0.1"}\n'
            'RUNNING:train_ablation:{"epoch":75,"total_epochs":100,"loss":0.25}\n'
            'DEAD:train_extra:99999\n'
        )

        # Phase 4: Parse and recover (first attempt — dead task gets auto-retry)
        detection = parse_detection_output(ssh_output)
        state = load_experiment_state(tmp_path)
        result = recover_from_detection(state, detection)

        assert result.recovered_completed == ["train_baseline"]
        assert result.still_running == ["train_ablation"]
        # train_extra: first failure → auto-retry (pending), not failed
        assert result.retried == ["train_extra"]
        assert result.recovered_failed == []
        assert result.needs_monitor is True
        assert result.progress["train_ablation"]["epoch"] == 75

        # Phase 5: Sync to gpu_progress
        save_experiment_state(tmp_path, state)
        sync_to_gpu_progress(tmp_path, state)

        completed, running_ids, _, _, _ = _load_progress(tmp_path)
        assert "train_baseline" in completed
        assert "train_ablation" in running_ids
        # train_extra is pending (retried), not running or failed
        assert "train_extra" not in running_ids

        # Phase 6: Verify state file — train_extra is pending for retry
        final = load_experiment_state(tmp_path)
        assert final.tasks["train_baseline"]["status"] == "completed"
        assert final.tasks["train_ablation"]["status"] == "running"
        assert final.tasks["train_extra"]["status"] == "pending"
        assert final.tasks["train_extra"]["retry_count"] == 1
        assert "process_disappeared" in final.tasks["train_extra"]["error_summary"]
        # 2 log entries: one for completed train_baseline, one for retried train_extra
        assert len(final.recovery_log) == 2

        # Phase 7: Simulate second failure after retry — now finally failed
        final.tasks["train_extra"]["status"] = "running"  # re-dispatched
        detection2 = parse_detection_output("DEAD:train_extra:88888\n")
        result2 = recover_from_detection(final, detection2)
        assert result2.recovered_failed == ["train_extra"]
        assert result2.retried == []
        assert final.tasks["train_extra"]["status"] == "failed"


class TestSyncCompletedFromProgress:
    def test_sync_completed_from_gpu_progress(self, tmp_path):
        """When gpu_progress marks a task completed but experiment_state still
        shows it running, loading experiment state should auto-sync."""
        from sibyl.experiment_recovery import (
            sync_completed_from_progress,
        )
        ws = tmp_path / "ws"
        (ws / "exp").mkdir(parents=True)

        # experiment_state: task_a running
        state = ExperimentState(tasks={"task_a": {"status": "running", "gpu_ids": [0]}})
        save_experiment_state(ws, state)

        # gpu_progress: task_a completed
        progress = {"completed": ["task_a"], "running": {}, "timings": {}}
        (ws / "exp" / "gpu_progress.json").write_text(json.dumps(progress))

        updated = sync_completed_from_progress(ws)
        assert updated.tasks["task_a"]["status"] == "completed"

    def test_sync_noop_when_already_synced(self, tmp_path):
        from sibyl.experiment_recovery import sync_completed_from_progress
        ws = tmp_path / "ws"
        (ws / "exp").mkdir(parents=True)

        state = ExperimentState(tasks={"task_a": {"status": "completed", "gpu_ids": [0]}})
        save_experiment_state(ws, state)

        progress = {"completed": ["task_a"], "running": {}, "timings": {}}
        (ws / "exp" / "gpu_progress.json").write_text(json.dumps(progress))

        updated = sync_completed_from_progress(ws)
        assert updated.tasks["task_a"]["status"] == "completed"


class TestExperimentStateLocking:
    def test_experiment_state_lock_exists(self):
        """experiment_state operations should use a file lock."""
        import inspect
        from sibyl.experiment_recovery import save_experiment_state
        source = inspect.getsource(save_experiment_state)
        assert "_experiment_state_lock" in source or "fcntl" in source or "_progress_lock" in source

    def test_load_experiment_state_lock_exists(self):
        """load_experiment_state should use a file lock."""
        import inspect
        from sibyl.experiment_recovery import load_experiment_state
        source = inspect.getsource(load_experiment_state)
        assert "_experiment_state_lock" in source or "fcntl" in source


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
