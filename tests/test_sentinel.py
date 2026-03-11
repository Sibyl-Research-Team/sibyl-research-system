"""Tests for Sentinel heartbeat, session persistence, and breadcrumbs."""
import json
import time
import io
import sys

import pytest

from sibyl.orchestrate import (
    _write_sentinel_heartbeat,
    _write_breadcrumb,
    cli_sentinel_session,
    cli_sentinel_config,
)


def _init_workspace(ws):
    ws.mkdir()
    (ws / "status.json").write_text(json.dumps({
        "stage": "experiment_cycle",
        "started_at": time.time(),
        "updated_at": time.time(),
        "iteration": 1,
        "errors": [],
        "paused": False,
        "paused_at": None,
        "stop_requested": False,
        "stop_requested_at": None,
        "iteration_dirs": False,
    }))
    (ws / "config.yaml").write_text(
        "topic: test\nssh_server: test\nremote_base: /tmp/test\n"
    )
    (ws / "exp").mkdir()
    return ws


@pytest.fixture
def workspace(tmp_path):
    """Minimal workspace for sentinel tests."""
    ws = tmp_path / "test_project"
    return _init_workspace(ws)


class TestHeartbeat:
    def test_creates_file(self, workspace):
        _write_sentinel_heartbeat(str(workspace), "experiment_cycle", "polling")
        hb_path = workspace / "sentinel_heartbeat.json"
        assert hb_path.exists()
        data = json.loads(hb_path.read_text())
        assert data["stage"] == "experiment_cycle"
        assert data["action"] == "polling"
        assert abs(data["ts"] - time.time()) < 5

    def test_updates_timestamp(self, workspace):
        _write_sentinel_heartbeat(str(workspace), "literature_search", "cli_next")
        hb1 = json.loads((workspace / "sentinel_heartbeat.json").read_text())
        time.sleep(0.05)
        _write_sentinel_heartbeat(str(workspace), "planning", "cli_record")
        hb2 = json.loads((workspace / "sentinel_heartbeat.json").read_text())
        assert hb2["ts"] >= hb1["ts"]
        assert hb2["stage"] == "planning"


class TestSessionPersistence:
    def test_write_session(self, workspace):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_session(str(workspace), "abc-123-def", "%1")
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        result = json.loads(output)
        assert result["status"] == "ok"
        assert result["tmux_pane"] == "%1"
        session_path = workspace / "sentinel_session.json"
        assert session_path.exists()
        data = json.loads(session_path.read_text())
        assert data["session_id"] == "abc-123-def"
        assert data["tmux_pane"] == "%1"
        assert data["ownership_conflict"] is False
        assert data["ralph_prompt_path"].endswith("/.claude/ralph-prompt.txt")
        assert "saved_at" in data

    def test_conflicting_workspace_claim_reports_ownership_conflict(self, workspace, tmp_path):
        other = _init_workspace(tmp_path / "other_project")

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_session(str(other), "shared-session", "%2")
        sys.stdout = io.StringIO()
        cli_sentinel_session(str(workspace), "shared-session", "%1")
        session_output = sys.stdout.getvalue()
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        config_output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        session_data = json.loads(session_output)
        config_data = json.loads(config_output)
        assert session_data["status"] == "conflict"
        assert session_data["ownership_conflict"] is True
        assert session_data["conflicts"][0]["workspace_path"] == str(other)
        assert "session_id" in session_data["conflicts"][0]["reasons"]
        assert config_data["ownership_conflict"] is True
        assert config_data["watchdog_allowed"] is False


