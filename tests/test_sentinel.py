"""Tests for Sentinel heartbeat and session persistence."""
import json
import time
import io
import sys
from pathlib import Path

import pytest

from sibyl.orchestrate import (
    _write_sentinel_heartbeat,
    cli_sentinel_session,
    cli_sentinel_config,
)


@pytest.fixture
def workspace(tmp_path):
    """Minimal workspace for sentinel tests."""
    ws = tmp_path / "test_project"
    ws.mkdir()
    (ws / "status.json").write_text(json.dumps({
        "stage": "experiment_cycle",
        "started_at": time.time(),
        "updated_at": time.time(),
        "iteration": 1,
        "errors": [],
        "paused_at": 0.0,
        "iteration_dirs": False,
    }))
    (ws / "config.yaml").write_text(
        "topic: test\nssh_server: test\nremote_base: /tmp/test\n"
    )
    (ws / "exp").mkdir()
    return ws


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
        cli_sentinel_session(str(workspace), "abc-123-def")
        sys.stdout = old_stdout

        session_path = workspace / "sentinel_session.json"
        assert session_path.exists()
        data = json.loads(session_path.read_text())
        assert data["session_id"] == "abc-123-def"
        assert "saved_at" in data


class TestSentinelConfig:
    def test_returns_status(self, workspace):
        # Set up session and heartbeat
        (workspace / "sentinel_session.json").write_text(
            json.dumps({"session_id": "test-sess", "saved_at": time.time()})
        )
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
        assert "heartbeat" in data
        assert data["heartbeat"]["stage"] == "experiment_cycle"

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
            "paused_at": time.time(),
            "iteration_dirs": False,
        }))

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cli_sentinel_config(str(workspace))
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        data = json.loads(output)
        assert data["paused"] is True
