"""Tests for workspace state watcher helpers."""

import json

import pytest

from sibyl.webui.state_watcher import categorize_change, read_state_snapshot


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspaces" / "proj-a"
    ws.mkdir(parents=True)
    (ws / "logs").mkdir()
    (ws / "exp").mkdir()
    (ws / "status.json").write_text(
        json.dumps(
            {
                "stage": "planning",
                "iteration": 1,
                "paused": False,
                "stop_requested": False,
            }
        ),
        encoding="utf-8",
    )
    (ws / "logs" / "events.jsonl").write_text("", encoding="utf-8")
    (ws / "exp" / "gpu_progress.json").write_text(
        json.dumps({"running": {"task-1": {"gpu_ids": [0]}}}),
        encoding="utf-8",
    )
    return ws


class TestCategorizeChange:
    def test_status(self):
        assert categorize_change("/ws/proj/status.json") == "status_changed"

    def test_events(self):
        assert categorize_change("/ws/proj/logs/events.jsonl") == "event_logged"

    def test_gpu(self):
        assert categorize_change("/ws/proj/exp/gpu_progress.json") == "experiment_updated"

    def test_experiment(self):
        assert categorize_change("/ws/proj/exp/experiment_state.json") == "experiment_updated"

    def test_unknown(self):
        assert categorize_change("/ws/proj/other.txt") is None


class TestReadStateSnapshot:
    def test_reads_status(self, workspace):
        snapshot = read_state_snapshot(workspace)

        assert snapshot["status"]["stage"] == "planning"
        assert "task-1" in snapshot["gpu_progress"]["running"]

    def test_handles_missing(self, tmp_path):
        ws = tmp_path / "empty"
        ws.mkdir()
        (ws / "status.json").write_text('{"stage": "init"}', encoding="utf-8")

        snapshot = read_state_snapshot(ws)

        assert snapshot["status"]["stage"] == "init"
        assert snapshot["gpu_progress"] == {}
