"""Tests for the Sibyl Dashboard web server."""

import json
import os
from pathlib import Path

import pytest

from sibyl.config import Config
from sibyl.dashboard.server import create_app
from sibyl.workspace import Workspace


@pytest.fixture(autouse=True)
def clear_dashboard_auth(monkeypatch):
    """Dashboard tests run with auth disabled unless a test opts in."""
    import sibyl.dashboard.server as srv

    monkeypatch.setattr(srv, "_AUTH_KEY", "")


@pytest.fixture
def workspace(tmp_path):
    """Create a runtime-ready test workspace."""
    ws_dir = tmp_path / "workspaces"
    ws = Workspace(ws_dir, "test-proj")
    proj = ws.root

    # status.json
    (proj / "status.json").write_text(json.dumps({
        "stage": "writing_sections",
        "started_at": 1000.0,
        "updated_at": 2000.0,
        "iteration": 2,
        "errors": [],
        "paused": False,
        "paused_at": None,
        "stop_requested": False,
        "stop_requested_at": None,
        "iteration_dirs": False,
        "stage_started_at": 1500.0,
    }))
    (proj / "topic.txt").write_text("Test research topic")
    (proj / "config.yaml").write_text("language: zh\ncodex_enabled: true\n")
    (proj / "spec.md").write_text("# 项目: test-proj\n\n## 研究主题\nTest research topic\n")
    (proj / ".git").mkdir(exist_ok=True)
    (proj / ".gitignore").write_text("*.pyc\n")

    # Create some artifact dirs and files
    for d in ["context", "idea", "plan", "exp", "writing", "logs"]:
        (proj / d).mkdir(exist_ok=True)

    (proj / "context" / "literature.md").write_text("# Literature\nSome papers...")
    (proj / "idea" / "proposal.md").write_text("# Proposal\nOur idea...")
    (proj / "writing" / "paper.md").write_text("# Paper\nFull paper content...")
    (proj / "plan" / "task_plan.json").write_text(json.dumps({"tasks": []}))
    (proj / "logs" / "events.jsonl").write_text(
        json.dumps({"ts": 1000.0, "event": "stage_start", "stage": "literature_search", "iteration": 0}) + "\n"
        + json.dumps({"ts": 1100.0, "event": "stage_end", "stage": "literature_search", "iteration": 0, "duration_sec": 100.0}) + "\n"
    )

    return ws_dir


@pytest.fixture
def client(workspace):
    """Create a Flask test client."""
    config = Config(workspaces_dir=workspace)
    app = create_app(config)
    app.config["TESTING"] = True
    return app.test_client()


class TestHealthEndpoint:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert "ts" in data


