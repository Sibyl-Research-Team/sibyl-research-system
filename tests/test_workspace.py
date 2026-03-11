"""Tests for sibyl.workspace module."""
import json
from pathlib import Path

import pytest

from sibyl.workspace import Workspace, WorkspaceStatus


class TestWorkspaceInit:
    def test_creates_directory_structure(self, tmp_path):
        ws = Workspace(tmp_path, "my-project")
        assert (ws.root / "idea").is_dir()
        assert (ws.root / "idea/perspectives").is_dir()
        assert (ws.root / "idea/debate").is_dir()
        assert (ws.root / "exp/code").is_dir()
        assert (ws.root / "exp/results/pilots").is_dir()
        assert (ws.root / "exp/results/full").is_dir()
        assert (ws.root / "writing/sections").is_dir()
        assert (ws.root / "writing/critique").is_dir()
        assert (ws.root / "writing/latex").is_dir()
        assert (ws.root / "context").is_dir()
        assert (ws.root / "codex").is_dir()
        assert (ws.root / "supervisor").is_dir()
        assert (ws.root / "critic").is_dir()
        assert (ws.root / "reflection").is_dir()
        assert (ws.root / "logs/iterations").is_dir()
        assert (ws.root / "lark_sync").is_dir()

    def test_creates_status_json(self, tmp_path):
        ws = Workspace(tmp_path, "my-project")
        status = ws.get_status()
        assert status.stage == "init"
        assert status.iteration == 0
        assert status.errors == []
        assert status.started_at > 0
        raw = json.loads((ws.root / "status.json").read_text(encoding="utf-8"))
        assert raw["paused"] is False
        assert raw["paused_at"] is None
        assert raw["stop_requested"] is False
        assert raw["stop_requested_at"] is None

    def test_idempotent_init(self, tmp_path):
        ws1 = Workspace(tmp_path, "proj")
        ws1.update_stage("planning")
        ws2 = Workspace(tmp_path, "proj")
        assert ws2.get_status().stage == "planning"

    def test_creates_runtime_scaffold(self, tmp_path):
        ws = Workspace(tmp_path, "runtime-proj")

        assert (ws.root / ".sibyl" / "system.json").exists()
        assert (ws.root / ".sibyl" / "project" / "MEMORY.md").exists()
        assert (ws.root / ".sibyl" / "project" / "prompt_overlays").is_dir()
        assert (ws.root / "CLAUDE.md").exists()
        assert "## Project Memory Layer" in (ws.root / "CLAUDE.md").read_text(encoding="utf-8")

        agents_link = ws.root / ".claude" / "agents"
        skills_link = ws.root / ".claude" / "skills"
        assert agents_link.is_symlink()
        assert skills_link.is_symlink()
        assert agents_link.resolve() == (Path(__file__).resolve().parents[1] / ".claude" / "agents")
        assert skills_link.resolve() == (Path(__file__).resolve().parents[1] / ".claude" / "skills")


class TestWorkspaceOpenExisting:
    def test_open_existing_does_not_materialize_runtime_scaffold(self, tmp_path):
        proj = tmp_path / "bare-proj"
        proj.mkdir()
        (proj / "status.json").write_text(json.dumps({
            "stage": "planning",
            "started_at": 1.0,
            "updated_at": 2.0,
            "iteration": 1,
            "errors": [],
            "paused": False,
            "paused_at": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "iteration_dirs": False,
            "stage_started_at": 1.5,
        }), encoding="utf-8")

        ws = Workspace.open_existing(tmp_path, "bare-proj")
        metadata = ws.get_project_metadata()

        assert metadata["stage"] == "planning"
        assert not (proj / ".sibyl" / "system.json").exists()
        assert not (proj / "CLAUDE.md").exists()
        assert not (proj / ".claude").exists()

    def test_open_existing_infers_iteration_dirs_from_status(self, tmp_path):
        proj = tmp_path / "iter-proj"
        current = proj / "current"
        iter_dir = proj / "iter_002"
        iter_dir.mkdir(parents=True)
        current.symlink_to(iter_dir.name)
        (proj / "status.json").write_text(json.dumps({
            "stage": "experiment_cycle",
            "started_at": 1.0,
            "updated_at": 2.0,
            "iteration": 2,
            "errors": [],
            "paused": False,
            "paused_at": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "iteration_dirs": True,
            "stage_started_at": 1.5,
        }), encoding="utf-8")

        ws = Workspace.open_existing(tmp_path, "iter-proj")

        assert ws.active_root == current

    def test_open_existing_requires_status_json(self, tmp_path):
        proj = tmp_path / "missing-status"
        proj.mkdir()

        with pytest.raises(FileNotFoundError, match="status.json"):
            Workspace.open_existing(tmp_path, "missing-status")


