"""Tests for control API endpoints."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sibyl.config import Config
from sibyl.webui.app import create_webui_app


@pytest.fixture
def workspace(tmp_path):
    ws_dir = tmp_path / "workspaces"
    project = ws_dir / "proj-a"
    project.mkdir(parents=True)
    (project / "status.json").write_text(json.dumps({
        "stage": "planning",
        "iteration": 1,
        "paused": False,
        "stop_requested": False,
        "started_at": 1000.0,
        "updated_at": 2000.0,
        "iteration_dirs": False,
        "stage_started_at": 1500.0,
        "errors": [],
    }), encoding="utf-8")
    (project / "topic.txt").write_text("test topic", encoding="utf-8")
    (project / "config.yaml").write_text("language: zh\n", encoding="utf-8")
    (project / "spec.md").write_text("# spec", encoding="utf-8")
    (project / ".git").mkdir()
    (project / "sentinel_session.json").write_text(json.dumps({
        "session_id": "sess-123",
        "tmux_pane": "sibyl:0.0",
    }), encoding="utf-8")
    for name in ["logs", "context", "idea", "plan", "exp", "writing"]:
        (project / name).mkdir()
    (project / "logs" / "events.jsonl").write_text("", encoding="utf-8")
    return ws_dir


@pytest.fixture
def client(workspace, monkeypatch):
    import sibyl.dashboard.server as srv

    monkeypatch.setattr(srv, "_AUTH_KEY", "")
    monkeypatch.setenv("SIBYL_WEBUI_DISABLE_THREADS", "1")
    config = Config(workspaces_dir=workspace)
    app = create_webui_app(config)
    app.config["TESTING"] = True
    return app.test_client()


class TestSendMessage:
    @patch("sibyl.webui.control_api.MessageInjector")
    def test_success(self, mock_injector, client):
        mock_injector.return_value.send.return_value = {"ok": True}

        response = client.post("/api/projects/proj-a/send-message", json={"text": "pivot"})

        assert response.status_code == 200
        assert response.get_json()["ok"] is True

    def test_no_session(self, client, workspace):
        (workspace / "proj-a" / "sentinel_session.json").unlink()

        response = client.post("/api/projects/proj-a/send-message", json={"text": "hi"})

        assert response.status_code == 409

    def test_missing_text(self, client):
        response = client.post("/api/projects/proj-a/send-message", json={})
        assert response.status_code == 400


class TestStop:
    @patch("sibyl.webui.control_api.MessageInjector")
    def test_prefers_tmux_injection(self, mock_injector, client):
        mock_injector.return_value.send.return_value = {"ok": True}

        response = client.post("/api/projects/proj-a/stop")

        assert response.status_code == 200
        sent = mock_injector.return_value.send.call_args[0][1]
        assert sent == "/sibyl-research:stop proj-a"

    @patch("sibyl.webui.control_api.cli_pause")
    def test_fallback_without_session(self, mock_pause, client, workspace):
        (workspace / "proj-a" / "sentinel_session.json").unlink()
        mock_pause.return_value = {"status": "stopped", "stage": "planning"}

        response = client.post("/api/projects/proj-a/stop")

        assert response.status_code == 200
        assert (workspace / "proj-a" / "sentinel_stop.json").exists()
        mock_pause.assert_called_once()


class TestResume:
    @patch("sibyl.webui.control_api.MessageInjector")
    def test_prefers_tmux_injection(self, mock_injector, client):
        mock_injector.return_value.send.return_value = {"ok": True}

        response = client.post("/api/projects/proj-a/resume")

        assert response.status_code == 200
        sent = mock_injector.return_value.send.call_args[0][1]
        assert sent == "/sibyl-research:resume proj-a"

    @patch("sibyl.webui.control_api.cli_resume")
    def test_fallback_without_session(self, mock_resume, client, workspace):
        (workspace / "proj-a" / "sentinel_session.json").unlink()
        (workspace / "proj-a" / "sentinel_stop.json").write_text('{"stop": true}', encoding="utf-8")
        mock_resume.return_value = {"status": "resumed", "stage": "planning"}

        response = client.post("/api/projects/proj-a/resume")

        assert response.status_code == 200
        assert not (workspace / "proj-a" / "sentinel_stop.json").exists()
        mock_resume.assert_called_once()


class TestConfigEndpoints:
    def test_get_config(self, client):
        response = client.get("/api/projects/proj-a/config")

        assert response.status_code == 200
        assert "language: zh" in response.get_json()["content"]

    def test_update_config(self, client, workspace):
        response = client.put("/api/projects/proj-a/config", json={"content": "language: en\nmax_gpus: 2\n"})

        assert response.status_code == 200
        saved = (workspace / "proj-a" / "config.yaml").read_text(encoding="utf-8")
        assert "language: en" in saved

    def test_invalid_config(self, client):
        response = client.put("/api/projects/proj-a/config", json={"content": "compute_backend: kubernetes\n"})
        assert response.status_code == 400


class TestTerminalInfo:
    def test_terminal_not_running(self, client):
        response = client.get("/api/projects/proj-a/terminal-info")
        payload = response.get_json()

        assert response.status_code == 200
        assert payload["running"] is False

    def test_terminal_running(self, client):
        meta_path = Path("/tmp/sibyl_ttyd_proj-a.json")
        try:
            meta_path.write_text(json.dumps({
                "project": "proj-a",
                "port": 7681,
                "pid": 999999,
                "url": "http://127.0.0.1:7681",
            }), encoding="utf-8")

            with patch("sibyl.webui.control_api._pid_is_alive", return_value=True):
                response = client.get("/api/projects/proj-a/terminal-info")

            payload = response.get_json()
            assert payload["running"] is True
            assert payload["url"] == "http://127.0.0.1:7681"
        finally:
            meta_path.unlink(missing_ok=True)

    def test_terminal_uses_custom_state_dir(self, client, tmp_path, monkeypatch):
        state_dir = tmp_path / "ttyd-state"
        state_dir.mkdir()
        monkeypatch.setenv("SIBYL_TTYD_STATE_DIR", str(state_dir))
        meta_path = state_dir / "sibyl_ttyd_proj-a.json"
        meta_path.write_text(json.dumps({
            "project": "proj-a",
            "port": 7682,
            "pid": 424242,
            "url": "http://127.0.0.1:7682",
        }), encoding="utf-8")

        with patch("sibyl.webui.control_api._pid_is_alive", return_value=True):
            response = client.get("/api/projects/proj-a/terminal-info")

        payload = response.get_json()
        assert response.status_code == 200
        assert payload["running"] is True
        assert payload["url"] == "http://127.0.0.1:7682"