class TestProjectsEndpoint:
    def test_list_projects(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "test-proj"
        assert data[0]["stage"] == "writing_sections"
        assert data[0]["iteration"] == 2
        assert data[0]["topic"] == "Test research topic"
        assert data[0]["runtime_ready"] is True
        assert data[0]["migration_needed"] is False

    def test_list_empty_workspaces(self, tmp_path):
        config = Config(workspaces_dir=tmp_path / "empty")
        app = create_app(config)
        app.config["TESTING"] = True
        r = app.test_client().get("/api/projects")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_list_projects_does_not_materialize_runtime_scaffold(self, tmp_path):
        ws_dir = tmp_path / "workspaces"
        proj = ws_dir / "bare-proj"
        proj.mkdir(parents=True)
        (proj / "status.json").write_text(json.dumps({
            "stage": "planning",
            "started_at": 1000.0,
            "updated_at": 2000.0,
            "iteration": 1,
            "errors": [],
            "paused": False,
            "paused_at": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "iteration_dirs": False,
            "stage_started_at": 1500.0,
        }), encoding="utf-8")

        config = Config(workspaces_dir=ws_dir)
        app = create_app(config)
        app.config["TESTING"] = True

        r = app.test_client().get("/api/projects")
        assert r.status_code == 200
        data = r.get_json()
        assert data[0]["name"] == "bare-proj"
        assert not (proj / ".sibyl" / "system.json").exists()
        assert not (proj / "CLAUDE.md").exists()


class TestDashboardEndpoint:
    def test_dashboard(self, client):
        r = client.get("/api/projects/test-proj/dashboard")
        assert r.status_code == 200
        data = r.get_json()
        assert "status" in data
        assert "stages" in data
        assert "runtime" in data
        assert "stage_durations" in data
        assert "recent_events" in data
        assert data["status"]["stage"] == "writing_sections"
        assert data["runtime"]["runtime_ready"] is True
        assert len(data["stages"]) > 10  # pipeline stages present
        assert len(data["recent_events"]) == 2

    def test_dashboard_stage_durations(self, client):
        r = client.get("/api/projects/test-proj/dashboard")
        data = r.get_json()
        durations = data["stage_durations"]
        assert len(durations) == 1
        assert durations[0]["stage"] == "literature_search"
        assert durations[0]["duration_sec"] == 100.0

    def test_dashboard_404(self, client):
        r = client.get("/api/projects/nonexistent/dashboard")
        assert r.status_code == 404

    def test_dashboard_does_not_materialize_runtime_scaffold(self, tmp_path):
        ws_dir = tmp_path / "workspaces"
        proj = ws_dir / "bare-proj"
        logs = proj / "logs"
        proj.mkdir(parents=True)
        logs.mkdir()
        (proj / "status.json").write_text(json.dumps({
            "stage": "planning",
            "started_at": 1000.0,
            "updated_at": 2000.0,
            "iteration": 1,
            "errors": [],
            "paused": False,
            "paused_at": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "iteration_dirs": False,
            "stage_started_at": 1500.0,
        }), encoding="utf-8")
        (logs / "events.jsonl").write_text("", encoding="utf-8")

        config = Config(workspaces_dir=ws_dir)
        app = create_app(config)
        app.config["TESTING"] = True

        r = app.test_client().get("/api/projects/bare-proj/dashboard")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"]["name"] == "bare-proj"
        assert data["runtime"]["runtime_ready"] is False
        assert not (proj / ".sibyl" / "system.json").exists()
        assert not (proj / "CLAUDE.md").exists()


class TestFilesEndpoint:
    def test_list_root_files(self, client):
        r = client.get("/api/projects/test-proj/files")
        assert r.status_code == 200
        data = r.get_json()
        dir_names = {d["name"] for d in data["dirs"]}
        assert ".sibyl" in dir_names
        assert ".claude" not in dir_names
        assert "context" in dir_names
        assert "writing" in dir_names

    def test_list_runtime_subdir(self, client):
        r = client.get("/api/projects/test-proj/files?dir=.sibyl")
        assert r.status_code == 200
        data = r.get_json()
        dir_names = {d["name"] for d in data["dirs"]}
        file_names = {f["name"] for f in data["files"]}
        assert "project" in dir_names
        assert "system.json" in file_names

    def test_list_subdir(self, client):
        r = client.get("/api/projects/test-proj/files?dir=context")
        assert r.status_code == 200
        data = r.get_json()
        file_names = {f["name"] for f in data["files"]}
        assert "literature.md" in file_names

    def test_file_entry_has_metadata(self, client):
        r = client.get("/api/projects/test-proj/files?dir=context")
        data = r.get_json()
        lit_file = [f for f in data["files"] if f["name"] == "literature.md"][0]
        assert "size" in lit_file
        assert "ext" in lit_file
        assert lit_file["ext"] == ".md"


class TestFileContentEndpoint:
    def test_read_markdown(self, client):
        r = client.get("/api/projects/test-proj/file?path=context/literature.md")
        assert r.status_code == 200
        assert b"Literature" in r.data
        assert "charset=utf-8" in r.content_type

    def test_read_json(self, client):
        r = client.get("/api/projects/test-proj/file?path=plan/task_plan.json")
        assert r.status_code == 200
        assert b"tasks" in r.data

    def test_file_not_found(self, client):
        r = client.get("/api/projects/test-proj/file?path=nonexistent.md")
        assert r.status_code == 404

    def test_path_traversal_blocked(self, client):
        r = client.get("/api/projects/test-proj/file?path=../../pyproject.toml")
        assert r.status_code == 403

    def test_missing_path_param(self, client):
        r = client.get("/api/projects/test-proj/file")
        assert r.status_code == 400


class TestIterationsEndpoint:
    def test_no_iteration_dirs(self, client):
        r = client.get("/api/projects/test-proj/iterations")
        assert r.status_code == 200
        data = r.get_json()
        assert data["iterations"] == []
        assert data["current_iteration"] == 2

    def test_with_iteration_dirs(self, client, workspace):
        proj = workspace / "test-proj"
        (proj / "iter_001").mkdir()
        (proj / "iter_002").mkdir()
        r = client.get("/api/projects/test-proj/iterations")
        data = r.get_json()
        assert len(data["iterations"]) == 2
        assert data["iterations"][0]["number"] == 1
        assert data["iterations"][1]["number"] == 2


class TestIndexPage:
    def test_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Sibyl Dashboard" in r.data
        assert b"vue" in r.data.lower()


class TestOutputsEndpoint:
    def test_outputs_root_level(self, client):
        """Root-level proposal.md should appear in root outputs."""
        r = client.get("/api/projects/test-proj/outputs")
        assert r.status_code == 200
        data = r.get_json()
        assert data["root"]["idea"]["path"] == "idea/proposal.md"
        assert data["root"]["paper_md"]["path"] == "writing/paper.md"
        assert data["iterations"] == []

    def test_outputs_with_iterations(self, client, workspace):
        proj = workspace / "test-proj"
        iter1 = proj / "iter_001"
        (iter1 / "idea").mkdir(parents=True)
        (iter1 / "writing").mkdir(parents=True)
        (iter1 / "idea" / "proposal.md").write_text("# Idea 1")
        (iter1 / "writing" / "paper.md").write_text("# Paper 1")

        iter2 = proj / "iter_002"
        (iter2 / "idea").mkdir(parents=True)
        (iter2 / "idea" / "final_proposal.md").write_text("# Final Idea 2")

        r = client.get("/api/projects/test-proj/outputs")
        data = r.get_json()
        # Sorted descending by iteration number
        assert len(data["iterations"]) == 2
        assert data["iterations"][0]["number"] == 2
        assert data["iterations"][0]["idea"]["name"] == "final_proposal.md"
        assert "paper_md" not in data["iterations"][0]
        assert data["iterations"][1]["number"] == 1
        assert data["iterations"][1]["idea"]["path"] == "iter_001/idea/proposal.md"
        assert data["iterations"][1]["paper_md"]["path"] == "iter_001/writing/paper.md"

    def test_outputs_pdf(self, client, workspace):
        proj = workspace / "test-proj"
        latex = proj / "iter_001" / "writing" / "latex"
        latex.mkdir(parents=True)
        (proj / "iter_001" / "idea").mkdir(parents=True)
        (latex / "paper.pdf").write_bytes(b"%PDF-1.4 fake")

        r = client.get("/api/projects/test-proj/outputs")
        data = r.get_json()
        assert data["iterations"][0]["paper_pdf"]["name"] == "paper.pdf"


class TestAuth:
    def test_no_auth_key_all_open(self, client):
        """Without SIBYL_DASHBOARD_KEY, everything is accessible."""
        r = client.get("/api/auth/check")
        assert r.status_code == 200
        data = r.get_json()
        assert data["auth_required"] is False

    def test_auth_blocks_api(self, workspace, monkeypatch):
        """With SIBYL_DASHBOARD_KEY set, API returns 401."""
        import sibyl.dashboard.server as srv
        monkeypatch.setattr(srv, "_AUTH_KEY", "test-secret-123")

        config = Config(workspaces_dir=workspace)
        app = create_app(config)
        app.config["TESTING"] = True
        c = app.test_client()

        # Health and auth check are always accessible
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/auth/check").status_code == 200
        # Protected endpoint blocked
        assert c.get("/api/projects").status_code == 401

    def test_auth_login_sets_cookie(self, workspace, monkeypatch):
        """Correct key sets cookie and grants access."""
        import sibyl.dashboard.server as srv
        monkeypatch.setattr(srv, "_AUTH_KEY", "my-key")

        config = Config(workspaces_dir=workspace)
        app = create_app(config)
        app.config["TESTING"] = True
        c = app.test_client()

        # Login with correct key
        r = c.post("/api/auth", json={"key": "my-key"})
        assert r.status_code == 200
        # Cookie should be set in the response
        assert any("sibyl_auth" in h for h in r.headers.getlist("Set-Cookie"))

        # Now protected endpoints work (cookie forwarded automatically)
        assert c.get("/api/projects").status_code == 200

    def test_auth_login_wrong_key(self, workspace, monkeypatch):
        """Wrong key returns 403."""
        import sibyl.dashboard.server as srv
        monkeypatch.setattr(srv, "_AUTH_KEY", "correct-key")

        config = Config(workspaces_dir=workspace)
        app = create_app(config)
        app.config["TESTING"] = True
        c = app.test_client()

        r = c.post("/api/auth", json={"key": "wrong-key"})
        assert r.status_code == 403
        assert c.get("/api/projects").status_code == 401


class TestSystemEndpoint:
    def test_system_status(self, client):
        evolution_dir = Path(os.environ["SIBYL_STATE_DIR"]) / "evolution"
        (evolution_dir / "lessons").mkdir(parents=True, exist_ok=True)
        (evolution_dir / "lessons" / "planner.md").write_text("lesson", encoding="utf-8")
        (evolution_dir / "outcomes.jsonl").write_text(
            '{"project":"demo","stage":"reflection","issues":["x"],"score":5.0,"notes":"n"}\n',
            encoding="utf-8",
        )
        r = client.get("/api/system/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data["project_count"] == 1
        assert data["runtime_ready_count"] == 1
        assert data["migration_needed_count"] == 0
        assert data["skill_count"] > 0
        assert data["agent_count"] > 0
        assert data["tool_count"] == len(data["tool_names"])
        assert data["tools_dir"].endswith("/tools")
        assert data["workspaces_dir"].endswith("/workspaces")
        assert data["evolution_dir"] == str(evolution_dir.resolve())
        assert data["evolution_lesson_count"] == 1
        assert data["evolution_outcome_count"] == 1


class TestErrorHandling:
    def test_404_returns_json(self, client):
        r = client.get("/api/projects/bad/dashboard")
        assert r.status_code == 404
        data = r.get_json()
        assert "error" in data