class TestWorkspaceStatus:
    def test_update_stage(self, tmp_ws):
        tmp_ws.update_stage("literature_search")
        assert tmp_ws.get_status().stage == "literature_search"

    def test_update_iteration(self, tmp_ws):
        tmp_ws.update_iteration(3)
        assert tmp_ws.get_status().iteration == 3

    def test_update_stage_and_iteration_atomic(self, tmp_ws):
        tmp_ws.update_stage_and_iteration("literature_search", 5)
        s = tmp_ws.get_status()
        assert s.stage == "literature_search"
        assert s.iteration == 5

    def test_add_error(self, tmp_ws):
        tmp_ws.add_error("something broke")
        status = tmp_ws.get_status()
        assert len(status.errors) == 1
        assert status.errors[0]["error"] == "something broke"
        assert "time" in status.errors[0]

    def test_multiple_errors(self, tmp_ws):
        tmp_ws.add_error("err1")
        tmp_ws.add_error("err2")
        assert len(tmp_ws.get_status().errors) == 2

    def test_errors_not_shared_between_instances(self):
        """Regression test: errors field must use default_factory, not mutable default."""
        s1 = WorkspaceStatus()
        s2 = WorkspaceStatus()
        s1.errors.append({"error": "test"})
        assert s2.errors == []

    def test_corrupted_status_recovery(self, tmp_ws):
        (tmp_ws.root / "status.json").write_text("CORRUPT{{{", encoding="utf-8")
        status = tmp_ws.get_status()
        assert status.stage == "init"
        assert status.started_at > 0

    def test_corrupted_status_recovers_from_tmp(self, tmp_ws):
        tmp_ws.update_stage("planning")
        # Simulate: .tmp is valid, main is corrupted
        import shutil
        shutil.copy(tmp_ws.root / "status.json", tmp_ws.root / "status.json.tmp")
        (tmp_ws.root / "status.json").write_text("BAD", encoding="utf-8")
        status = tmp_ws.get_status()
        assert status.stage == "planning"

    def test_unknown_fields_ignored(self, tmp_ws):
        data = {"stage": "planning", "iteration": 1, "started_at": 1.0,
                "updated_at": 1.0, "errors": [], "paused": False,
                "paused_at": None, "stop_requested": False,
                "stop_requested_at": None,
                "future_field": "should_be_ignored"}
        (tmp_ws.root / "status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        status = tmp_ws.get_status()
        assert status.stage == "planning"
        assert status.paused is False
        assert status.stop_requested is False

    def test_legacy_numeric_pause_schema_still_loads(self, tmp_ws):
        data = {"stage": "planning", "iteration": 1, "started_at": 1.0,
                "updated_at": 1.0, "errors": [], "paused_at": 123.0,
                "stop_requested_at": 0.0, "iteration_dirs": False}
        (tmp_ws.root / "status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        status = tmp_ws.get_status()
        assert status.paused is True
        assert status.paused_at == 123.0
        assert status.stop_requested is False
        assert status.stop_requested_at is None

    def test_legacy_numeric_stop_schema_still_loads(self, tmp_ws):
        data = {"stage": "planning", "iteration": 1, "started_at": 1.0,
                "updated_at": 1.0, "errors": [], "paused_at": 222.0,
                "stop_requested_at": 333.0, "iteration_dirs": False}
        (tmp_ws.root / "status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        status = tmp_ws.get_status()
        assert status.paused is False
        assert status.paused_at is None
        assert status.stop_requested is True
        assert status.stop_requested_at == 333.0


class TestWorkspacePause:
    def test_pause_and_resume(self, tmp_ws):
        assert not tmp_ws.is_paused()
        assert not tmp_ws.is_stop_requested()
        tmp_ws.pause("rate_limit")
        assert tmp_ws.is_paused()
        assert not tmp_ws.is_stop_requested()
        status = tmp_ws.get_status()
        assert status.paused is True
        assert status.paused_at is not None
        assert status.stop_requested is False
        assert status.stop_requested_at is None
        tmp_ws.resume()
        resumed = tmp_ws.get_status()
        assert not tmp_ws.is_paused()
        assert not tmp_ws.is_stop_requested()
        assert resumed.paused is False
        assert resumed.paused_at is None
        assert resumed.stop_requested is False
        assert resumed.stop_requested_at is None

    def test_user_stop_sets_stop_requested(self, tmp_ws):
        tmp_ws.pause("user_stop")
        status = tmp_ws.get_status()
        assert status.paused is False
        assert status.paused_at is None
        assert status.stop_requested is True
        assert status.stop_requested_at is not None
        assert not tmp_ws.is_paused()
        assert tmp_ws.is_stop_requested()
        tmp_ws.resume()
        assert not tmp_ws.is_stop_requested()

    def test_non_stop_pause_clears_previous_stop_marker(self, tmp_ws):
        tmp_ws.pause("user_stop")
        assert tmp_ws.is_stop_requested()
        tmp_ws.pause("rate_limit")
        assert not tmp_ws.is_stop_requested()
        assert tmp_ws.is_paused()

    def test_pause_writes_new_schema_to_disk(self, tmp_ws):
        tmp_ws.pause("rate_limit")
        raw = json.loads((tmp_ws.root / "status.json").read_text(encoding="utf-8"))
        assert raw["paused"] is True
        assert raw["paused_at"] is not None
        assert raw["stop_requested"] is False
        assert raw["stop_requested_at"] is None

    def test_pause_writes_log(self, tmp_ws):
        tmp_ws.update_stage("planning")
        tmp_ws.pause("test_reason")
        log = tmp_ws.read_file("logs/pause_log.jsonl")
        assert log is not None
        entry = json.loads(log.strip())
        assert entry["reason"] == "test_reason"
        assert entry["stage"] == "planning"


class TestWorkspaceFileIO:
    def test_write_and_read(self, tmp_ws):
        tmp_ws.write_file("test/hello.txt", "world")
        assert tmp_ws.read_file("test/hello.txt") == "world"

    def test_read_nonexistent(self, tmp_ws):
        assert tmp_ws.read_file("does/not/exist.txt") is None

    def test_write_creates_parents(self, tmp_ws):
        tmp_ws.write_file("deep/nested/dir/file.txt", "content")
        assert tmp_ws.read_file("deep/nested/dir/file.txt") == "content"

    def test_path_traversal_blocked(self, tmp_ws):
        with pytest.raises(ValueError, match="Path traversal"):
            tmp_ws.write_file("../../etc/passwd", "hack")

    def test_path_traversal_blocked_on_read(self, tmp_ws):
        with pytest.raises(ValueError, match="Path traversal"):
            tmp_ws.read_file("../../../etc/passwd")

    def test_write_and_read_json(self, tmp_ws):
        data = {"key": "value", "list": [1, 2, 3]}
        tmp_ws.write_json("data.json", data)
        assert tmp_ws.read_json("data.json") == data

    def test_read_json_corrupt(self, tmp_ws):
        tmp_ws.write_file("bad.json", "not json{{{")
        assert tmp_ws.read_json("bad.json") is None

    def test_list_files(self, tmp_ws):
        tmp_ws.write_file("a.txt", "a")
        tmp_ws.write_file("sub/b.txt", "b")
        files = tmp_ws.list_files()
        assert any("a.txt" in f for f in files)
        assert any("b.txt" in f for f in files)

    def test_list_files_filters_symlinks(self, tmp_ws):
        tmp_ws.write_file("real.txt", "content")
        link = tmp_ws.root / "link.txt"
        link.symlink_to(tmp_ws.root / "real.txt")
        files = tmp_ws.list_files()
        assert not any("link.txt" in f for f in files)
        assert any("real.txt" in f for f in files)


class TestWorkspaceArchive:
    def test_archive_copies_artifacts(self, tmp_ws):
        tmp_ws.write_file("idea/proposal.md", "proposal")
        tmp_ws.write_file("writing/paper.md", "paper")
        tmp_ws.write_file("supervisor/review.md", "review")
        tmp_ws.archive_iteration(1)
        archive = tmp_ws.root / "logs/iterations/iter_001"
        assert (archive / "idea" / "proposal.md").exists()
        assert (archive / "writing" / "paper.md").exists()
        assert (archive / "supervisor" / "review.md").exists()

    def test_archive_preserves_originals(self, tmp_ws):
        tmp_ws.write_file("idea/proposal.md", "proposal")
        tmp_ws.archive_iteration(1)
        assert tmp_ws.read_file("idea/proposal.md") == "proposal"

    def test_archive_overwrites_previous(self, tmp_ws):
        tmp_ws.write_file("idea/proposal.md", "v1")
        tmp_ws.archive_iteration(1)
        tmp_ws.write_file("idea/proposal.md", "v2")
        tmp_ws.archive_iteration(1)
        archive = tmp_ws.root / "logs/iterations/iter_001/idea/proposal.md"
        assert archive.read_text(encoding="utf-8") == "v2"


class TestWorkspaceGit:
    def test_git_init(self, tmp_ws):
        tmp_ws.git_init()
        assert (tmp_ws.root / ".git").is_dir()
        assert (tmp_ws.root / ".gitignore").exists()

    def test_git_init_idempotent(self, tmp_ws):
        tmp_ws.git_init()
        tmp_ws.git_init()  # should not error
        assert (tmp_ws.root / ".git").is_dir()

    def test_git_commit(self, tmp_ws):
        tmp_ws.git_init()
        tmp_ws.write_file("test.txt", "hello")
        tmp_ws.git_commit("test commit")
        # Verify commit exists
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=tmp_ws.root, capture_output=True, text=True
        )
        assert "test commit" in result.stdout

    def test_git_commit_noop_when_clean(self, tmp_ws):
        tmp_ws.git_init()
        tmp_ws.git_commit("should be noop")  # no staged changes


class TestIterationDirs:
    def test_iteration_dirs_init(self, tmp_path):
        ws = Workspace(tmp_path, "iter-proj", iteration_dirs=True)
        assert (ws.root / "iter_001").is_dir()
        assert (ws.root / "current").is_symlink()
        assert (ws.root / "current").resolve() == (ws.root / "iter_001").resolve()
        assert (ws.root / "shared").is_dir()
        # Standard dirs should be inside iter_001
        assert (ws.root / "iter_001" / "idea").is_dir()
        assert (ws.root / "iter_001" / "exp" / "code").is_dir()
        # Status should record iteration_dirs=True
        status = ws.get_status()
        assert status.iteration_dirs is True

    def test_start_new_iteration(self, tmp_path):
        ws = Workspace(tmp_path, "iter-proj", iteration_dirs=True)
        # Put shared files
        (ws.root / "shared" / "literature.md").write_text("lit content", encoding="utf-8")
        (ws.root / "shared" / "references.json").write_text("[]", encoding="utf-8")
        # Put lessons in iter_001
        (ws.root / "iter_001" / "reflection" / "lessons_learned.md").write_text(
            "lesson 1", encoding="utf-8"
        )
        ws.start_new_iteration(2)
        # iter_002 should exist
        assert (ws.root / "iter_002").is_dir()
        assert (ws.root / "iter_002" / "idea").is_dir()
        # current should point to iter_002
        assert (ws.root / "current").resolve() == (ws.root / "iter_002").resolve()
        # Shared files should be copied
        assert (ws.root / "iter_002" / "context" / "literature.md").read_text(encoding="utf-8") == "lit content"
        assert (ws.root / "iter_002" / "context" / "references.json").read_text(encoding="utf-8") == "[]"
        # Lessons should be copied from prev iteration
        assert (ws.root / "iter_002" / "reflection" / "lessons_learned.md").read_text(encoding="utf-8") == "lesson 1"

    def test_reopen_preserves_current_iteration_target(self, tmp_path):
        ws = Workspace(tmp_path, "iter-proj", iteration_dirs=True)
        ws.start_new_iteration(2)
        ws.update_iteration(2)

        reopened = Workspace(tmp_path, "iter-proj", iteration_dirs=True)

        assert (reopened.root / "current").is_symlink()
        assert (reopened.root / "current").resolve() == (reopened.root / "iter_002").resolve()
        assert reopened.active_root.resolve() == (reopened.root / "iter_002").resolve()

    def test_archive_iteration_dirs_mode(self, tmp_path):
        ws = Workspace(tmp_path, "iter-proj", iteration_dirs=True)
        # Set iteration_dirs in status
        status = ws.get_status()
        status.iteration_dirs = True
        ws._save_status(status)
        # Create some context files in iter_001
        (ws.root / "iter_001" / "context" / "literature.md").write_text("updated lit", encoding="utf-8")
        ws.archive_iteration(1)
        # In iteration_dirs mode, shared files should be synced back
        assert (ws.root / "shared" / "literature.md").read_text(encoding="utf-8") == "updated lit"
        # No copytree to logs/iterations/ in iteration_dirs mode
        assert not (ws.root / "logs" / "iterations" / "iter_001" / "idea").exists()

    def test_backward_compat(self, tmp_path):
        """iteration_dirs=False should behave exactly like before."""
        ws = Workspace(tmp_path, "classic-proj")
        # Standard dirs at root level
        assert (ws.root / "idea").is_dir()
        assert not (ws.root / "iter_001").exists()
        assert not (ws.root / "current").exists()
        # shared/ is always created
        assert (ws.root / "shared").is_dir()
        # Status should have iteration_dirs=False
        assert ws.get_status().iteration_dirs is False
        # Archive should use classic copytree
        ws.write_file("idea/proposal.md", "proposal")
        ws.archive_iteration(1)
        assert (ws.root / "logs" / "iterations" / "iter_001" / "idea" / "proposal.md").exists()


class TestProjectMetadata:
    def test_metadata_fields(self, tmp_ws):
        tmp_ws.update_stage("planning")
        tmp_ws.update_iteration(2)
        tmp_ws.write_file("idea/proposal.md", "proposal")
        tmp_ws.write_file("writing/paper.md", "paper")
        meta = tmp_ws.get_project_metadata()
        assert meta["name"] == "test-proj"
        assert meta["stage"] == "planning"
        assert meta["iteration"] == 2
        assert meta["has_proposal"] is True
        assert meta["has_paper"] is True
