"""Tests for monitor API endpoints."""

import json

import pytest

from sibyl.config import Config
from sibyl.webui.app import create_webui_app


@pytest.fixture
def workspace(tmp_path):
    ws_dir = tmp_path / "workspaces"
    project = ws_dir / "proj-a"
    project.mkdir(parents=True)
    (project / "status.json").write_text(json.dumps({
        "stage": "experiment_cycle",
        "iteration": 1,
        "paused": False,
        "stop_requested": False,
        "started_at": 1000.0,
        "updated_at": 2000.0,
        "iteration_dirs": False,
        "stage_started_at": 1500.0,
        "errors": [],
    }), encoding="utf-8")
    (project / "topic.txt").write_text("attention sinks", encoding="utf-8")
    (project / "config.yaml").write_text("language: zh\n", encoding="utf-8")
    (project / "spec.md").write_text("# spec", encoding="utf-8")
    (project / ".git").mkdir()
    for name in ["logs", "exp", "context", "idea", "plan", "writing"]:
        (project / name).mkdir()
    (project / "logs" / "events.jsonl").write_text(
        json.dumps({
            "ts": 1000.0,
            "event": "agent_start",
            "agent": "sibyl-innovator",
            "stage": "experiment_cycle",
            "iteration": 1,
            "model_tier": "heavy",
        }) + "\n",
        encoding="utf-8",
    )
    (project / "sentinel_session.json").write_text(json.dumps({
        "session_id": "sess-123",
        "tmux_pane": "sibyl:0.0",
    }), encoding="utf-8")
    claude_dir = tmp_path / ".claude" / "projects" / "-tmp-workspaces"
    claude_dir.mkdir(parents=True)
    (claude_dir / "sess-123.jsonl").write_text(
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-17T12:00:00Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }) + "\n",
        encoding="utf-8",
    )
    return ws_dir


@pytest.fixture
def client(workspace, monkeypatch, tmp_path):
    import sibyl.dashboard.server as srv

    monkeypatch.setattr(srv, "_AUTH_KEY", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SIBYL_WEBUI_DISABLE_THREADS", "1")
    config = Config(workspaces_dir=workspace)
    app = create_webui_app(config)
    app.config["TESTING"] = True
    return app.test_client()


class TestGPUOverview:
    def test_empty(self, client):
        response = client.get("/api/monitor/gpu")
        assert response.status_code == 200
        assert "leases" in response.get_json()

    def test_with_leases(self, client, tmp_path, monkeypatch):
        lease_dir = tmp_path / "state" / "scheduler"
        lease_dir.mkdir(parents=True)
        (lease_dir / "gpu_leases.json").write_text(json.dumps({
            "leases": {"0": {"project_name": "proj-a", "task_ids": ["t1"]}},
            "updated_at": 1000.0,
        }), encoding="utf-8")
        monkeypatch.setenv("SIBYL_STATE_DIR", str(tmp_path / "state"))

        response = client.get("/api/monitor/gpu")

        assert "0" in response.get_json()["leases"]


class TestActiveAgents:
    def test_active_agents(self, client):
        response = client.get("/api/monitor/agents")
        payload = response.get_json()

        assert response.status_code == 200
        assert payload["agents"][0]["agent"] == "sibyl-innovator"
        assert payload["agents"][0]["project"] == "proj-a"


class TestCost:
    def test_cost_timeline(self, client):
        response = client.get("/api/monitor/cost")
        payload = response.get_json()

        assert response.status_code == 200
        assert payload["totals"]["input_tokens"] == 10
        assert len(payload["timeline"]) == 1


class TestInheritsDashboard:
    def test_projects(self, client):
        response = client.get("/api/projects")
        assert response.status_code == 200
        assert response.get_json()[0]["name"] == "proj-a"

    def test_conversation_history(self, client):
        response = client.get("/api/projects/proj-a/conversation?limit=10")
        payload = response.get_json()

        assert response.status_code == 200
        assert payload["entries"][0]["type"] == "assistant"