class TestSentinelConfig:
    def test_returns_status(self, workspace):
        # Set up session and heartbeat
        (workspace / "sentinel_session.json").write_text(
            json.dumps({"session_id": "test-sess", "saved_at": time.time()})
        )
        (workspace / ".sibyl").mkdir(parents=True, exist_ok=True)
        (workspace / ".sibyl" / "recovery_state.json").write_text(json.dumps({
            "source": "cli_resume",
            "pending_sync_count": 1,
            "background_agent_required": True,
        }))
        _write_sentinel_heartbeat(str(workspace), "experiment_cycle", "cli_next")

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["session_id"] == "test-sess"
        assert data["stage"] == "experiment_cycle"
        assert data["paused"] is False
        assert data["stop_requested"] is False
        assert data["auto_resume_pending"] is False
        assert data["should_keep_running"] is True
        assert data["watchdog_allowed"] is True
        assert data["ralph_prompt_path"].endswith("/.claude/ralph-prompt.txt")
        assert "heartbeat" in data
        assert data["heartbeat"]["stage"] == "experiment_cycle"
        assert data["recovery"]["pending_sync_count"] == 1
        assert data["recovery"]["background_agent_required"] is True

    def test_detects_running_experiments(self, workspace):
        # Write experiment_state with running task
        (workspace / "exp" / "experiment_state.json").write_text(json.dumps({
            "tasks": {
                "task_a": {"status": "running", "gpu_ids": [0]},
                "task_b": {"status": "completed", "gpu_ids": [1]},
            }
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["has_running_experiments"] is True

    def test_no_running_experiments(self, workspace):
        (workspace / "exp" / "experiment_state.json").write_text(json.dumps({
            "tasks": {
                "task_a": {"status": "completed", "gpu_ids": [0]},
            }
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["has_running_experiments"] is False

    def test_detects_gpu_progress_running(self, workspace):
        # No experiment_state, but gpu_progress has running
        (workspace / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": [],
            "failed": [],
            "running": {"task_x": {"gpu_ids": [2], "started_at": "2026-03-09T10:00:00"}},
            "timings": {},
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["has_running_experiments"] is True

    def test_paused_project(self, workspace):
        (workspace / "status.json").write_text(json.dumps({
            "stage": "experiment_cycle",
            "started_at": time.time(),
            "updated_at": time.time(),
            "iteration": 1,
            "errors": [],
            "paused": True,
            "paused_at": time.time(),
            "stop_requested": False,
            "stop_requested_at": None,
            "iteration_dirs": False,
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["paused"] is True
        assert data["stop_requested"] is False
        assert data["auto_resume_pending"] is True
        assert data["should_keep_running"] is True

    def test_legacy_numeric_pause_schema_still_reports(self, workspace):
        (workspace / "status.json").write_text(json.dumps({
            "stage": "experiment_cycle",
            "started_at": time.time(),
            "updated_at": time.time(),
            "iteration": 1,
            "errors": [],
            "paused_at": time.time(),
            "stop_requested_at": 0.0,
            "iteration_dirs": False,
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["paused"] is True
        assert data["stop_requested"] is False
        assert data["auto_resume_pending"] is True
        assert data["should_keep_running"] is True

    def test_user_stop_is_reported(self, workspace):
        (workspace / "status.json").write_text(json.dumps({
            "stage": "experiment_cycle",
            "started_at": time.time(),
            "updated_at": time.time(),
            "iteration": 1,
            "errors": [],
            "paused": False,
            "paused_at": None,
            "stop_requested": True,
            "stop_requested_at": time.time(),
            "iteration_dirs": False,
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["paused"] is False
        assert data["stop_requested"] is True
        assert data["auto_resume_pending"] is False
        assert data["should_keep_running"] is False


class TestBreadcrumb:
    def test_write_from_action_dict(self, workspace):
        action = {
            "action_type": "experiment_wait",
            "stage": "experiment_cycle",
            "iteration": 2,
            "description": "实验运行中（3个任务）",
        }
        _write_breadcrumb(str(workspace), action_dict=action)
        bc = json.loads((workspace / "breadcrumb.json").read_text())
        assert bc["stage"] == "experiment_cycle"
        assert bc["action_type"] == "experiment_wait"
        assert bc["in_loop"] is True
        assert bc["loop_type"] == "experiment_wait"
        assert bc["iteration"] == 2
        assert abs(bc["ts"] - time.time()) < 5

    def test_write_from_completed(self, workspace):
        _write_breadcrumb(str(workspace), stage="planning", completed=True)
        bc = json.loads((workspace / "breadcrumb.json").read_text())
        assert bc["stage"] == "planning"
        assert bc["action_type"] == "completed"
        assert bc["in_loop"] is False
        assert bc["loop_type"] == ""

    def test_non_loop_action(self, workspace):
        action = {
            "action_type": "skill",
            "stage": "literature_search",
            "description": "文献调研",
        }
        _write_breadcrumb(str(workspace), action_dict=action)
        bc = json.loads((workspace / "breadcrumb.json").read_text())
        assert bc["in_loop"] is False
        assert bc["loop_type"] == ""

    def test_gpu_poll_is_loop(self, workspace):
        action = {"action_type": "gpu_poll", "stage": "experiment_cycle"}
        _write_breadcrumb(str(workspace), action_dict=action)
        bc = json.loads((workspace / "breadcrumb.json").read_text())
        assert bc["in_loop"] is True
        assert bc["loop_type"] == "gpu_poll"

    def test_description_truncated(self, workspace):
        action = {
            "action_type": "skill",
            "stage": "writing",
            "description": "x" * 500,
        }
        _write_breadcrumb(str(workspace), action_dict=action)
        bc = json.loads((workspace / "breadcrumb.json").read_text())
        assert len(bc["description"]) == 200
