"""Tests for session registry."""

import json

import pytest

from sibyl.webui.session_registry import SessionRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    claude_dir = tmp_path / ".claude"
    (claude_dir / "projects" / "-tmp-workspaces").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    return SessionRegistry(ws_dir)


class TestSessionRegistry:
    def test_discover_from_sentinel(self, registry, tmp_path):
        project = tmp_path / "workspaces" / "proj-a"
        project.mkdir()
        (project / "status.json").write_text('{"stage": "planning"}', encoding="utf-8")
        (project / "sentinel_session.json").write_text(json.dumps({
            "session_id": "sess-abc-123",
            "tmux_pane": "sibyl:0.0",
        }), encoding="utf-8")

        info = registry.get_session("proj-a")

        assert info is not None
        assert info["session_id"] == "sess-abc-123"
        assert info["tmux_pane"] == "sibyl:0.0"

    def test_legacy_key_is_supported(self, registry, tmp_path):
        project = tmp_path / "workspaces" / "proj-legacy"
        project.mkdir()
        (project / "status.json").write_text('{"stage": "planning"}', encoding="utf-8")
        (project / "sentinel_session.json").write_text(json.dumps({
            "claude_session_id": "sess-legacy",
            "tmux_pane": "sibyl:0.1",
        }), encoding="utf-8")

        info = registry.get_session("proj-legacy")

        assert info is not None
        assert info["session_id"] == "sess-legacy"

    def test_find_conversation_jsonl(self, registry, tmp_path):
        claude_proj_dir = tmp_path / ".claude" / "projects" / "-tmp-workspaces"
        (claude_proj_dir / "sess-abc-123.jsonl").write_text('{"type":"system"}\n', encoding="utf-8")
        project = tmp_path / "workspaces" / "proj-a"
        project.mkdir()
        (project / "status.json").write_text('{"stage": "planning"}', encoding="utf-8")
        (project / "sentinel_session.json").write_text(json.dumps({
            "session_id": "sess-abc-123",
            "tmux_pane": "sibyl:0.0",
        }), encoding="utf-8")

        info = registry.get_session("proj-a")

        assert info["conversation_jsonl"] is not None
        assert info["conversation_jsonl"].endswith(".jsonl")

    def test_list_sessions(self, registry, tmp_path):
        project = tmp_path / "workspaces" / "proj-a"
        project.mkdir()
        (project / "status.json").write_text('{"stage": "planning"}', encoding="utf-8")
        (project / "sentinel_session.json").write_text(json.dumps({
            "session_id": "sess-1",
            "tmux_pane": "s:0.0",
        }), encoding="utf-8")

        sessions = registry.list_sessions()

        assert len(sessions) == 1
        assert sessions[0]["project"] == "proj-a"
