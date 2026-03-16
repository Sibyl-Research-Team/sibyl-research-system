"""Tests for sibyl.orchestrate module."""
import json
import shlex
import sys
from pathlib import Path

import pytest

from sibyl.orchestrate import (
    FarsOrchestrator, load_prompt, load_common_prompt,
    render_skill_prompt, render_control_plane_prompt,
    PAPER_SECTIONS, cli_checkpoint, cli_dispatch_tasks, cli_resume,
    project_marker_file, self_heal_monitor_script,
    cli_experiment_status, cli_next, migrate_workspace, collect_dashboard_data,
    cli_experiment_supervisor_claim, cli_experiment_supervisor_heartbeat,
    cli_experiment_supervisor_notify_main, cli_experiment_supervisor_release,
    cli_experiment_supervisor_drain_wake, cli_experiment_supervisor_snapshot,
    cli_record_gpu_poll, cli_requeue_experiment_task,
)
from sibyl.config import Config
from sibyl.workspace import Workspace


# ══════════════════════════════════════════════
# State machine transitions
# ══════════════════════════════════════════════

class TestStageTransitions:
    """Test the full pipeline stage progression."""

    def test_init_action_is_noop_before_literature_search(self, make_orchestrator):
        o = make_orchestrator(stage="init")

        action = o.get_next_action()

        assert action["action_type"] == "bash"
        assert action["stage"] == "init"
        assert action["skills"] is None
        assert "initialized" in action["bash_command"]

    def test_init_advances_to_literature_search(self, make_orchestrator):
        o = make_orchestrator(stage="init")
        o.record_result("init")
        assert o.ws.get_status().stage == "literature_search"

    def test_linear_progression(self, make_orchestrator):
        """Test that each stage advances to the next in the default path."""
        linear_stages = [
            "literature_search", "idea_debate", "planning",
            "pilot_experiments", "experiment_cycle", "result_debate",
            "experiment_decision", "writing_outline", "writing_sections",
            "writing_critique", "writing_integrate", "writing_final_review",
            "writing_latex", "review",
            "reflection",
        ]
        o = make_orchestrator(stage="literature_search", idea_validation_rounds=0)
        for i, stage in enumerate(linear_stages[:-1]):
            o.ws.update_stage(stage)
            # writing_final_review needs a passing review file, otherwise
            # default score 5.0 triggers revision loop back to writing_integrate
            if stage == "writing_final_review":
                o.ws.write_file("writing/review.md", "SCORE: 9.0")
            o.record_result(stage)
            expected = linear_stages[i + 1]
            actual = o.ws.get_status().stage
            assert actual == expected, (
                f"After recording {stage}, expected {expected} but got {actual}"
            )

    def test_reflection_goes_to_quality_gate(self, make_orchestrator):
        """Without lark_sync stage, reflection goes directly to quality_gate."""
        o = make_orchestrator(stage="reflection", lark_enabled=True)
        o.record_result("reflection")
        assert o.ws.get_status().stage == "quality_gate"

    def test_reflection_to_quality_gate_lark_disabled(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", lark_enabled=False)
        o.record_result("reflection")
        assert o.ws.get_status().stage == "quality_gate"

    def test_stages_advance_directly_without_lark_sync(self, make_orchestrator):
        """Stages advance directly without interleaved lark_sync."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.record_result("literature_search")
        assert o.ws.get_status().stage == "idea_debate"

    def test_unknown_stage_forces_done(self, make_orchestrator):
        o = make_orchestrator(stage="nonexistent_stage")
        o.record_result("nonexistent_stage")
        assert o.ws.get_status().stage == "done"


class TestRecordResult:
    def test_rejects_done_stage(self, make_orchestrator):
        o = make_orchestrator(stage="done")
        with pytest.raises(ValueError, match="terminal stage"):
            o.record_result("done")

    def test_past_stage_mismatch_is_idempotent_noop(self, make_orchestrator):
        """Only stale/past stage retries should be ignored."""
        o = make_orchestrator(stage="planning")
        o.record_result("literature_search")  # should not raise
        assert o.ws.get_status().stage == "planning"  # unchanged

    def test_future_stage_mismatch_raises(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        with pytest.raises(ValueError, match="Stage mismatch"):
            o.record_result("writing_sections")

    def test_writes_score_log(self, make_orchestrator):
        o = make_orchestrator(stage="literature_search")
        o.record_result("literature_search", score=8.5)
        content = o.ws.read_file("logs/stage_literature_search_score.txt")
        assert content == "8.5"

    def test_git_commit_after_stage(self, make_orchestrator):
        o = make_orchestrator(stage="literature_search")
        o.ws.git_init()
        o.record_result("literature_search")
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=o.ws.root, capture_output=True, text=True
        )
        assert "literature_search" in result.stdout


# ══════════════════════════════════════════════
# Background Feishu sync
# ══════════════════════════════════════════════

class TestBackgroundSync:
    """Tests for background Feishu sync trigger in cli_record."""

    def test_cli_record_appends_pending_sync_when_lark_enabled(self, make_orchestrator):
        """cli_record should append a line to pending_sync.jsonl when lark_enabled."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.record_result("literature_search")
        pending_path = o.ws.root / "lark_sync" / "pending_sync.jsonl"
        assert pending_path.exists()
        lines = pending_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["trigger_stage"] == "literature_search"
        assert "timestamp" in entry
        assert "iteration" in entry

    def test_cli_record_no_pending_sync_when_lark_disabled(self, make_orchestrator):
        """No pending_sync.jsonl written when lark_enabled=False."""
        o = make_orchestrator(stage="literature_search", lark_enabled=False)
        o.record_result("literature_search")
        pending_path = o.ws.root / "lark_sync" / "pending_sync.jsonl"
        assert not pending_path.exists()

    def test_cli_record_appends_multiple_syncs(self, make_orchestrator):
        """Multiple stage completions append multiple lines."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.record_result("literature_search")
        o.record_result("idea_debate")
        pending_path = o.ws.root / "lark_sync" / "pending_sync.jsonl"
        lines = pending_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["trigger_stage"] == "literature_search"
        assert json.loads(lines[1])["trigger_stage"] == "idea_debate"

    def test_cli_record_returns_sync_requested(self, make_orchestrator, capsys, monkeypatch):
        """cli_record output includes sync_requested when lark_enabled."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.ws.write_file("config.yaml", "lark_enabled: true\ngpu_poll_enabled: false\n")
        monkeypatch.chdir(o.ws.root)
        from sibyl.orchestrate import cli_record
        result = cli_record(str(o.ws.root), "literature_search")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert result == output
        assert output["sync_requested"] is True

    def test_cli_record_no_sync_requested_when_disabled(self, make_orchestrator, capsys, monkeypatch):
        """cli_record output has no sync_requested when lark disabled."""
        o = make_orchestrator(stage="literature_search", lark_enabled=False)
        o.ws.write_file("config.yaml", "lark_enabled: false\ngpu_poll_enabled: false\n")
        monkeypatch.chdir(o.ws.root)
        from sibyl.orchestrate import cli_record
        cli_record(str(o.ws.root), "literature_search")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output.get("sync_requested", False) is False

    def test_no_pending_sync_for_init_stage(self, make_orchestrator):
        """init stage should not trigger sync."""
        o = make_orchestrator(stage="init", lark_enabled=True)
        # init auto-advances, but shouldn't write sync trigger
        pending_path = o.ws.root / "lark_sync" / "pending_sync.jsonl"
        assert not pending_path.exists()

    def test_no_pending_sync_for_quality_gate(self, make_orchestrator):
        """quality_gate should not trigger sync."""
        o = make_orchestrator(stage="quality_gate", lark_enabled=True, iteration=1)
        # quality_gate needs a score to proceed
        o.ws.write_file("logs/stage_review_score.txt", "9.0")
        o.record_result("quality_gate", score=9.0)
        pending_path = o.ws.root / "lark_sync" / "pending_sync.jsonl"
        assert not pending_path.exists()

    def test_cli_status_includes_sync_status(self, make_orchestrator, capsys):
        """cli_status should include lark sync status when sync_status.json exists."""
        o = make_orchestrator(stage="idea_debate", lark_enabled=True)
        ws_path = o.ws.root
        sync_dir = ws_path / "lark_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        status_data = {
            "last_sync_at": "2026-03-09T12:00:00Z",
            "last_sync_success": True,
            "last_synced_line": 1,
            "last_trigger_stage": "literature_search",
            "history": [],
        }
        (sync_dir / "sync_status.json").write_text(json.dumps(status_data))
        from sibyl.orchestrate import cli_status
        result = cli_status(str(ws_path))
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert result == output
        assert output["lark_sync_status"]["last_sync_success"] is True

    def test_cli_status_no_sync_status_when_missing(self, make_orchestrator, capsys):
        """cli_status should not include lark_sync_status when no sync_status.json."""
        o = make_orchestrator(stage="idea_debate", lark_enabled=False)
        ws_path = o.ws.root
        from sibyl.orchestrate import cli_status
        cli_status(str(ws_path))
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "lark_sync_status" not in output

    def test_cli_resume_reports_pending_hook_and_background_agent(self, make_orchestrator, capsys):
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(
            stage="experiment_cycle", lark_enabled=True,
            gpu_poll_enabled=False, supervisor_enabled=True,
        )
        # Persist supervisor_enabled so cli_resume re-reads it from config.yaml
        o.ws.write_file("config.yaml", o.config.to_yaml())
        o.ws.pause("user_stop")
        o.ws.write_file(
            "plan/task_plan.json",
            json.dumps({"tasks": [{"id": "task_a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 30}]}),
        )
        state = ExperimentState()
        register_task(state, "task_a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"task_a": [0]})
        o.ws.write_file(
            "lark_sync/pending_sync.jsonl",
            json.dumps({"trigger_stage": "planning"}) + "\n",
        )

        result = cli_resume(str(o.ws.root))
        output = json.loads(capsys.readouterr().out)
        breadcrumb = json.loads((o.ws.root / "breadcrumb.json").read_text(encoding="utf-8"))
        recovery_state = json.loads((o.ws.root / ".sibyl" / "recovery_state.json").read_text(encoding="utf-8"))

        assert result == output
        assert output["status"] == "resumed"
        assert output["resume_action_type"] == "experiment_wait"
        assert output["background_agent_required"] is True
        assert output["pending_sync_count"] == 1
        assert output["pending_hooks"][0]["name"] == "lark_sync"
        assert output["pending_background_agents"][0]["name"] == "sibyl-experiment-supervisor"
        assert output["resume_action"]["experiment_monitor"]["background_agent"]["name"] == "sibyl-experiment-supervisor"
        assert output["recovery"]["source"] == "cli_resume"
        assert output["recovery"]["background_agent_required"] is True
        assert recovery_state["pending_sync_count"] == 1
        assert recovery_state["source"] == "cli_resume"
        assert breadcrumb["action_type"] == "experiment_wait"
        assert breadcrumb["stage"] == "experiment_cycle"

    def test_cli_status_exposes_persisted_recovery_state(self, make_orchestrator, capsys):
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks
        from sibyl.orchestrate import cli_status

        o = make_orchestrator(
            stage="experiment_cycle", lark_enabled=True,
            gpu_poll_enabled=False, supervisor_enabled=True,
        )
        o.ws.write_file("config.yaml", o.config.to_yaml())
        o.ws.write_file(
            "plan/task_plan.json",
            json.dumps({"tasks": [{"id": "task_a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 30}]}),
        )
        state = ExperimentState()
        register_task(state, "task_a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"task_a": [0]})
        cli_next(str(o.ws.root))
        capsys.readouterr()

        result = cli_status(str(o.ws.root))
        output = json.loads(capsys.readouterr().out)

        assert result == output
        assert output["recovery"]["source"] == "cli_next"
        assert output["recovery"]["resume_action_type"] == "experiment_wait"
        assert output["recovery"]["background_agent_required"] is True

    def test_cli_status_does_not_materialize_runtime_scaffold(self, tmp_path, capsys):
        proj = tmp_path / "bare-status"
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

        from sibyl.orchestrate import cli_status
        cli_status(str(proj))

        output = json.loads(capsys.readouterr().out)
        assert output["stage"] == "planning"
        assert not (proj / ".sibyl" / "system.json").exists()
        assert not (proj / "CLAUDE.md").exists()


# ══════════════════════════════════════════════
# Quality gate
# ══════════════════════════════════════════════

class TestQualityGate:
    def test_done_when_score_above_threshold_from_review_json(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2)
        o.ws.write_file("supervisor/review.json", json.dumps({
            "score": 9.0,
            "verdict": "done",
            "summary": "Ready to finish",
            "issues": [],
        }))
        o.record_result("quality_gate")
        assert o.ws.get_status().stage == "done"

    def test_done_when_score_above_threshold(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2)
        o.ws.write_file("supervisor/review_writing.md", "Overall quality score: 9.0")
        o.record_result("quality_gate")
        assert o.ws.get_status().stage == "done"

    def test_loops_when_score_below_threshold(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.record_result("quality_gate")
        s = o.ws.get_status()
        assert s.stage == "literature_search"
        assert s.iteration == 2

    def test_done_when_max_iterations_reached(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=10)
        o.ws.write_file("supervisor/review_writing.md", "score: 3.0")
        o.record_result("quality_gate")
        assert o.ws.get_status().stage == "done"

    def test_requires_min_2_iterations_for_done(self, make_orchestrator):
        """Even high score shouldn't terminate on first iteration."""
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 9.5")
        o.record_result("quality_gate")
        assert o.ws.get_status().stage == "literature_search"

    def test_atomic_stage_and_iteration_on_loop(self, make_orchestrator):
        """Verify both stage and iteration are updated atomically."""
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.record_result("quality_gate")
        s = o.ws.get_status()
        assert s.stage == "literature_search"
        assert s.iteration == 2

    def test_quality_gate_display_action_consistent(self, make_orchestrator):
        """_action_quality_gate and _get_next_stage must agree on done/continue."""
        o = make_orchestrator(stage="quality_gate", iteration=2)
        o.ws.write_file("supervisor/review_writing.md", "score: 9.0")
        action = o.get_next_action()
        assert action["action_type"] == "done"

    def test_quality_gate_display_action_continue(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        action = o.get_next_action()
        assert action["action_type"] == "bash"
        assert "iteration" in action["description"].lower()

    def test_threshold_from_action_plan(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2)
        o.ws.write_file("supervisor/review.json", json.dumps({
            "score": 7.0,
            "verdict": "revise",
            "summary": "Needs more work",
            "issues": [],
        }))
        o.ws.write_file("reflection/action_plan.json", json.dumps({
            "suggested_threshold_adjustment": 6.0
        }))
        o.record_result("quality_gate")
        # 7.0 >= 6.0 and iteration 2 >= 2 → done
        assert o.ws.get_status().stage == "done"

    def test_threshold_bounds_validation(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2)
        o.ws.write_file("supervisor/review_writing.md", "score: 9.0")
        o.ws.write_file("reflection/action_plan.json", json.dumps({
            "suggested_threshold_adjustment": 100.0,  # out of bounds
            "suggested_max_iterations": 999,  # out of bounds
        }))
        # Out-of-bounds values should be ignored, defaults used
        score, threshold, max_iters = o._parse_quality_gate_params()
        assert threshold == 8.0  # default, not 100
        assert max_iters == 10  # default, not 999

    def test_max_iterations_not_hard_capped_at_20(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2, max_iterations_cap=100)
        o.ws.write_file("supervisor/review.json", json.dumps({
            "score": 7.0,
            "verdict": "revise",
            "summary": "Needs more work",
            "issues": [],
        }))
        o.ws.write_file("reflection/action_plan.json", json.dumps({
            "suggested_max_iterations": 50,
        }))
        _, _, max_iters = o._parse_quality_gate_params()
        assert max_iters == 50

    def test_max_iterations_cap_zero_disables_upper_bound(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2, max_iterations_cap=0)
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
        o.ws.write_file("reflection/action_plan.json", json.dumps({
            "suggested_max_iterations": 250,
        }))
        _, _, max_iters = o._parse_quality_gate_params()
        assert max_iters == 250


# ══════════════════════════════════════════════
# Iteration boundary (archive + clear)
# ══════════════════════════════════════════════

class TestIterationBoundary:
    def test_archives_before_clearing(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.ws.write_file("idea/perspectives/innovator.md", "idea")
        o.ws.write_file("writing/critique/intro_critique.md", "critique")
        o.record_result("quality_gate")
        # Archived
        archive = o.ws.root / "logs/iterations/iter_001"
        assert (archive / "idea" / "perspectives" / "innovator.md").exists()
        # Cleared
        assert not (o.ws.root / "idea/perspectives/innovator.md").exists()
        assert not (o.ws.root / "writing/critique/intro_critique.md").exists()

    def test_preserves_cross_iteration_data(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        # These should survive clearing
        o.ws.write_file("idea/proposal.md", "final proposal")
        o.ws.write_file("writing/paper.md", "integrated paper")
        o.ws.write_file("context/literature.md", "literature review")
        o.ws.write_file("exp/results/full/result.json", '{"acc": 0.9}')
        o.ws.write_file("writing/outline.md", "outline")
        o.ws.write_file("topic.txt", "my topic")
        o.record_result("quality_gate")
        assert o.ws.read_file("idea/proposal.md") == "final proposal"
        assert o.ws.read_file("writing/paper.md") == "integrated paper"
        assert o.ws.read_file("context/literature.md") == "literature review"
        assert o.ws.read_file("exp/results/full/result.json") == '{"acc": 0.9}'
        assert o.ws.read_file("writing/outline.md") == "outline"
        assert o.ws.read_file("topic.txt") == "my topic"

    def test_clears_revision_markers(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.ws.write_file("writing/critique/revision_round_1.marker", "r1")
        o.ws.write_file("writing/critique/revision_round_2.marker", "r2")
        o.record_result("quality_gate")
        critique_dir = o.ws.root / "writing/critique"
        markers = [f for f in critique_dir.iterdir()
                   if f.name.startswith("revision_round_")]
        assert len(markers) == 0

    def test_clears_pivot_markers(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        (o.ws.root / "logs/idea_exp_cycle_1.marker").write_text("pivot 1")
        (o.ws.root / "logs/idea_exp_cycle_2.marker").write_text("pivot 2")
        o.record_result("quality_gate")
        markers = list((o.ws.root / "logs").glob("idea_exp_cycle_*.marker"))
        assert len(markers) == 0

    def test_archive_failure_does_not_block(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        # Make archive dir read-only to force OSError
        archive_parent = o.ws.root / "logs" / "iterations"
        archive_parent.mkdir(parents=True, exist_ok=True)
        target = archive_parent / "iter_001"
        target.mkdir()
        # Create a file that blocks rmtree
        blocker = target / "idea"
        blocker.mkdir()
        (blocker / "test").write_text("x")
        blocker.chmod(0o444)
        # Even if archive has issues, pipeline should continue
        try:
            o.record_result("quality_gate")
        except OSError:
            pytest.skip("OS doesn't allow this permission trick")
        s = o.ws.get_status()
        assert s.stage == "literature_search"
        assert s.iteration == 2
        # Cleanup permissions for tmp_path cleanup
        blocker.chmod(0o755)

    def test_recreates_cleared_directories(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.record_result("quality_gate")
        # Directories should be recreated (empty)
        assert (o.ws.root / "supervisor").is_dir()
        assert (o.ws.root / "critic").is_dir()
        assert (o.ws.root / "reflection").is_dir()
        assert (o.ws.root / "writing/critique").is_dir()

    def test_preserves_lessons_learned(self, make_orchestrator):
        """lessons_learned.md should survive iteration clearing."""
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.ws.write_file("reflection/lessons_learned.md", "# Lessons\n- Fix X")
        o.record_result("quality_gate")
        content = o.ws.read_file("reflection/lessons_learned.md")
        assert content is not None
        assert "Fix X" in content

    def test_preserves_prev_action_plan(self, make_orchestrator):
        """action_plan.json should be saved as prev_action_plan.json."""
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0")
        o.ws.write_file("reflection/action_plan.json", '{"issues_classified": []}')
        o.record_result("quality_gate")
        content = o.ws.read_file("reflection/prev_action_plan.json")
        assert content is not None
        assert "issues_classified" in content


# ══════════════════════════════════════════════
# PIVOT mechanism
# ══════════════════════════════════════════════

class TestPivot:
    def test_pivot_loops_to_idea_debate(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision", idea_exp_cycles=3)
        o.ws.write_file("supervisor/experiment_analysis.md", "DECISION: PIVOT")
        o.record_result("experiment_decision")
        assert o.ws.get_status().stage == "idea_debate"

    def test_pivot_creates_marker(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision", idea_exp_cycles=3)
        o.ws.write_file("supervisor/experiment_analysis.md", "DECISION: PIVOT")
        o.record_result("experiment_decision")
        markers = list((o.ws.root / "logs").glob("idea_exp_cycle_*.marker"))
        assert len(markers) == 1

    def test_pivot_exhaustion_proceeds_to_writing(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision", idea_exp_cycles=2)
        o.ws.write_file("supervisor/experiment_analysis.md", "DECISION: PIVOT")
        # Exhaust cycle limit
        (o.ws.root / "logs").mkdir(parents=True, exist_ok=True)
        (o.ws.root / "logs/idea_exp_cycle_1.marker").write_text("p1")
        (o.ws.root / "logs/idea_exp_cycle_2.marker").write_text("p2")
        o.record_result("experiment_decision")
        assert o.ws.get_status().stage == "writing_outline"

    def test_pivot_exhaustion_logs_error(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision", idea_exp_cycles=1)
        o.ws.write_file("supervisor/experiment_analysis.md", "DECISION: PIVOT")
        (o.ws.root / "logs").mkdir(parents=True, exist_ok=True)
        (o.ws.root / "logs/idea_exp_cycle_1.marker").write_text("p1")
        o.record_result("experiment_decision")
        errors = o.ws.get_status().errors
        assert any("PIVOT requested but cycle limit" in e["error"] for e in errors)

    def test_proceed_goes_to_writing(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision")
        o.ws.write_file("supervisor/experiment_analysis.md", "DECISION: PROCEED")
        o.record_result("experiment_decision")
        assert o.ws.get_status().stage == "writing_outline"

    def test_missing_analysis_file(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision")
        o.record_result("experiment_decision")
        assert o.ws.get_status().stage == "writing_outline"
        errors = o.ws.get_status().errors
        assert any("not found" in e["error"] for e in errors)

    def test_pivot_case_insensitive(self, make_orchestrator):
        o = make_orchestrator(stage="experiment_decision", idea_exp_cycles=3)
        o.ws.write_file("supervisor/experiment_analysis.md", "Decision: pivot")
        o.record_result("experiment_decision")
        assert o.ws.get_status().stage == "idea_debate"


class TestIdeaValidationLoop:
    def test_pilot_stage_enters_validation_decision_when_enabled(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", idea_validation_rounds=2)
        o.record_result("pilot_experiments")
        assert o.ws.get_status().stage == "idea_validation_decision"

    def test_validation_decision_advance_filters_selected_candidate(self, make_orchestrator):
        o = make_orchestrator(stage="idea_validation_decision", idea_validation_rounds=2)
        o.ws.write_file(
            "plan/task_plan.json",
            json.dumps({
                "tasks": [
                    {"id": "shared_setup", "candidate_id": "shared", "depends_on": [],
                     "gpu_count": 1, "estimated_minutes": 5},
                    {"id": "cand_a_train", "candidate_id": "cand_a", "depends_on": ["shared_setup"],
                     "gpu_count": 1, "estimated_minutes": 10},
                    {"id": "cand_b_train", "candidate_id": "cand_b", "depends_on": ["shared_setup"],
                     "gpu_count": 1, "estimated_minutes": 10},
                ]
            }),
        )
        o.ws.write_file(
            "supervisor/idea_validation_decision.json",
            json.dumps({
                "decision": "ADVANCE",
                "selected_candidate_id": "cand_b",
                "confidence": 0.82,
            }),
        )
        o.record_result("idea_validation_decision")
        assert o.ws.get_status().stage == "experiment_cycle"
        plan = json.loads(o.ws.read_file("plan/task_plan.json"))
        task_ids = [task["id"] for task in plan["tasks"]]
        assert task_ids == ["shared_setup", "cand_b_train"]
        selected = json.loads(o.ws.read_file("plan/selected_candidate.json"))
        assert selected["selected_candidate_id"] == "cand_b"

    def test_validation_decision_refine_loops_back_to_idea_debate(self, make_orchestrator):
        o = make_orchestrator(stage="idea_validation_decision", idea_validation_rounds=2)
        o.ws.write_file("idea/perspectives/innovator.md", "old idea")
        o.ws.create_checkpoint(
            "idea_debate",
            "idea",
            {"innovator": "idea/perspectives/innovator.md"},
            iteration=0,
        )
        o.ws.complete_checkpoint_step("idea", "innovator")
        o.ws.write_file(
            "supervisor/idea_validation_decision.json",
            json.dumps({
                "decision": "REFINE",
                "selected_candidate_id": "cand_b",
                "confidence": 0.61,
            }),
        )
        o.record_result("idea_validation_decision")
        assert o.ws.get_status().stage == "idea_debate"
        markers = list((o.ws.root / "logs").glob("idea_validation_round_*.marker"))
        assert len(markers) == 1
        action = o.get_next_action()
        assert action["action_type"] == "team"

    def test_validation_decision_refine_respects_round_limit(self, make_orchestrator):
        o = make_orchestrator(stage="idea_validation_decision", idea_validation_rounds=1)
        o.ws.write_file("logs/idea_validation_round_1.marker", "round 1")
        o.ws.write_file(
            "supervisor/idea_validation_decision.json",
            json.dumps({"decision": "REFINE", "selected_candidate_id": "cand_a"}),
        )
        o.record_result("idea_validation_decision")
        assert o.ws.get_status().stage == "experiment_cycle"
        errors = o.ws.get_status().errors
        assert any("more refinement rounds than allowed" in e["error"] for e in errors)


# ══════════════════════════════════════════════
# Codex idea iteration loop
# ══════════════════════════════════════════════

class TestCodexIdeaIteration:
    """Test the Codex-guided idea refinement loop."""

    def test_codex_revise_loops_back_to_idea_debate(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=True, codex_idea_rounds=2)
        o.ws.write_file(
            "codex/idea_debate_review.md",
            "## Review\nNeeds work.\n\nVERDICT: REVISE",
        )
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "idea_debate"
        markers = list((o.ws.root / "logs").glob("codex_idea_round_*.marker"))
        assert len(markers) == 1

    def test_codex_approve_advances_to_planning(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=True, codex_idea_rounds=2)
        o.ws.write_file(
            "codex/idea_debate_review.md",
            "## Review\nLooks good.\n\nVERDICT: APPROVE",
        )
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "planning"

    def test_codex_missing_review_advances(self, make_orchestrator):
        """Missing Codex review should not block — advance by default."""
        o = make_orchestrator(stage="idea_debate", codex_enabled=True, codex_idea_rounds=2)
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "planning"

    def test_codex_revise_respects_round_limit(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=True, codex_idea_rounds=1)
        o.ws.write_file("logs/codex_idea_round_1.marker", "round 1")
        o.ws.write_file(
            "codex/idea_debate_review.md",
            "Still not great.\n\nVERDICT: REVISE",
        )
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "planning"
        errors = o.ws.get_status().errors
        assert any("codex_idea_rounds limit" in e["error"] for e in errors)

    def test_codex_disabled_skips_iteration(self, make_orchestrator):
        """codex_enabled=False should bypass the iteration check entirely."""
        o = make_orchestrator(stage="idea_debate", codex_enabled=False, codex_idea_rounds=2)
        o.ws.write_file(
            "codex/idea_debate_review.md",
            "VERDICT: REVISE",
        )
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "planning"

    def test_codex_idea_rounds_zero_skips_iteration(self, make_orchestrator):
        """codex_idea_rounds=0 should bypass even when codex_enabled."""
        o = make_orchestrator(stage="idea_debate", codex_enabled=True, codex_idea_rounds=0)
        o.ws.write_file(
            "codex/idea_debate_review.md",
            "VERDICT: REVISE",
        )
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "planning"

    def test_codex_revise_clears_stale_verdict_on_loop(self, make_orchestrator):
        """prepare_idea_refinement_round should delete the old Codex review."""
        o = make_orchestrator(stage="idea_debate", codex_enabled=True, codex_idea_rounds=2)
        o.ws.write_file(
            "codex/idea_debate_review.md",
            "Old review.\n\nVERDICT: REVISE",
        )
        o.record_result("idea_debate")
        assert o.ws.get_status().stage == "idea_debate"
        # The stale review should have been deleted
        assert o.ws.read_file("codex/idea_debate_review.md") is None

    def test_codex_markers_cleared_on_iteration_boundary(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", codex_enabled=True)
        o.ws.write_file("logs/codex_idea_round_1.marker", "round 1")
        o.ws.write_file("logs/codex_idea_round_2.marker", "round 2")
        o.ws.write_file("supervisor/review.json", json.dumps({"score": 9.5}))
        from sibyl.orchestration.state_machine import clear_iteration_artifacts
        clear_iteration_artifacts(o, 1)
        markers = list((o.ws.root / "logs").glob("codex_idea_round_*.marker"))
        assert len(markers) == 0


class TestNoveltyCheckerPostStep:
    """Test that the novelty checker is included in idea_debate post_steps."""

    def test_novelty_checker_in_post_steps(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=False)
        action = o.get_next_action()
        assert action["action_type"] == "team"
        post_steps = action["team"]["post_steps"]
        skill_names = [step["skill"] for step in post_steps]
        assert "sibyl-synthesizer" in skill_names
        assert "sibyl-novelty-checker" in skill_names
        # novelty checker should be after synthesizer
        assert skill_names.index("sibyl-novelty-checker") > skill_names.index("sibyl-synthesizer")

    def test_codex_reviewer_after_novelty_checker(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=True)
        action = o.get_next_action()
        post_steps = action["team"]["post_steps"]
        skill_names = [step["skill"] for step in post_steps]
        assert "sibyl-novelty-checker" in skill_names
        assert "sibyl-codex-reviewer" in skill_names
        assert skill_names.index("sibyl-codex-reviewer") > skill_names.index("sibyl-novelty-checker")

    def test_novelty_feedback_in_context(self, make_orchestrator):
        """Novelty report from prior round should appear in the team prompt context."""
        o = make_orchestrator(stage="idea_debate")
        o.ws.write_file("idea/novelty_report.md", "Candidate A has a collision with Paper X")
        action = o.get_next_action()
        context = o.ws.read_file("context/idea_context.md") or ""
        assert "collision" in context.lower() or "novelty" in context.lower()


# ══════════════════════════════════════════════
# Writing revision loop
# ══════════════════════════════════════════════

class TestWritingRevision:
    def test_low_score_triggers_revision(self, make_orchestrator):
        o = make_orchestrator(stage="writing_final_review", writing_revision_rounds=2)
        o.ws.write_file("writing/review.md", "SCORE: 5.0")
        o.record_result("writing_final_review")
        assert o.ws.get_status().stage == "writing_integrate"

    def test_high_score_skips_revision(self, make_orchestrator):
        o = make_orchestrator(stage="writing_final_review")
        o.ws.write_file("writing/review.md", "SCORE: 8.0")
        o.record_result("writing_final_review")
        assert o.ws.get_status().stage == "writing_latex"

    def test_revision_creates_marker(self, make_orchestrator):
        o = make_orchestrator(stage="writing_final_review", writing_revision_rounds=2)
        o.ws.write_file("writing/review.md", "SCORE: 5.0")
        o.record_result("writing_final_review")
        markers = list((o.ws.root / "writing/critique").glob("revision_round_*.marker"))
        assert len(markers) == 1

    def test_revision_exhaustion(self, make_orchestrator):
        o = make_orchestrator(stage="writing_final_review", writing_revision_rounds=2)
        o.ws.write_file("writing/review.md", "SCORE: 5.0")
        o.ws.write_file("writing/critique/revision_round_1.marker", "r1")
        o.ws.write_file("writing/critique/revision_round_2.marker", "r2")
        o.record_result("writing_final_review")
        # Should proceed despite low score
        assert o.ws.get_status().stage == "writing_latex"

    def test_score_case_insensitive(self, make_orchestrator):
        """Regression test for H6: score regex must be case-insensitive."""
        o = make_orchestrator(stage="writing_final_review", writing_revision_rounds=2)
        o.ws.write_file("writing/review.md", "Score: 5.0")  # lowercase
        o.record_result("writing_final_review")
        assert o.ws.get_status().stage == "writing_integrate"

    def test_missing_review_defaults_to_revision(self, make_orchestrator):
        o = make_orchestrator(stage="writing_final_review", writing_revision_rounds=2)
        # No review.md → default score 5.0 → triggers revision
        o.record_result("writing_final_review")
        assert o.ws.get_status().stage == "writing_integrate"


# ══════════════════════════════════════════════
# Score parsing
# ══════════════════════════════════════════════

class TestScoreParsing:
    def test_basic_score(self, make_orchestrator):
        o = make_orchestrator(stage="quality_gate", iteration=2)
        o.ws.write_file("supervisor/review_writing.md", "quality score: 8.5")
        score, _, _ = o._parse_quality_gate_params()
        assert score == 8.5

    def test_score_clamped_to_10(self, make_orchestrator):
        o = make_orchestrator()
        o.ws.write_file("supervisor/review_writing.md", "score: 99")
        score, _, _ = o._parse_quality_gate_params()
        assert score == 10.0

    def test_score_clamped_to_0(self, make_orchestrator):
        o = make_orchestrator()
        o.ws.write_file("supervisor/review_writing.md", "score: -5")
        # Negative won't match \d+, defaults to 5.0
        score, _, _ = o._parse_quality_gate_params()
        assert score == 5.0

    def test_score_rejects_10x(self, make_orchestrator):
        """Regression test for H5: '10x speedup' should not match as score."""
        o = make_orchestrator()
        o.ws.write_file("supervisor/review_writing.md",
                        "This method scores 10x speedup. Quality: 7.5")
        score, _, _ = o._parse_quality_gate_params()
        assert score == 7.5  # should match "Quality: 7.5", not "10x"

    def test_no_score_defaults_to_5(self, make_orchestrator):
        o = make_orchestrator()
        o.ws.write_file("supervisor/review_writing.md", "No numeric rating here")
        score, _, _ = o._parse_quality_gate_params()
        assert score == 5.0

    def test_missing_review_defaults_to_5(self, make_orchestrator):
        o = make_orchestrator()
        score, _, _ = o._parse_quality_gate_params()
        assert score == 5.0


# ══════════════════════════════════════════════
# Action generation
# ══════════════════════════════════════════════

class TestActionGeneration:
    def test_init_returns_init_stage(self, make_orchestrator):
        o = make_orchestrator(stage="init")
        action = o.get_next_action()
        assert action["stage"] == "init"
        assert action["action_type"] == "bash"

    def test_paused_workspace_auto_resumes(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        o.ws.pause("rate_limit")
        action = o.get_next_action()
        assert action["action_type"] != "paused"
        assert action["stage"] == "planning"
        status = o.ws.get_status()
        assert status.paused is False
        assert status.paused_at is None

    def test_user_stop_returns_stopped_action(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        o.ws.pause("user_stop")
        action = o.get_next_action()
        assert action["action_type"] == "stopped"
        assert action["stage"] == "planning"
        status = o.ws.get_status()
        assert status.stop_requested is True
        assert status.stop_requested_at is not None

    def test_done_returns_done_action(self, make_orchestrator):
        o = make_orchestrator(stage="done")
        action = o.get_next_action()
        assert action["action_type"] == "done"

    def test_idea_debate_returns_team(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate")
        action = o.get_next_action()
        assert action["action_type"] == "team"
        assert action["team"] is not None

    def test_idea_debate_with_codex(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=True)
        action = o.get_next_action()
        codex_steps = [s for s in action["team"]["post_steps"] if s["type"] == "codex"]
        assert len(codex_steps) == 1

    def test_idea_debate_without_codex(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate", codex_enabled=False)
        action = o.get_next_action()
        codex_steps = [s for s in action["team"]["post_steps"] if s["type"] == "codex"]
        assert len(codex_steps) == 0

    def test_writing_mode_sequential(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="sequential")
        action = o.get_next_action()
        assert action["action_type"] == "skill"
        assert action["skills"][0]["name"] == "sibyl-sequential-writer"

    def test_writing_mode_codex(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="codex", codex_enabled=True)
        action = o.get_next_action()
        assert action["skills"][0]["name"] == "sibyl-codex-writer"

    def test_writing_mode_codex_falls_back_when_disabled(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="codex", codex_enabled=False)
        action = o.get_next_action()
        assert action["action_type"] == "team"
        assert action["team"]["team_name"] == "sibyl-writing-sections"
        assert "自动回退" in action["description"]

    def test_writing_mode_parallel(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="parallel")
        action = o.get_next_action()
        assert action["action_type"] == "team"

    def test_review_parallel(self, make_orchestrator):
        o = make_orchestrator(stage="review", codex_enabled=False)
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        names = [s["name"] for s in action["skills"]]
        assert "sibyl-critic" in names
        assert "sibyl-supervisor" in names
        assert len(names) == 2

    def test_review_parallel_with_codex(self, make_orchestrator):
        o = make_orchestrator(stage="review", codex_enabled=True)
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        names = [s["name"] for s in action["skills"]]
        assert "sibyl-critic" in names
        assert "sibyl-supervisor" in names
        assert "sibyl-codex-reviewer" in names
        assert len(names) == 3

    def test_backward_compat_critic_review(self, make_orchestrator):
        o = make_orchestrator(stage="critic_review")
        action = o.get_next_action()
        assert o.ws.get_status().stage == "review"
        assert action["action_type"] == "skills_parallel"

    def test_backward_compat_supervisor_review(self, make_orchestrator):
        o = make_orchestrator(stage="supervisor_review")
        action = o.get_next_action()
        assert o.ws.get_status().stage == "review"
        assert action["action_type"] == "skills_parallel"

    def test_experiment_mode_ssh(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", experiment_mode="ssh_mcp",
                              gpu_poll_enabled=False)
        action = o.get_next_action()
        assert action["skills"][0]["name"] == "sibyl-experimenter"

    def test_experiment_mode_server_codex(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", experiment_mode="server_codex",
                              gpu_poll_enabled=False)
        action = o.get_next_action()
        assert action["skills"][0]["name"] == "sibyl-server-experimenter"

    def test_experiment_mode_server_claude(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", experiment_mode="server_claude",
                              gpu_poll_enabled=False)
        action = o.get_next_action()
        assert action["skills"][0]["name"] == "sibyl-server-experimenter"

    def test_idea_validation_decision_returns_skill(self, make_orchestrator):
        o = make_orchestrator(stage="idea_validation_decision")
        action = o.get_next_action()
        assert action["action_type"] == "skill"
        assert action["skills"][0]["name"] == "sibyl-idea-validation-decision"

    def test_idea_debate_team_structure(self, make_orchestrator):
        """idea_debate returns structured team with 6 teammates + post_steps."""
        o = make_orchestrator(stage="idea_debate")
        action = o.get_next_action()
        team = action["team"]
        assert team["team_name"] == "sibyl-idea-debate"
        assert len(team["teammates"]) == 6
        names = [t["name"] for t in team["teammates"]]
        assert "innovator" in names
        assert "pragmatist" in names
        assert "theoretical" in names
        assert "contrarian" in names
        assert "interdisciplinary" in names
        assert "empiricist" in names
        for t in team["teammates"]:
            assert "skill" in t
            assert "args" in t
        # synthesizer always in post_steps
        skill_steps = [s for s in team["post_steps"] if s["type"] == "skill"]
        assert any(s["skill"] == "sibyl-synthesizer" for s in skill_steps)
        assert "prompt" in team

    def test_idea_debate_context_includes_pilot_feedback(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate")
        o.ws.write_file("idea/proposal.md", "# Proposal\nInitial direction")
        o.ws.write_file("idea/hypotheses.md", "# Hypotheses\nH1")
        o.ws.write_file("exp/results/pilot_summary.md", "# Pilot Summary\nNO-GO on branch A")
        o.ws.write_file("idea/candidates.json", json.dumps({
            "candidates": [{"candidate_id": "cand_a", "status": "front_runner"}]
        }))
        action = o.get_next_action()
        context = o.ws.read_file("context/idea_context.md") or ""
        assert "小型实验真实反馈" in context
        assert "NO-GO on branch A" in context
        assert "当前候选 idea 池" in context
        assert "evidence-driven refinement round" in action["team"]["prompt"]

    def test_result_debate_team_structure(self, make_orchestrator):
        """result_debate returns structured team with 6 teammates + synthesizer."""
        o = make_orchestrator(stage="result_debate")
        action = o.get_next_action()
        team = action["team"]
        assert team["team_name"] == "sibyl-result-debate"
        assert len(team["teammates"]) == 6
        names = [t["name"] for t in team["teammates"]]
        assert "optimist" in names
        assert "skeptic" in names
        assert "strategist" in names
        assert "methodologist" in names
        assert "comparativist" in names
        assert "revisionist" in names
        # result-synthesizer always in post_steps
        skill_steps = [s for s in team["post_steps"] if s["type"] == "skill"]
        assert any(s["skill"] == "sibyl-result-synthesizer" for s in skill_steps)

    def test_result_debate_codex_step(self, make_orchestrator):
        """result_debate with codex_enabled includes codex post_step."""
        o = make_orchestrator(stage="result_debate", codex_enabled=True)
        action = o.get_next_action()
        codex_steps = [s for s in action["team"]["post_steps"] if s["type"] == "codex"]
        assert len(codex_steps) == 1
        assert codex_steps[0]["skill"] == "sibyl-codex-reviewer"

    def test_result_debate_no_codex(self, make_orchestrator):
        o = make_orchestrator(stage="result_debate", codex_enabled=False)
        action = o.get_next_action()
        codex_steps = [s for s in action["team"]["post_steps"] if s["type"] == "codex"]
        assert len(codex_steps) == 0
        # synthesizer is always present
        skill_steps = [s for s in action["team"]["post_steps"] if s["type"] == "skill"]
        assert len(skill_steps) == 1

    def test_writing_sections_parallel_team_structure(self, make_orchestrator):
        """writing_sections parallel mode returns 6 section-writer teammates."""
        o = make_orchestrator(stage="writing_sections", writing_mode="parallel")
        action = o.get_next_action()
        team = action["team"]
        assert team["team_name"] == "sibyl-writing-sections"
        assert len(team["teammates"]) == 6
        for t in team["teammates"]:
            assert t["skill"] == "sibyl-section-writer"
            assert t["name"].startswith("writer-")
        assert len(team["post_steps"]) == 0

    def test_writing_critique_team_structure(self, make_orchestrator):
        """writing_critique returns 6 section-critic teammates."""
        o = make_orchestrator(stage="writing_critique")
        action = o.get_next_action()
        team = action["team"]
        assert team["team_name"] == "sibyl-writing-critique"
        assert len(team["teammates"]) == 6
        for t in team["teammates"]:
            assert t["skill"] == "sibyl-section-critic"
            assert t["name"].startswith("critic-")
        assert len(team["post_steps"]) == 0

    def test_all_stages_return_valid_action(self, make_orchestrator):
        """Every stage in STAGES must return a valid action dict."""
        for stage in FarsOrchestrator.STAGES:
            o = make_orchestrator(stage=stage)
            action = o.get_next_action()
            assert "action_type" in action
            assert "stage" in action


# ══════════════════════════════════════════════
# Post-reflection hook
# ══════════════════════════════════════════════

class TestPostReflectionHook:
    def test_logs_iteration_from_structured_review_json(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=1)
        o.ws.write_file(
            "supervisor/review.json",
            json.dumps(
                {
                    "score": 7.25,
                    "verdict": "continue",
                    "summary": "Promising but needs stronger baselines",
                    "issues": [],
                }
            ),
        )
        o.record_result("reflection")
        log = json.loads((o.ws.root / "logs/iterations/iter_001_reflection.json").read_text())
        assert log["quality_score"] == 7.25

    def test_logs_iteration(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
        o.record_result("reflection")
        log = o.ws.root / "logs/iterations/iter_001_reflection.json"
        assert log.exists()

    def test_writes_diary(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=1, lark_enabled=False)
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
        o.ws.write_file(
            "critic/findings.json",
            json.dumps(
                {
                    "summary": "Main weakness is missing ablation detail",
                    "findings": [],
                }
            ),
        )
        o.record_result("reflection")
        diary = o.ws.read_file("logs/research_diary.md")
        assert diary is not None
        assert "Iteration 1" in diary
        assert "missing ablation detail" in diary

    def test_survives_missing_files(self, make_orchestrator):
        """Hook should not crash if supervisor/critic files are missing."""
        o = make_orchestrator(stage="reflection", iteration=1, lark_enabled=False)
        o.record_result("reflection")  # should not raise
        assert o.ws.get_status().stage == "quality_gate"

    def test_evolution_recording(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=1,
                              lark_enabled=False, evolution_enabled=True)
        o.ws.write_file("supervisor/review_writing.md", "score: 6.0")
        o.record_result("reflection")
        # Evolution engine should have recorded outcome
        from sibyl.evolution import EvolutionEngine
        engine = EvolutionEngine()
        outcomes = engine._load_outcomes()
        # At least one outcome should exist for this project
        assert any(r.get("project") == "test-proj" for r in outcomes)

    def test_normalizes_action_plan_before_logging_and_evolution(self, make_orchestrator):
        o = make_orchestrator(
            stage="reflection",
            iteration=2,
            lark_enabled=False,
            evolution_enabled=True,
        )
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
        o.ws.write_file(
            "reflection/action_plan.json",
            json.dumps(
                {
                    "issues_classified": [
                        {
                            "description": "Need stronger literature comparison",
                            "category": "research",
                            "severity": "critical",
                            "status": "ongoing",
                        }
                    ],
                    "quality_trajectory": "divergent",
                    "success_patterns": ["Clear ablation table"],
                },
                ensure_ascii=False,
            ),
        )

        o.record_result("reflection")

        action_plan = json.loads(o.ws.read_file("reflection/action_plan.json"))
        issue = action_plan["issues_classified"][0]
        assert issue["category"] == "analysis"
        assert issue["severity"] == "high"
        assert issue["status"] == "recurring"
        assert issue["issue_key"].startswith("analysis:")
        assert action_plan["quality_trajectory"] == "stagnant"

        from sibyl.evolution import EvolutionEngine

        engine = EvolutionEngine()
        outcomes = engine._load_outcomes()
        record = [entry for entry in outcomes if entry.get("project") == "test-proj"][0]
        assert record["classified_issues"][0]["category"] == "analysis"
        assert record["classified_issues"][0]["severity"] == "high"

    def test_infers_fixed_issues_from_previous_action_plan(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=2, lark_enabled=False)
        o.ws.write_file(
            "reflection/prev_action_plan.json",
            json.dumps(
                {
                    "issues_classified": [
                        {
                            "description": "Weak baseline comparison",
                            "category": "analysis",
                            "severity": "medium",
                            "status": "recurring",
                            "issue_key": "analysis:weak-baseline-comparison",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        )
        o.ws.write_file("reflection/action_plan.json", '{"issues_classified": []}')

        o.record_result("reflection")

        log = json.loads((o.ws.root / "logs/iterations/iter_002_reflection.json").read_text())
        assert "Weak baseline comparison" in log["issues_fixed"]

    def test_writes_quality_trend_when_evolution_enabled(self, make_orchestrator):
        o = make_orchestrator(
            stage="reflection",
            iteration=1,
            lark_enabled=False,
            evolution_enabled=True,
        )
        o.ws.write_file("supervisor/review_writing.md", "score: 6.5")

        o.record_result("reflection")

        trend = o.ws.read_file("logs/quality_trend.md")
        assert trend is not None
        assert "# 质量趋势" in trend
        assert "score=6.5" in trend


# ══════════════════════════════════════════════
# CLI helpers
# ══════════════════════════════════════════════

class TestCLI:
    def test_cli_init(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        from sibyl.orchestrate import cli_init
        result = cli_init("Test Topic", "test-cli-proj")
        output = json.loads(capsys.readouterr().out)
        assert result == output
        assert output["project_name"] == "test-cli-proj"
        assert "workspace_path" in output

    def test_cli_next_logs_current_iteration(self, tmp_path, capsys):
        ws = Workspace(tmp_path, "iter-log-proj")
        ws.write_file("topic.txt", "test research topic")
        ws.update_stage("reflection")
        ws.update_iteration(3)

        action = cli_next(str(ws.root))
        output = json.loads(capsys.readouterr().out)
        assert action == output

        events = (ws.root / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(events) == 1
        event = json.loads(events[0])
        assert event["event"] == "stage_start"
        assert event["iteration"] == 3

    def test_load_experiment_plan_reads_task_plan_from_active_workspace(self, tmp_path):
        ws = Workspace(tmp_path, "compat-plan-proj", iteration_dirs=True)
        ws.write_file("plan/task_plan.json", json.dumps({
            "tasks": [{"id": "task_a", "depends_on": []}],
        }))

        from sibyl.orchestrate import _load_experiment_plan

        plan = _load_experiment_plan(str(ws.root))
        assert plan["tasks"][0]["id"] == "task_a"

    def test_load_experiment_plan_falls_back_to_legacy_experiment_plan_path(self, tmp_path):
        ws = Workspace(tmp_path, "compat-legacy-plan")
        legacy_plan = ws.active_path("exp/experiment_plan.json")
        legacy_plan.parent.mkdir(parents=True, exist_ok=True)
        legacy_plan.write_text(
            json.dumps({"tasks": [{"id": "legacy_task", "depends_on": []}]}),
            encoding="utf-8",
        )

        from sibyl.orchestrate import _load_experiment_plan

        plan = _load_experiment_plan(str(ws.root))
        assert plan["tasks"][0]["id"] == "legacy_task"

    def test_get_next_batch_wrapper_uses_active_workspace(self, tmp_path):
        ws = Workspace(tmp_path, "compat-batch-proj", iteration_dirs=True)
        ws.write_file("plan/task_plan.json", json.dumps({
            "tasks": [
                {"id": "task_a", "depends_on": []},
                {"id": "task_b", "depends_on": []},
            ],
        }))

        from sibyl.orchestrate import get_next_batch

        batch = get_next_batch(str(ws.root), [2, 3])
        assert batch is not None
        assert batch[0]["task_ids"] == ["task_a"]
        assert batch[0]["gpu_ids"] == [2]

    def test_cli_init_spec(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.yaml").write_text(
            f"workspaces_dir: {tmp_path / 'workspaces'}\niteration_dirs: true\n",
            encoding="utf-8",
        )
        from sibyl.orchestrate import cli_init_spec
        cli_init_spec("my-spec-proj")
        output = json.loads(capsys.readouterr().out)
        assert output["project_name"] == "my-spec-proj"
        assert Path(output["spec_path"]).exists()
        ws_root = Path(output["workspace_path"])
        assert (ws_root / "current").is_symlink()
        assert json.loads((ws_root / "status.json").read_text(encoding="utf-8"))["iteration_dirs"] is True

    def test_cli_init_from_existing_spec_reuses_workspace_and_project_config(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        from sibyl.orchestrate import cli_init_spec, cli_init_from_spec

        (tmp_path / "config.yaml").write_text(
            "iteration_dirs: true\nssh_server: initial-box\nremote_base: /srv/initial\n",
            encoding="utf-8",
        )
        cli_init_spec("My Fancy Project")
        output = json.loads(capsys.readouterr().out)
        ws_root = Path(output["workspace_path"])

        (ws_root / "config.yaml").write_text(
            "iteration_dirs: true\nssh_server: saved-box\nremote_base: /srv/saved\n",
            encoding="utf-8",
        )
        (tmp_path / "config.yaml").write_text(
            "iteration_dirs: false\nssh_server: root-box\nremote_base: /srv/root\n",
            encoding="utf-8",
        )

        cli_init_from_spec(str(ws_root / "spec.md"))
        restored = json.loads(capsys.readouterr().out)

        assert Path(restored["workspace_path"]).resolve() == ws_root.resolve()
        assert restored["project_name"] == "My Fancy Project"
        assert not (ws_root.parent / "my-fancy-project").exists()
        assert (ws_root / "current").is_symlink()
        project_cfg = (ws_root / "config.yaml").read_text(encoding="utf-8")
        assert "ssh_server: saved-box" in project_cfg
        assert "remote_base: /srv/saved" in project_cfg

    def test_cli_init_uses_root_config_and_persists_iteration_dirs(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.yaml").write_text(
            "iteration_dirs: true\nssh_server: persist-box\nremote_base: /srv/research\n",
            encoding="utf-8",
        )
        from sibyl.orchestrate import cli_init

        cli_init("Test Topic", "iter-proj")
        output = json.loads(capsys.readouterr().out)
        ws_root = Path(output["workspace_path"])

        assert (ws_root / "current").is_symlink()
        assert (ws_root / "current").resolve() == (ws_root / "iter_001").resolve()
        assert json.loads((ws_root / "status.json").read_text(encoding="utf-8"))["iteration_dirs"] is True
        project_cfg = (ws_root / "config.yaml").read_text(encoding="utf-8")
        assert "ssh_server: persist-box" in project_cfg
        assert "remote_base: /srv/research" in project_cfg

    def test_cli_status_auto_migrates_flat_workspace_when_project_config_prefers_iteration_dirs(
        self, tmp_path, capsys
    ):
        project = tmp_path / "status-migrate-proj"
        (project / "idea").mkdir(parents=True)
        (project / "plan").mkdir(parents=True)
        (project / "status.json").write_text(json.dumps({
            "stage": "planning",
            "started_at": 1000.0,
            "updated_at": 1100.0,
            "iteration": 0,
            "errors": [],
            "paused": False,
            "paused_at": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "iteration_dirs": False,
            "stage_started_at": 1050.0,
        }), encoding="utf-8")
        (project / "config.yaml").write_text("iteration_dirs: true\n", encoding="utf-8")
        (project / "topic.txt").write_text("Topic\n", encoding="utf-8")
        (project / "idea" / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
        (project / "plan" / "methodology.md").write_text("# Method\n", encoding="utf-8")
        from sibyl.orchestrate import cli_status

        cli_status(str(project))
        output = json.loads(capsys.readouterr().out)

        assert output["stage"] == "planning"
        assert json.loads((project / "status.json").read_text(encoding="utf-8"))["iteration_dirs"] is True
        assert (project / "current").is_symlink()
        assert (project / "current" / "idea" / "proposal.md").exists()
        assert (project / "current" / "plan" / "methodology.md").exists()

    def test_orchestrator_normalizes_current_symlink_to_project_root(self, tmp_path):
        ws = Workspace(tmp_path, "iter-proj", iteration_dirs=True)

        o = FarsOrchestrator(str(ws.root / "current"))

        assert o.project_path == str(ws.root)
        assert o.workspace_path == str(ws.root / "current")

    def test_slugify(self):
        assert FarsOrchestrator._slugify("Hello World!") == "hello-world"
        assert FarsOrchestrator._slugify("Test_123") == "test-123"
        assert len(FarsOrchestrator._slugify("x" * 100)) <= 60

    def test_auto_loads_project_config(self, tmp_path, monkeypatch):
        """Orchestrator should auto-load config.yaml from workspace dir."""
        monkeypatch.chdir(tmp_path)
        # Create workspace with a project config.yaml
        ws_dir = tmp_path / "workspaces" / "cfg-proj"
        ws_dir.mkdir(parents=True)
        (ws_dir / "status.json").write_text(
            json.dumps({"stage": "init", "started_at": 1.0, "updated_at": 1.0,
                         "iteration": 0, "errors": [], "paused_at": 0.0,
                         "iteration_dirs": False}),
            encoding="utf-8",
        )
        (ws_dir / "topic.txt").write_text("test", encoding="utf-8")
        (ws_dir / "config.yaml").write_text(
            "ssh_server: my-custom-server\nremote_base: /data/experiments\n",
            encoding="utf-8",
        )
        o = FarsOrchestrator(str(ws_dir))
        assert o.config.ssh_server == "my-custom-server"
        assert o.config.remote_base == "/data/experiments"

    def test_no_project_config_uses_defaults(self, tmp_path, monkeypatch):
        """Without config.yaml, orchestrator should use default Config."""
        monkeypatch.chdir(tmp_path)
        ws_dir = tmp_path / "workspaces" / "no-cfg-proj"
        ws_dir.mkdir(parents=True)
        (ws_dir / "status.json").write_text(
            json.dumps({"stage": "init", "started_at": 1.0, "updated_at": 1.0,
                         "iteration": 0, "errors": [], "paused_at": 0.0,
                         "iteration_dirs": False}),
            encoding="utf-8",
        )
        (ws_dir / "topic.txt").write_text("test", encoding="utf-8")
        o = FarsOrchestrator(str(ws_dir))
        assert o.config.ssh_server == "default"  # default

    def test_project_path_wins_over_config_workspaces_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        actual_root = tmp_path / "custom-root"
        ws = Workspace(actual_root, "path-proj")
        ws.write_file("topic.txt", "test")
        project_cfg = (
            "workspaces_dir: some-other-root\n"
            "ssh_server: project-box\n"
        )
        (ws.root / "config.yaml").write_text(project_cfg, encoding="utf-8")

        o = FarsOrchestrator(str(ws.root))

        assert o.ws.root == ws.root
        assert o.config.ssh_server == "project-box"


# ══════════════════════════════════════════════
# Skill argument contracts
# ══════════════════════════════════════════════

class TestSkillArgContracts:
    def test_literature_skill_args_preserve_topic_spaces(self, make_orchestrator):
        topic = "graph neural networks for molecule generation"
        o = make_orchestrator(stage="literature_search")
        o.ws.write_file("topic.txt", topic)

        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert args == [str(o.ws.root), topic]

    def test_idea_debate_teammates_preserve_topic_spaces(self, make_orchestrator):
        topic = "multi agent planning with language models"
        o = make_orchestrator(stage="idea_debate")
        o.ws.write_file("topic.txt", topic)

        action = o.get_next_action()
        teammate = next(t for t in action["team"]["teammates"] if t["name"] == "innovator")

        assert shlex.split(teammate["args"]) == [str(o.ws.root), topic]

    def test_planner_skill_args_use_explicit_mode(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert args[0] == str(o.ws.root)
        assert args[1] == "plan"
        assert "samples=" in args[2]
        assert "timeout=" in args[2]

    def test_planner_fix_gpu_args_use_explicit_mode(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False,
                              idea_validation_rounds=0)
        o.ws.write_file("plan/task_plan.json", json.dumps({
            "tasks": [{"id": "a", "depends_on": [], "name": "broken"}]
        }))

        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert action["skills"][0]["name"] == "sibyl-planner"
        assert args == [str(o.ws.root), "fix-gpu"]

    def test_experimenter_args_include_remote_env_command(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, compute_backend="ssh")
        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert action["skills"][0]["name"] == "sibyl-experimenter"
        assert args[:5] == [
            str(o.ws.root),
            "PILOT",
            "default",
            o.config.remote_base,
            o.config.get_remote_env_cmd(o.ws.name),
        ]
        assert args[5] == "0,1,2,3"

    def test_server_experimenter_args_include_remote_env_command(self, make_orchestrator):
        o = make_orchestrator(
            stage="pilot_experiments",
            experiment_mode="server_codex",
            gpu_poll_enabled=False,
            compute_backend="ssh",
        )
        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert action["skills"][0]["name"] == "sibyl-server-experimenter"
        assert args[:7] == [
            str(o.ws.root),
            "PILOT",
            "default",
            o.config.remote_base,
            o.config.get_remote_env_cmd(o.ws.name),
            "0,1,2,3",
            "server_codex",
        ]

    def test_server_claude_experimenter_args_include_remote_env_command(self, make_orchestrator):
        o = make_orchestrator(
            stage="pilot_experiments",
            experiment_mode="server_claude",
            gpu_poll_enabled=False,
            compute_backend="ssh",
        )
        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert action["skills"][0]["name"] == "sibyl-server-experimenter"
        assert args[:7] == [
            str(o.ws.root),
            "PILOT",
            "default",
            o.config.remote_base,
            o.config.get_remote_env_cmd(o.ws.name),
            "0,1,2,3",
            "server_claude",
        ]

    def test_section_writer_args_match_skill_contract(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="parallel")
        action = o.get_next_action()
        teammate = next(t for t in action["team"]["teammates"] if t["name"] == "writer-related_work")

        assert shlex.split(teammate["args"]) == [str(o.ws.root), "Related Work", "related_work"]

    def test_section_critic_args_match_skill_contract(self, make_orchestrator):
        o = make_orchestrator(stage="writing_critique")
        action = o.get_next_action()
        teammate = next(t for t in action["team"]["teammates"] if t["name"] == "critic-related_work")

        assert shlex.split(teammate["args"]) == [str(o.ws.root), "Related Work", "related_work"]

    def test_latex_writer_args_preserve_remote_base_spaces(self, make_orchestrator):
        o = make_orchestrator(
            stage="writing_latex",
            remote_base="/tmp/sibyl remote base",
            ssh_server="research-box",
        )
        action = o.get_next_action()
        args = shlex.split(action["skills"][0]["args"])

        assert args == [str(o.ws.root), "research-box", "/tmp/sibyl remote base"]


# ══════════════════════════════════════════════
# Prompt loading
# ══════════════════════════════════════════════

class TestPromptLoading:
    def test_load_existing_prompt(self):
        prompt = load_prompt("_common")
        assert len(prompt) > 0

    def test_load_nonexistent_prompt(self):
        prompt = load_prompt("this_does_not_exist_xyz")
        assert prompt == ""

    def test_load_common_prompt_default_en(self):
        import os
        os.environ.pop("SIBYL_LANGUAGE", None)
        prompt = load_common_prompt()
        assert "本次运行的**控制面语言**使用中文" in prompt
        assert "以下始终必须使用英文" in prompt
        assert "Language Requirement" not in prompt

    def test_load_common_prompt_zh(self):
        import os
        os.environ["SIBYL_LANGUAGE"] = "zh"
        try:
            prompt = load_common_prompt()
            assert "本次运行的**控制面语言**使用中文" in prompt
            assert "以下始终必须使用英文" in prompt
            assert "Language Requirement" not in prompt
        finally:
            os.environ.pop("SIBYL_LANGUAGE", None)

    def test_load_common_prompt_en_explicit(self):
        import os
        os.environ["SIBYL_LANGUAGE"] = "en"
        try:
            prompt = load_common_prompt()
            assert "Use **English** as the control-plane locale" in prompt
        finally:
            os.environ.pop("SIBYL_LANGUAGE", None)

    def test_load_common_prompt_appends_project_memory(self, tmp_path, monkeypatch):
        ws = Workspace(tmp_path, "prompt-proj")
        memory_path = ws.root / ".sibyl" / "project" / "MEMORY.md"
        memory_path.write_text("# Project Memory\n\n- Prefer CIFAR-10 only\n", encoding="utf-8")

        monkeypatch.chdir(ws.root)
        prompt = load_common_prompt()

        assert "Prefer CIFAR-10 only" in prompt

    def test_render_skill_prompt_compiles_shared_runtime_sections(self, tmp_path):
        ws = Workspace(tmp_path, "compiled-prompt-proj")
        prompt = render_skill_prompt("planner", workspace_path=ws.root)
        assert "# Compiled Sibyl Skill Prompt: planner" in prompt
        assert "## Locale Contract" in prompt
        assert "## Workspace Contract" in prompt
        assert "## Role Protocol" in prompt
        assert "Orchestra" in prompt

    def test_render_skill_prompt_includes_experimenter_autonomous_skill_rules(self, tmp_path):
        ws = Workspace(tmp_path, "compiled-exp-prompt-proj")
        prompt = render_skill_prompt("experimenter", workspace_path=ws.root)
        assert "Orchestra Skill Auto-Trigger" in prompt
        assert "vllm" in prompt
        assert "deepspeed" in prompt
        assert "Do not wait for user prompting" in prompt

    def test_render_skill_prompt_includes_supervisor_autonomous_skill_rules(self, tmp_path):
        ws = Workspace(tmp_path, "compiled-supervisor-prompt-proj")
        prompt = render_skill_prompt("experiment_supervisor", workspace_path=ws.root)
        assert "Orchestra Skill Auto-Trigger" in prompt
        assert "experiment-supervisor-notify-main" in prompt
        assert "Do not wait for the main system or user" in prompt

    def test_render_skill_prompt_appends_project_memory(self, tmp_path, monkeypatch):
        ws = Workspace(tmp_path, "compiled-memory-proj")
        memory_path = ws.root / ".sibyl" / "project" / "MEMORY.md"
        memory_path.write_text("# Project Memory\n\n- Prefer CIFAR-10 only\n", encoding="utf-8")

        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("planner", workspace_path=ws.root)

        assert "## Project Constraints" in prompt
        assert "Prefer CIFAR-10 only" in prompt

    def test_render_skill_prompt_appends_project_overlay(self, tmp_path, monkeypatch):
        ws = Workspace(tmp_path, "compiled-overlay-proj")
        overlay_path = ws.root / ".sibyl" / "project" / "prompt_overlays" / "planner.md"
        overlay_path.write_text("Project overlay: reuse the frozen baseline.", encoding="utf-8")

        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("planner", workspace_path=ws.root)

        assert "## Project Overrides" in prompt
        assert "Project overlay: reuse the frozen baseline." in prompt

    def test_load_prompt_appends_project_overlay(self, tmp_path, monkeypatch):
        ws = Workspace(tmp_path, "overlay-proj")
        overlay_path = ws.root / ".sibyl" / "project" / "prompt_overlays" / "planner.md"
        overlay_path.write_text("Project overlay: reuse the frozen baseline.", encoding="utf-8")

        monkeypatch.chdir(ws.root)
        prompt = load_prompt("planner")

        assert "Project overlay: reuse the frozen baseline." in prompt

    def test_load_prompt_uses_contextual_evolution_overlay(self, tmp_path):
        from sibyl.evolution import EvolutionEngine

        ws = Workspace(tmp_path, "context-overlay-proj")
        ws.update_stage("writing_sections")
        ws.write_file("topic.txt", "tighten paper clarity")

        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome(
                "cross-project-a",
                "reflection",
                ["SSH connection failed"],
                5.0,
            )
        for _ in range(3):
            engine.record_outcome(
                "cross-project-b",
                "reflection",
                ["Paper writing clarity issues"],
                6.0,
            )

        prompt = render_skill_prompt("section_writer", workspace_path=ws.root)

        assert "## Evolution Lessons" in prompt
        assert "Paper writing clarity issues" in prompt
        assert "SSH connection failed" not in prompt

    def test_render_control_plane_prompt_compiles_loop(self):
        prompt = render_control_plane_prompt("loop", workspace_path="workspaces/demo")
        assert "# Sibyl Control-Plane Loop" in prompt
        assert "cli_next('workspaces/demo')" in prompt
        assert "sync_requested: true" in prompt
        assert "wake_cmd" in prompt
        assert "requires_main_system=true" in prompt

    def test_render_control_plane_prompt_compiles_ralph(self):
        prompt = render_control_plane_prompt(
            "ralph_loop",
            workspace_path="workspaces/demo",
            project_name="demo",
        )
        assert "# Sibyl Ralph Loop Runtime" in prompt
        assert "Project: `demo`" in prompt
        assert "workspaces/demo/breadcrumb.json" in prompt

    def test_sequential_writer_requires_figures_block(self):
        prompt = load_prompt("sequential_writer")
        assert "<!-- FIGURES" in prompt
        assert "gen_{figure_id}.py" in prompt

    def test_latex_writer_uses_local_official_template(self):
        prompt = load_prompt("latex_writer")
        assert "sibyl/templates/neurips_2024/neurips_2024.tex" in prompt
        assert "sibyl/templates/neurips_2024/neurips_2024.sty" in prompt
        assert Path("sibyl/templates/neurips_2024/neurips_2024.tex").is_file()
        assert Path("sibyl/templates/neurips_2024/neurips_2024.sty").is_file()

    def test_reflection_prompt_defaults_suggested_max_iterations_to_20(self):
        prompt = load_prompt("reflection")
        assert '"suggested_max_iterations": 20' in prompt
        assert "default to `20`" in prompt


class TestResearchFocus:
    """Tests for the research_focus configuration and prompt injection."""

    def test_config_default_is_balanced(self):
        cfg = Config()
        assert cfg.research_focus == 3

    def test_config_from_yaml_reads_research_focus(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("research_focus: 5\n", encoding="utf-8")
        cfg = Config.from_yaml(str(config_file))
        assert cfg.research_focus == 5

    def test_config_rejects_invalid_research_focus(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("research_focus: 0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="research_focus"):
            Config.from_yaml(str(config_file))

    def test_config_rejects_bool_research_focus(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("research_focus: true\n", encoding="utf-8")
        with pytest.raises(ValueError, match="research_focus"):
            Config.from_yaml(str(config_file))

    def test_config_rejects_research_focus_above_5(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("research_focus: 6\n", encoding="utf-8")
        with pytest.raises(ValueError, match="research_focus"):
            Config.from_yaml(str(config_file))

    def test_focus_directive_not_injected_for_balanced(self, tmp_path, monkeypatch):
        """Level 3 (balanced/default) should not inject any focus directive."""
        ws = Workspace(tmp_path, "focus-test")
        config_file = ws.root / "config.yaml"
        config_file.write_text("research_focus: 3\n", encoding="utf-8")
        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("supervisor_decision", workspace_path=ws.root)
        assert "Research Focus Directive" not in prompt

    def test_focus_directive_injected_for_deep_focus(self, tmp_path, monkeypatch):
        """Level 5 should inject DEEP FOCUS directive into supervisor_decision."""
        ws = Workspace(tmp_path, "focus-test")
        config_file = ws.root / "config.yaml"
        config_file.write_text("research_focus: 5\n", encoding="utf-8")
        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("supervisor_decision", workspace_path=ws.root)
        assert "## Research Focus Directive" in prompt
        assert "DEEP FOCUS" in prompt
        assert "Strongly favor PROCEED" in prompt

    def test_focus_directive_injected_for_explore(self, tmp_path, monkeypatch):
        """Level 1 should inject EXPLORE directive into idea_validation_decision."""
        ws = Workspace(tmp_path, "focus-test")
        config_file = ws.root / "config.yaml"
        config_file.write_text("research_focus: 1\n", encoding="utf-8")
        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("idea_validation_decision", workspace_path=ws.root)
        assert "## Research Focus Directive" in prompt
        assert "EXPLORE" in prompt

    def test_focus_directive_injected_for_synthesizer(self, tmp_path, monkeypatch):
        """Level 4 should inject FOCUSED directive into synthesizer."""
        ws = Workspace(tmp_path, "focus-test")
        config_file = ws.root / "config.yaml"
        config_file.write_text("research_focus: 4\n", encoding="utf-8")
        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("synthesizer", workspace_path=ws.root)
        assert "## Research Focus Directive" in prompt
        assert "FOCUSED" in prompt

    def test_focus_directive_not_injected_for_unrelated_agent(self, tmp_path, monkeypatch):
        """Agents not in the focus list should not get the directive."""
        ws = Workspace(tmp_path, "focus-test")
        config_file = ws.root / "config.yaml"
        config_file.write_text("research_focus: 5\n", encoding="utf-8")
        monkeypatch.chdir(ws.root)
        prompt = render_skill_prompt("planner", workspace_path=ws.root)
        assert "Research Focus Directive" not in prompt

    def test_candidate_hint_explore(self, make_orchestrator):
        """Focus 1 should produce a broad candidate pool hint."""
        o = make_orchestrator(stage="idea_debate", research_focus=1)
        action = o.get_next_action()
        assert action["action_type"] == "team"
        prompt = action["team"]["prompt"]
        assert "3-4" in prompt

    def test_candidate_hint_deep_focus(self, make_orchestrator):
        """Focus 5 should produce a focused candidate pool hint."""
        o = make_orchestrator(stage="idea_debate", research_focus=5)
        action = o.get_next_action()
        assert action["action_type"] == "team"
        prompt = action["team"]["prompt"]
        assert "1 front-runner" in prompt

    def test_candidate_hint_balanced_default(self, make_orchestrator):
        """Focus 3 (default) keeps the original 2-3 candidate hint."""
        o = make_orchestrator(stage="idea_debate", research_focus=3)
        action = o.get_next_action()
        assert action["action_type"] == "team"
        prompt = action["team"]["prompt"]
        assert "2-3 serious ideas" in prompt

    def test_commented_yaml_includes_research_focus(self):
        cfg = Config()
        yaml_text = cfg.to_commented_yaml()
        assert "research_focus:" in yaml_text
        assert "explore" in yaml_text
        assert "deep_focus" in yaml_text


class TestMigration:
    def test_migrate_workspace_backfills_layered_scaffold(self, tmp_path, monkeypatch):
        project = tmp_path / "legacy-proj"
        (project / "idea").mkdir(parents=True)
        (project / "status.json").write_text(json.dumps({
            "stage": "done",
            "started_at": 1000.0,
            "updated_at": 1100.0,
            "iteration": 0,
            "errors": [],
        }))
        (project / "idea" / "proposal.md").write_text(
            "# Legacy Topic\n\nSome legacy project notes.\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        result = migrate_workspace(project)

        assert result["runtime"]["migration_needed"] is False
        assert result["runtime"]["runtime_ready"] is True
        assert result["runtime"]["scaffold_ready"] is True
        assert (project / "topic.txt").exists()
        assert (project / "config.yaml").exists()
        assert (project / "spec.md").exists()
        assert (project / ".git").exists()
        assert (project / ".sibyl" / "project" / "MEMORY.md").exists()
        assert (project / "current").is_symlink()
        status = json.loads((project / "status.json").read_text(encoding="utf-8"))
        assert status["iteration"] == 1
        assert status["iteration_dirs"] is True
        assert status["paused"] is False
        assert status["stop_requested"] is False
        assert status["stage_started_at"] == 1100.0

    def test_migrate_workspace_moves_flat_iteration_scoped_dirs_into_current(self, tmp_path, monkeypatch):
        project = tmp_path / "iter-migrate-proj"
        (project / "idea").mkdir(parents=True)
        (project / "exp" / "results").mkdir(parents=True)
        (project / "status.json").write_text(json.dumps({
            "stage": "pilot_experiments",
            "started_at": 1000.0,
            "updated_at": 1100.0,
            "iteration": 0,
            "errors": [],
            "iteration_dirs": False,
        }), encoding="utf-8")
        (project / "config.yaml").write_text("iteration_dirs: true\n", encoding="utf-8")
        (project / "topic.txt").write_text("Topic\n", encoding="utf-8")
        (project / "idea" / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
        (project / "exp" / "results" / "pilot_summary.md").write_text("# Pilot\n", encoding="utf-8")

        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        result = migrate_workspace(project)

        assert (project / "current").is_symlink()
        assert not (project / "idea").exists()
        assert not (project / "exp").exists()
        assert (project / "current" / "idea" / "proposal.md").exists()
        assert (project / "current" / "exp" / "results" / "pilot_summary.md").exists()
        assert any("Moved idea/" in change for change in result["changes"])
        assert any("Moved exp/" in change for change in result["changes"])

    def test_migrate_workspace_flattens_legacy_nested_workspace_dir(self, tmp_path, monkeypatch):
        project = tmp_path / "nested-proj"
        (project / "lark_sync").mkdir(parents=True)
        (project / "remote-data").mkdir(parents=True)
        (project / "status.json").write_text(json.dumps({
            "stage": "reflection",
            "started_at": 1000.0,
            "updated_at": 1200.0,
            "iteration": 1,
            "errors": [],
            "iteration_dirs": False,
        }))
        (project / "topic.txt").write_text("Nested topic\n", encoding="utf-8")
        (project / "lark_sync" / "pending_sync.jsonl").write_text(
            '{"trigger_stage":"review","timestamp":"2026-03-09T08:40:24+00:00","iteration":0}\n',
            encoding="utf-8",
        )
        legacy_dir = project / "nested-proj" / "lark_sync"
        legacy_dir.mkdir(parents=True)
        legacy_dir.joinpath("pending_sync.jsonl").write_text(
            '{"trigger_stage":"writing_integrate","timestamp":"2026-03-09T08:08:12+00:00","iteration":0}\n',
            encoding="utf-8",
        )

        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        result = migrate_workspace(project)

        assert not (project / "nested-proj").exists()
        pending_lines = (project / "lark_sync" / "pending_sync.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert len(pending_lines) == 2
        assert "2026-03-09T08:08:12+00:00" in pending_lines[0]
        assert result["runtime"]["nested_project_dir_exists"] is False
        assert result["warnings"] == []

    def test_migrate_workspace_normalizes_project_config_workspaces_dir(self, tmp_path, monkeypatch):
        project = tmp_path / "config-proj"
        project.mkdir(parents=True)
        (project / "status.json").write_text(json.dumps({
            "stage": "init",
            "started_at": 1000.0,
            "updated_at": 1000.0,
            "iteration": 0,
            "errors": [],
        }))
        (project / "topic.txt").write_text("Config topic\n", encoding="utf-8")
        (project / "config.yaml").write_text(
            "workspaces_dir: workspaces\nssh_server: my-box\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        result = migrate_workspace(project)

        assert "Normalized project config workspaces_dir to workspace parent" in result["changes"]
        stored_config = (project / "config.yaml").read_text(encoding="utf-8")
        assert f"workspaces_dir: {project.parent.resolve()}" in stored_config
        assert "ssh_server: my-box" in stored_config

    def test_collect_dashboard_data_includes_runtime(self, tmp_path):
        ws = Workspace(tmp_path, "dashboard-proj")
        ws.write_file("topic.txt", "Dashboard topic")
        ws.write_file("config.yaml", "language: zh\n")
        ws.write_file("spec.md", "# 项目: dashboard-proj\n\n## 研究主题\nDashboard topic\n")
        (ws.root / ".git").mkdir(exist_ok=True)
        (ws.root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        ws.write_file("logs/events.jsonl", "")

        payload = collect_dashboard_data(ws.root)

        assert payload["status"]["name"] == "dashboard-proj"
        assert payload["runtime"]["runtime_ready"] is True
        assert "stages" in payload

    def test_collect_dashboard_data_does_not_materialize_runtime_scaffold(self, tmp_path):
        proj = tmp_path / "dashboard-bare"
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

        payload = collect_dashboard_data(proj)

        assert payload["status"]["name"] == "dashboard-bare"
        assert payload["runtime"]["runtime_ready"] is False
        assert not (proj / ".sibyl" / "system.json").exists()
        assert not (proj / "CLAUDE.md").exists()


# ══════════════════════════════════════════════
# Experiment parallel scheduling
# ══════════════════════════════════════════════

class TestExperimentParallel:
    def test_no_task_plan_single_agent(self, make_orchestrator):
        """Without task_plan.json, falls back to single-agent mode."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        action = o.get_next_action()
        assert action["action_type"] == "skill"
        assert action["skills"][0]["name"] == "sibyl-experimenter"

    def test_with_task_plan_parallel(self, make_orchestrator):
        """With task_plan.json, spawns parallel experiment skills."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        assert len(action["skills"]) == 2
        # Check --tasks arg is present
        for skill in action["skills"]:
            assert "--tasks=" in skill["args"]

    def test_experiment_loop_stays_in_stage(self, make_orchestrator):
        """When tasks remain, stage loops back to itself."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": ["a"], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        # Mark "a" complete
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": []
        }))
        # "b" is now ready, so stage should loop
        o.record_result("pilot_experiments")
        assert o.ws.get_status().stage == "pilot_experiments"

    def test_experiment_advances_when_all_done(self, make_orchestrator):
        """When all tasks complete, advances to next stage."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False,
                              idea_validation_rounds=0)
        tasks = [{"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10}]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": []
        }))
        o.record_result("pilot_experiments")
        assert o.ws.get_status().stage == "experiment_cycle"

    def test_pilot_to_full_resets_runtime_state_and_allows_rerun(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, max_gpus=2,
                              idea_validation_rounds=0)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a", "b"], "failed": [], "running": {}, "timings": {}
        }))
        o.ws.write_file("exp/results/a_DONE", "{}")
        o.ws.write_file("exp/results/b_DONE", "{}")
        Path(project_marker_file(o.ws.root, "exp_monitor")).write_text("{}", encoding="utf-8")
        Path(project_marker_file(o.ws.root, "gpu_free")).write_text("{}", encoding="utf-8")

        o.record_result("pilot_experiments")

        assert o.ws.get_status().stage == "experiment_cycle"
        assert not o.ws.active_path("exp/gpu_progress.json").exists()
        assert not o.ws.active_path("exp/results/a_DONE").exists()
        assert not o.ws.active_path("exp/results/b_DONE").exists()
        assert not Path(project_marker_file(o.ws.root, "exp_monitor")).exists()
        assert not Path(project_marker_file(o.ws.root, "gpu_free")).exists()

        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        assert len(action["skills"]) == 2

    def test_experiment_cycle_parallel(self, make_orchestrator):
        """experiment_cycle also supports parallel scheduling."""
        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        tasks = [
            {"id": "x", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "y", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "z", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        assert len(action["skills"]) == 3

    def test_gpu_progress_cleared_on_new_iteration(self, make_orchestrator):
        """gpu_progress.json should be cleared between iterations."""
        o = make_orchestrator(stage="quality_gate", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 5.0\n")
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": []
        }))
        o.record_result("quality_gate")
        assert not (o.ws.root / "exp/gpu_progress.json").exists()

    def test_server_experimenter_with_tasks(self, make_orchestrator):
        """Server experiment mode also supports --tasks."""
        o = make_orchestrator(stage="pilot_experiments",
                              experiment_mode="server_codex",
                              gpu_poll_enabled=False)
        tasks = [{"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10}]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["skills"][0]["name"] == "sibyl-server-experimenter"
        assert "--tasks=a" in action["skills"][0]["args"]

    def test_gpus_per_task_config(self, make_orchestrator):
        """gpus_per_task controls GPU allocation per experiment task."""
        o = make_orchestrator(stage="pilot_experiments", gpus_per_task=2,
                              gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 2, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 2, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        # With 4 GPUs and 2 per task, should get 2 parallel tasks
        assert len(action["skills"]) == 2

    def test_per_task_gpu_count(self, make_orchestrator):
        """Tasks with per-task gpu_count override the default.
        Smallest-first: b(1 GPU) before a(2 GPUs)."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False,
                              idea_validation_rounds=0)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 2, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        assert len(action["skills"]) == 2
        # Smallest-first: b(1 GPU) then a(2 GPUs)
        assert "--tasks=b" in action["skills"][0]["args"]
        assert "--tasks=a" in action["skills"][1]["args"]

    def test_estimated_minutes_in_action(self, make_orchestrator):
        """Action should include estimated_minutes from task plan."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 30},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 90},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["estimated_minutes"] == 90  # max of batch
        assert "90min" in action["description"]

    def test_experiment_monitor_included(self, make_orchestrator):
        """Experiment action should include monitor config for background tracking."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "task_1a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 30},
            {"id": "task_1b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        monitor = action.get("experiment_monitor")
        assert monitor is not None
        assert "script" in monitor
        assert "task_1a" in monitor["script"]
        assert "task_1b" in monitor["script"]
        assert monitor["marker_file"] == project_marker_file(o.ws.root, "exp_monitor")
        assert set(monitor["task_ids"]) == {"task_1a", "task_1b"}
        assert monitor["timeout_minutes"] >= 30  # at least 30 min
        assert "experiment-supervisor-drain-wake" in monitor["wake_cmd"]
        assert monitor["wake_check_interval_sec"] == 90
        # Default: no background_agent (bash daemon via hook instead)
        assert "background_agent" not in monitor

    def test_experiment_monitor_includes_supervisor_when_enabled(self, make_orchestrator):
        """When supervisor_enabled=True, background_agent is included."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, supervisor_enabled=True)
        tasks = [
            {"id": "task_1a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 30},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        monitor = action.get("experiment_monitor")
        assert monitor is not None
        assert monitor["background_agent"]["name"] == "sibyl-experiment-supervisor"
        assert shlex.quote(str(o.ws.active_root)) in monitor["background_agent"]["args"]

    def test_incomplete_task_plan_redirects_to_planner(self, make_orchestrator):
        """Tasks missing gpu_count/estimated_minutes should trigger planner fix."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": [], "gpu_count": 1},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skill"
        assert action["skills"][0]["name"] == "sibyl-planner"
        assert "fix-gpu" in action["skills"][0]["args"]
        assert "gpu_count" in action["description"] or "estimated_minutes" in action["description"]

    def test_no_task_plan_zero_estimated_minutes(self, make_orchestrator):
        """Without task_plan, estimated_minutes defaults to 0."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        action = o.get_next_action()
        assert action["estimated_minutes"] == 0
        assert "experiment-supervisor-drain-wake" in action["experiment_monitor"]["wake_cmd"]
        # Default: no background_agent (supervisor_enabled=False)
        assert "background_agent" not in action["experiment_monitor"]


# ══════════════════════════════════════════════
# GPU polling integration (orchestrator)
# ══════════════════════════════════════════════

class TestGpuPollingIntegration:
    """Test GPU polling path in _action_experiment_batch."""

    @pytest.fixture(autouse=True)
    def _clean_poll_marker(self, tmp_path):
        """Ensure project-scoped GPU poll markers do not leak between tests."""
        marker = Path(project_marker_file(tmp_path / "test-proj", "gpu_free"))
        marker.unlink(missing_ok=True)
        yield
        marker.unlink(missing_ok=True)

    def test_poll_enabled_no_result_returns_gpu_poll(self, make_orchestrator):
        """When gpu_poll_enabled=True and no poll result, returns gpu_poll action."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        action = o.get_next_action()
        assert action["action_type"] == "gpu_poll"
        assert action["gpu_poll"] is not None
        # Local backend returns "" for ssh_connection; SSH backend returns the server name
        assert action["gpu_poll"]["ssh_connection"] == ""
        assert action["gpu_poll"]["marker_file"] == project_marker_file(o.ws.root, "gpu_free")
        assert "nvidia-smi" in action["gpu_poll"]["query_cmd"]
        assert action["gpu_poll"]["max_gpus"] == 4
        assert "轮询" in action["description"]
        assert action["stage"] == "pilot_experiments"

    def test_poll_enabled_with_result_uses_free_gpus(self, make_orchestrator, tmp_path):
        """When poll result exists, uses free GPUs for scheduling."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        marker = Path(project_marker_file(o.ws.root, "gpu_free"))
        marker.write_text(json.dumps({"free_gpus": [0, 2], "poll_count": 3}))
        try:
            tasks = [
                {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
                {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            ]
            o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
            action = o.get_next_action()
            assert action["action_type"] == "skills_parallel"
            assert len(action["skills"]) == 2
            # Should use GPUs 0 and 2 (from poll), not 0,1,2,3 (from config)
            assert "0" in action["skills"][0]["args"]
            assert "2" in action["skills"][1]["args"]
        finally:
            marker.unlink(missing_ok=True)

    def test_poll_enabled_with_result_single_agent_fallback(self, make_orchestrator):
        """Poll result + no task plan → single agent with free GPUs."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        marker = Path(project_marker_file(o.ws.root, "gpu_free"))
        marker.write_text(json.dumps({"free_gpus": [1, 3], "poll_count": 5}))
        try:
            action = o.get_next_action()
            assert action["action_type"] == "skill"
            assert action["skills"][0]["name"] == "sibyl-experimenter"
            # Should use free GPUs 1,3
            assert "1,3" in action["skills"][0]["args"]
        finally:
            marker.unlink(missing_ok=True)

    def test_poll_result_capped_by_max_gpus(self, make_orchestrator):
        """Free GPUs are capped by max_gpus config."""
        o = make_orchestrator(
            stage="pilot_experiments", gpu_poll_enabled=True,
            max_gpus=2,
        )
        marker = Path(project_marker_file(o.ws.root, "gpu_free"))
        # Poll found 4 free GPUs but max_gpus=2
        marker.write_text(json.dumps({"free_gpus": [2, 4, 5, 7], "poll_count": 2}))
        try:
            # No task plan → single agent fallback, uses first 2 free GPUs
            action = o.get_next_action()
            assert action["action_type"] == "skill"
            # Should use GPUs 2,4 (first 2 of the free list)
            assert "2,4" in action["skills"][0]["args"]
        finally:
            marker.unlink(missing_ok=True)

    def test_poll_disabled_uses_sequential_gpus(self, make_orchestrator):
        """When gpu_poll_enabled=False, uses GPUs 0..max_gpus-1."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skill"
        # Default max_gpus=4 → uses GPUs 0,1,2,3 sequentially, task gets GPU 0
        assert "0" in action["skills"][0]["args"]

    def test_poll_action_includes_config_params(self, make_orchestrator):
        """Poll action includes config parameters in gpu_poll dict."""
        o = make_orchestrator(
            stage="experiment_cycle",
            gpu_poll_enabled=True,
            gpu_free_threshold_mb=4000,
            gpu_poll_interval_sec=30,
            ssh_server="myserver",
        )
        action = o.get_next_action()
        assert action["action_type"] == "gpu_poll"
        poll = action["gpu_poll"]
        assert poll["threshold_mb"] == 4000
        assert poll["interval_sec"] == 30
        assert "nvidia-smi" in poll["query_cmd"]

    def test_poll_action_exposes_finite_wait_script(self, make_orchestrator):
        """Finite GPU polling must be encoded in the executable action contract."""
        o = make_orchestrator(
            stage="experiment_cycle",
            gpu_poll_enabled=True,
            gpu_poll_interval_sec=30,
            gpu_poll_max_attempts=3,
            max_gpus=2,
        )
        action = o.get_next_action()

        assert action["action_type"] == "gpu_poll"
        poll = action["gpu_poll"]
        assert poll["max_attempts"] == 3
        assert "seq 1 3" in poll["script"]
        assert "Timeout after 3 polls" in poll["script"]
        assert "最多 3 次" in action["description"]

    def test_poll_experiment_cycle_also_polls(self, make_orchestrator):
        """experiment_cycle stage also uses GPU polling when enabled."""
        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=True)
        action = o.get_next_action()
        assert action["action_type"] == "gpu_poll"
        assert action["gpu_poll"] is not None

    def test_poll_result_empty_free_gpus_repolls(self, make_orchestrator):
        """If poll result has empty free_gpus list → re-poll."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        marker = Path(project_marker_file(o.ws.root, "gpu_free"))
        marker.write_text(json.dumps({"free_gpus": [], "poll_count": 1}))
        try:
            action = o.get_next_action()
            # Empty free_gpus → no match with config → re-poll
            assert action["action_type"] == "gpu_poll"
        finally:
            marker.unlink(missing_ok=True)


# ══════════════════════════════════════════════
# Checkpoint integration
# ══════════════════════════════════════════════

class TestCheckpointIntegration:
    """Test checkpoint-aware action generation."""

    def test_writing_sections_parallel_creates_checkpoint(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="parallel")
        action = o.get_next_action()
        assert action["action_type"] == "team"
        cp = o.ws.load_checkpoint("writing/sections")
        assert cp is not None
        assert len(cp["steps"]) == 6
        assert action["checkpoint_info"] is not None

    def test_writing_sections_resumes_from_checkpoint(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections", writing_mode="parallel")
        iteration = o.ws.get_status().iteration
        steps = {sid: f"writing/sections/{sid}.md" for sid, _ in PAPER_SECTIONS}
        o.ws.create_checkpoint("writing_sections", "writing/sections", steps, iteration=iteration)
        for sid in ["intro", "related_work", "method"]:
            o.ws.write_file(f"writing/sections/{sid}.md", f"# {sid}\n" * 50)
            o.ws.complete_checkpoint_step("writing/sections", sid)
        action = o.get_next_action()
        assert action["action_type"] == "team"
        cp_info = action["checkpoint_info"]
        assert cp_info is not None
        assert cp_info["resuming"] is True
        assert set(cp_info["completed_steps"]) == {"intro", "related_work", "method"}
        assert len(cp_info["remaining_steps"]) == 3
        # Only remaining teammates should be spawned
        assert len(action["team"]["teammates"]) == 3

    def test_writing_critique_creates_checkpoint(self, make_orchestrator):
        o = make_orchestrator(stage="writing_critique")
        action = o.get_next_action()
        assert action["action_type"] == "team"
        cp = o.ws.load_checkpoint("writing/critique")
        assert cp is not None
        assert len(cp["steps"]) == 6

    def test_idea_debate_creates_checkpoint(self, make_orchestrator):
        o = make_orchestrator(stage="idea_debate")
        action = o.get_next_action()
        assert action["action_type"] == "team"
        cp = o.ws.load_checkpoint("idea")
        assert cp is not None
        assert len(cp["steps"]) == 6

    def test_result_debate_creates_checkpoint(self, make_orchestrator):
        o = make_orchestrator(stage="result_debate")
        action = o.get_next_action()
        assert action["action_type"] == "team"
        cp = o.ws.load_checkpoint("idea/result_debate")
        assert cp is not None
        assert len(cp["steps"]) == 6

    def test_all_steps_complete_returns_all_complete(self, make_orchestrator):
        """If all checkpoint steps valid, action indicates stage is complete."""
        o = make_orchestrator(stage="writing_sections", writing_mode="parallel")
        iteration = o.ws.get_status().iteration
        steps = {sid: f"writing/sections/{sid}.md" for sid, _ in PAPER_SECTIONS}
        o.ws.create_checkpoint("writing_sections", "writing/sections", steps, iteration=iteration)
        for sid, _ in PAPER_SECTIONS:
            o.ws.write_file(f"writing/sections/{sid}.md", f"# {sid}\n" * 50)
            o.ws.complete_checkpoint_step("writing/sections", sid)
        action = o.get_next_action()
        assert action["checkpoint_info"]["all_complete"] is True

    def test_clear_iteration_artifacts_clears_checkpoints(self, make_orchestrator):
        o = make_orchestrator(stage="writing_sections")
        steps = {"intro": "writing/sections/intro.md"}
        o.ws.create_checkpoint("writing_sections", "writing/sections", steps, iteration=0)
        o._clear_iteration_artifacts()
        assert o.ws.has_checkpoint("writing/sections") is False
        assert o.ws.has_checkpoint("writing/critique") is False
        assert o.ws.has_checkpoint("idea") is False
        assert o.ws.has_checkpoint("idea/result_debate") is False

    def test_sequential_writing_has_checkpoint_info(self, make_orchestrator):
        """Sequential writing mode also gets checkpoint info."""
        o = make_orchestrator(stage="writing_sections", writing_mode="sequential")
        action = o.get_next_action()
        assert action["action_type"] == "skill"
        assert action["checkpoint_info"] is not None
        cp = o.ws.load_checkpoint("writing/sections")
        assert cp is not None

    def test_writing_sections_cli_checkpoint_requires_visual_artifacts(
        self, make_orchestrator, capsys
    ):
        o = make_orchestrator(stage="writing_sections")
        steps = {"intro": "writing/sections/intro.md"}
        o.ws.create_checkpoint("writing_sections", "writing/sections", steps, iteration=0)
        o.ws.write_file(
            "writing/sections/intro.md",
            (
                "# Intro\n\n"
                "<!-- FIGURES\n"
                "- Figure 1: gen_intro_plot.py, intro_plot.pdf — Main teaser plot\n"
                "-->\n"
            ),
        )

        cli_checkpoint(str(o.ws.root), "writing_sections", "intro")
        result = json.loads(capsys.readouterr().out)

        assert result["status"] == "ok"
        assert result["completed"] is False
        assert set(result["missing_files"]) == {
            "writing/figures/gen_intro_plot.py",
            "writing/figures/intro_plot.pdf",
        }
        cp = o.ws.load_checkpoint("writing/sections")
        assert cp["steps"]["intro"]["status"] == "pending"


class TestCliCheckpoint:
    def test_cli_checkpoint_marks_step(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="writing_sections")
        steps = {"intro": "writing/sections/intro.md"}
        o.ws.create_checkpoint("writing_sections", "writing/sections", steps, iteration=0)
        o.ws.write_file(
            "writing/sections/intro.md",
            (
                "# Introduction\n\n"
                "<!-- FIGURES\n"
                "- None\n"
                "-->\n"
            ),
        )
        cli_checkpoint(str(o.ws.root), "writing_sections", "intro")
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "ok"
        assert result["step"] == "intro"
        assert result["completed"] is True
        cp = o.ws.load_checkpoint("writing/sections")
        assert cp["steps"]["intro"]["status"] == "completed"

    def test_cli_checkpoint_unsupported_stage(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="planning")
        cli_checkpoint(str(o.ws.root), "planning", "some_step")
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "error"


# ══════════════════════════════════════════════
# Dynamic GPU dispatch
# ══════════════════════════════════════════════

class TestDynamicGpuDispatch:
    """Test dynamic GPU dispatch during experiment monitoring."""

    def _write_task_plan(self, ws, tasks):
        ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

    def _write_progress(self, ws, completed=None, running=None, timings=None):
        ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": completed or [],
            "failed": [],
            "running": running or {},
            "timings": timings or {},
        }))

    def _write_config(self, ws, **overrides):
        """Write a config.yaml so cli_dispatch_tasks picks up test settings."""
        import yaml
        config = {
            "gpu_poll_enabled": False,
            "max_gpus": 4,
            "workspaces_dir": str(ws.root.parent),
        }
        config.update(overrides)
        ws.write_file("config.yaml", yaml.dump(config))

    def test_dispatch_returns_new_tasks(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, max_gpus=4)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "c", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_config(o.ws)
        # a and b are running, c is free
        self._write_progress(o.ws, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
            "b": {"gpu_ids": [1], "started_at": "2026-01-01"},
        })
        payload = cli_dispatch_tasks(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert payload == result
        assert len(result["dispatch"]) == 1
        assert result["dispatch"][0]["task_ids"] == ["c"]
        assert len(result["skills"]) == 1

    def test_dispatch_no_free_gpus(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, max_gpus=2)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "c", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_config(o.ws, max_gpus=2)
        self._write_progress(o.ws, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
            "b": {"gpu_ids": [1], "started_at": "2026-01-01"},
        })
        cli_dispatch_tasks(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["dispatch"] == []
        assert result["reason"] == "no_free_gpus"

    def test_dispatch_all_done(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, max_gpus=4)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_config(o.ws)
        self._write_progress(o.ws, completed=["a"])
        cli_dispatch_tasks(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["dispatch"] == []
        assert result["reason"] == "all_done"

    def test_dispatch_not_experiment_stage(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="planning")
        self._write_config(o.ws)
        cli_dispatch_tasks(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["dispatch"] == []
        assert result["reason"] == "not_experiment_stage"

    def test_dispatch_registers_new_running(self, make_orchestrator, capsys):
        from sibyl.experiment_recovery import load_experiment_state

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False, max_gpus=4)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_config(o.ws)
        self._write_progress(o.ws, completed=["a"])
        cli_dispatch_tasks(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert len(result["dispatch"]) == 1
        assert result["dispatch"][0]["task_ids"] == ["b"]
        # Verify b is now registered as running
        progress = json.loads(o.ws.read_file("exp/gpu_progress.json"))
        assert "b" in progress["running"]
        state = load_experiment_state(o.ws.active_root)
        assert state.tasks["b"]["status"] == "running"
        assert state.tasks["b"]["pid_file"].endswith("/exp/results/b.pid")

    def test_dispatch_prefers_project_scoped_poll_marker(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True, max_gpus=4)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_config(o.ws, gpu_poll_enabled=True, max_gpus=4)
        legacy_marker = Path("/tmp/sibyl_gpu_free.json")
        scoped_marker = Path(project_marker_file(o.ws.root, "gpu_free"))
        legacy_marker.write_text(json.dumps({"free_gpus": [7], "poll_count": 1}), encoding="utf-8")
        scoped_marker.write_text(json.dumps({"free_gpus": [2], "poll_count": 3}), encoding="utf-8")
        try:
            cli_dispatch_tasks(str(o.ws.root))
            captured = capsys.readouterr()
            result = json.loads(captured.out)
            assert len(result["dispatch"]) == 1
            args = shlex.split(result["skills"][0]["args"])
            assert args[5] == "2"
        finally:
            legacy_marker.unlink(missing_ok=True)
            scoped_marker.unlink(missing_ok=True)

    def test_dispatch_iteration_dirs_uses_active_workspace(self, make_orchestrator, capsys):
        o = make_orchestrator(
            stage="pilot_experiments",
            gpu_poll_enabled=False,
            max_gpus=4,
            iteration_dirs=True,
        )
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "c", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_config(o.ws)
        self._write_progress(o.ws, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
            "b": {"gpu_ids": [1], "started_at": "2026-01-01"},
        })

        # Write stale project-root state that should be ignored in iteration_dirs mode.
        root_plan = o.ws.root / "plan"
        root_plan.mkdir(parents=True, exist_ok=True)
        (root_plan / "task_plan.json").write_text(json.dumps({
            "tasks": [{"id": "stale", "depends_on": [], "gpu_count": 1, "estimated_minutes": 5}]
        }), encoding="utf-8")
        root_exp = o.ws.root / "exp"
        root_exp.mkdir(parents=True, exist_ok=True)
        (root_exp / "gpu_progress.json").write_text(json.dumps({
            "completed": ["stale"],
            "failed": [],
            "running": {},
            "timings": {},
        }), encoding="utf-8")

        cli_dispatch_tasks(str(o.ws.root))
        result = json.loads(capsys.readouterr().out)

        assert len(result["dispatch"]) == 1
        assert result["dispatch"][0]["task_ids"] == ["c"]
        args = shlex.split(result["skills"][0]["args"])
        assert args[:2] == [str(o.ws.root / "current"), "PILOT"]

        active_progress = json.loads((o.ws.root / "current" / "exp" / "gpu_progress.json").read_text(encoding="utf-8"))
        assert "c" in active_progress["running"]
        root_progress = json.loads((o.ws.root / "exp" / "gpu_progress.json").read_text(encoding="utf-8"))
        assert root_progress["running"] == {}


class TestExperimentStageWithRunning:
    """Test that _natural_next_stage waits for running tasks."""

    def _write_task_plan(self, ws, tasks):
        ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

    def _write_progress(self, ws, completed=None, running=None):
        ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": completed or [],
            "failed": [],
            "running": running or {},
            "timings": {},
        }))

    def test_stays_in_stage_while_tasks_running(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_progress(o.ws, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
        })
        next_stage, _ = o._natural_next_stage("pilot_experiments")
        assert next_stage == "pilot_experiments"  # stays because task still running

    def test_advances_when_no_running_no_remaining(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False,
                              idea_validation_rounds=0)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_task_plan(o.ws, tasks)
        self._write_progress(o.ws, completed=["a"])
        next_stage, _ = o._natural_next_stage("pilot_experiments")
        assert next_stage == "experiment_cycle"  # all done, advance


class TestExperimentBatchRegistersRunning:
    """Test that _action_experiment_batch registers tasks in running map."""

    def test_batch_action_registers_running(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, max_gpus=2)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] in ("skill", "skills_parallel")
        # Verify tasks are registered as running
        progress = json.loads(o.ws.read_file("exp/gpu_progress.json"))
        assert "a" in progress["running"]
        assert "b" in progress["running"]

    def test_batch_action_includes_dynamic_dispatch(self, make_orchestrator):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False, max_gpus=2)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["experiment_monitor"] is not None
        assert action["experiment_monitor"]["dynamic_dispatch"] is True
        assert "dispatch_cmd" in action["experiment_monitor"]

    def test_batch_action_dispatch_cmd_uses_active_workspace(self, make_orchestrator):
        o = make_orchestrator(
            stage="pilot_experiments",
            gpu_poll_enabled=False,
            max_gpus=1,
            iteration_dirs=True,
        )
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()

        dispatch_cmd = action["experiment_monitor"]["dispatch_cmd"]
        assert shlex.quote(sys.executable) in dispatch_cmd
        assert "-m sibyl.cli dispatch" in dispatch_cmd
        assert shlex.quote(str(o.ws.root / "current")) in dispatch_cmd
        assert "cli_dispatch_tasks(" not in dispatch_cmd


class TestSelfHealMonitorScript:
    def test_self_heal_monitor_script_uses_project_scoped_status_and_cli(self):
        workspace = "/tmp/demo dir/it's ok"

        script = self_heal_monitor_script(workspace, interval_sec=60)

        expected_status_file = project_marker_file(workspace, "self_heal_monitor")
        assert f"WORKSPACE={shlex.quote(workspace)}" in script
        assert f"STATUS_FILE={shlex.quote(expected_status_file)}" in script
        assert "-m sibyl.cli self-heal-scan" in script
        assert shlex.quote(sys.executable) in script
        assert "cli_self_heal_scan(" not in script


# ══════════════════════════════════════════════
# Experiment status display
# ══════════════════════════════════════════════

class TestExperimentStatusDisplay:
    """Test cli_experiment_status rich output."""

    def test_status_with_workspace(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "task_a", "name": "Train baseline", "depends_on": [],
             "gpu_count": 1, "estimated_minutes": 30},
            {"id": "task_b", "name": "Train variant", "depends_on": [],
             "gpu_count": 1, "estimated_minutes": 20},
            {"id": "task_c", "name": "Evaluate", "depends_on": ["task_a", "task_b"],
             "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["task_a"],
            "failed": [],
            "running": {
                "task_b": {"gpu_ids": [1], "started_at": "2026-03-09T12:00:00"},
            },
            "timings": {},
        }))
        payload = cli_experiment_status(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert payload == result
        assert result["completed_count"] == 1
        assert result["running_count"] == 1
        assert result["pending_count"] == 1
        assert result["total_tasks"] == 3
        assert "display" in result
        assert "Experiment Monitor" in result["display"]
        assert "1/3" in result["display"]
        assert "Train variant" in result["display"]
        assert "please wait" in result["display"]

    def test_status_with_workspace_prefers_project_scoped_monitor(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        legacy_marker = Path("/tmp/sibyl_exp_monitor.json")
        scoped_marker = Path(project_marker_file(o.ws.root, "exp_monitor"))
        legacy_marker.write_text(json.dumps({"status": "timeout"}), encoding="utf-8")
        scoped_marker.write_text(
            json.dumps({"status": "monitoring", "elapsed_sec": 120, "completed": [], "pending": []}),
            encoding="utf-8",
        )
        try:
            cli_experiment_status(str(o.ws.root))
            captured = capsys.readouterr()
            result = json.loads(captured.out)
            assert result["status"] == "monitoring"
            assert result["elapsed_min"] == 2
        finally:
            legacy_marker.unlink(missing_ok=True)
            scoped_marker.unlink(missing_ok=True)

    def test_status_iteration_dirs_reads_active_iteration_files(self, make_orchestrator, capsys):
        o = make_orchestrator(
            stage="pilot_experiments",
            gpu_poll_enabled=False,
            iteration_dirs=True,
        )
        tasks = [
            {"id": "task_a", "name": "Train baseline", "depends_on": [],
             "gpu_count": 1, "estimated_minutes": 30},
            {"id": "task_b", "name": "Train variant", "depends_on": [],
             "gpu_count": 1, "estimated_minutes": 20},
            {"id": "task_c", "name": "Evaluate", "depends_on": ["task_a", "task_b"],
             "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["task_a"],
            "failed": [],
            "running": {
                "task_b": {"gpu_ids": [1], "started_at": "2026-03-09T12:00:00"},
            },
            "timings": {},
        }))

        # Stale project-root progress should not leak into the panel.
        (o.ws.root / "plan").mkdir(parents=True, exist_ok=True)
        (o.ws.root / "plan" / "task_plan.json").write_text(json.dumps({
            "tasks": [{"id": "stale", "depends_on": [], "gpu_count": 1, "estimated_minutes": 5}]
        }), encoding="utf-8")
        (o.ws.root / "exp").mkdir(parents=True, exist_ok=True)
        (o.ws.root / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": [],
            "failed": [],
            "running": {},
            "timings": {},
        }), encoding="utf-8")

        cli_experiment_status(str(o.ws.root))
        result = json.loads(capsys.readouterr().out)

        assert result["completed_count"] == 1
        assert result["running_count"] == 1
        assert result["pending_count"] == 1
        assert result["total_tasks"] == 3
        assert "Train variant" in result["display"]

    def test_status_without_workspace(self, capsys, tmp_path):
        """Without workspace path, returns basic monitor status (no display)."""
        # Remove any leftover monitor file from other tests
        import os
        monitor_path = "/tmp/sibyl_exp_monitor.json"
        if os.path.exists(monitor_path):
            os.unlink(monitor_path)
        cli_experiment_status()
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "workspace_required"
        assert "workspace_path is required" in result["error"]

    def test_status_all_complete(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": [], "running": {}, "timings": {},
        }))
        cli_experiment_status(str(o.ws.root))
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["completed_count"] == 1
        assert result["running_count"] == 0
        assert result["pending_count"] == 0

    def test_record_gpu_poll_updates_project_scoped_marker(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True, max_gpus=4)
        cli_record_gpu_poll(
            str(o.ws.root),
            "0, 500, 24576\n1, 18000, 24576\n2, 100, 24576\n",
        )
        result = json.loads(capsys.readouterr().out)
        assert result["free_gpus"] == [0, 2]
        marker = json.loads(Path(project_marker_file(o.ws.root, "gpu_free")).read_text(encoding="utf-8"))
        assert marker["snapshot"][0]["gpu_id"] == 0
        assert marker["source"] == "experiment_supervisor"

    def test_experiment_supervisor_claim_heartbeat_release(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        owner = "exp-supervisor-test"

        cli_experiment_supervisor_claim(str(o.ws.root), owner, stale_after_sec=900)
        claimed = json.loads(capsys.readouterr().out)
        assert claimed["should_start"] is True

        cli_experiment_supervisor_heartbeat(
            str(o.ws.root),
            owner,
            summary="monitoring",
            actions_json='["dispatch"]',
            recommendations_json='["keep GPUs busy"]',
        )
        heartbeat = json.loads(capsys.readouterr().out)
        assert heartbeat["status"] == "ok"

        cli_experiment_supervisor_snapshot(str(o.ws.root))
        snapshot = json.loads(capsys.readouterr().out)
        assert snapshot["supervisor_state"]["owner_id"] == owner
        assert "drift" in snapshot

        cli_experiment_supervisor_release(str(o.ws.root), owner, final_status="idle", summary="done")
        released = json.loads(capsys.readouterr().out)
        assert released["status"] == "released"

    def test_experiment_supervisor_notify_and_drain_wake(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        owner = "exp-supervisor-test"

        cli_experiment_supervisor_claim(str(o.ws.root), owner, stale_after_sec=900)
        _ = json.loads(capsys.readouterr().out)

        cli_experiment_supervisor_notify_main(
            str(o.ws.root),
            owner,
            kind="needs_main_system",
            summary="task_a stuck after retries",
            details_json='{"task_id":"task_a","attempts":3}',
            actions_json='["checked progress","requeued once"]',
            recommendations_json='["planner should split task"]',
            urgency="critical",
            requires_main_system=True,
        )
        queued = json.loads(capsys.readouterr().out)
        assert queued["wake_requested"] is True
        assert queued["queue_depth"] == 1

        cli_experiment_supervisor_snapshot(str(o.ws.root))
        snapshot = json.loads(capsys.readouterr().out)
        assert snapshot["main_wake_queue_depth"] == 1
        assert snapshot["drift"]["pending_main_wake"] is True

        cli_experiment_supervisor_drain_wake(str(o.ws.root))
        drained = json.loads(capsys.readouterr().out)
        assert drained["wake_requested"] is True
        assert drained["requires_main_system"] is True
        assert drained["events"][0]["kind"] == "needs_main_system"
        assert drained["events"][0]["details"]["task_id"] == "task_a"

        cli_experiment_supervisor_drain_wake(str(o.ws.root))
        drained_again = json.loads(capsys.readouterr().out)
        assert drained_again["wake_requested"] is False
        assert drained_again["event_count"] == 0

    def test_requeue_experiment_task_clears_running_and_keeps_retryable(self, make_orchestrator, capsys):
        from sibyl.experiment_recovery import ExperimentState, register_task, save_experiment_state
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        state = ExperimentState()
        register_task(state, "task_a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"task_a": [0]})

        cli_requeue_experiment_task(str(o.ws.root), "task_a", reason="stalled")
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "ok"

        progress = json.loads((o.ws.active_root / "exp" / "gpu_progress.json").read_text(encoding="utf-8"))
        assert "task_a" not in progress["running"]
        assert "task_a" in progress["failed"]


class TestExperimentStateIntegration:
    def test_experiment_batch_registers_in_experiment_state(self, make_orchestrator):
        from sibyl.experiment_recovery import load_experiment_state
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.get_next_action()
        state = load_experiment_state(o.ws.active_root)
        assert "a" in state.tasks
        assert "b" in state.tasks
        assert state.tasks["a"]["status"] == "running"

    def test_experiment_batch_auto_recovers_completed(self, make_orchestrator):
        from sibyl.experiment_recovery import (
            load_experiment_state, save_experiment_state, register_task as register_exp_task,
            ExperimentState,
        )
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        # Pre-populate: experiment_state says both running
        state = ExperimentState()
        register_exp_task(state, "a", gpu_ids=[0])
        register_exp_task(state, "b", gpu_ids=[1])
        save_experiment_state(o.ws.active_root, state)

        # gpu_progress says "a" completed
        from sibyl.gpu_scheduler import register_running_tasks
        register_running_tasks(o.ws.active_root, {"a": [0], "b": [1]})
        progress_path = o.ws.active_path("exp/gpu_progress.json")
        progress = json.loads(progress_path.read_text())
        progress["completed"] = ["a"]
        del progress["running"]["a"]
        progress_path.write_text(json.dumps(progress))

        action = o.get_next_action()
        assert action["stage"] == "pilot_experiments"

        # Verify experiment_state was updated
        updated = load_experiment_state(o.ws.active_root)
        assert updated.tasks["a"]["status"] == "completed"


# ══════════════════════════════════════════════
# experiment_wait action for running experiments
# ══════════════════════════════════════════════


class TestExperimentWaitAction:
    """Verify that experiment_wait is returned when experiments are running."""

    def test_returns_experiment_wait_when_all_tasks_running(self, make_orchestrator):
        """When all tasks are running and no pending tasks, return experiment_wait."""
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 120},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        # Both tasks already running
        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        register_task(state, "b", gpu_ids=[1])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0], "b": [1]})

        action = o.get_next_action()
        assert action["action_type"] == "experiment_wait"
        assert action["stage"] == "experiment_cycle"
        assert "experiment_monitor" in action
        assert action["experiment_monitor"]["poll_interval_sec"] > 0
        assert "check_cmd" in action["experiment_monitor"]
        assert "status_cmd" in action["experiment_monitor"]
        assert "wake_cmd" in action["experiment_monitor"]
        assert action["experiment_monitor"]["wake_check_interval_sec"] == 90
        # Default: no background_agent (supervisor_enabled=False)
        assert "background_agent" not in action["experiment_monitor"]

    def test_experiment_wait_adaptive_interval_short(self, make_orchestrator):
        """Short remaining time → 2min poll interval."""
        import datetime
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 20},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        # Started 10 min ago → 10 min remaining
        state.tasks["a"]["started_at"] = (
            datetime.datetime.now() - datetime.timedelta(minutes=10)
        ).isoformat()
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0]})

        action = o.get_next_action()
        assert action["action_type"] == "experiment_wait"
        assert action["experiment_monitor"]["poll_interval_sec"] == 120  # 2 min (10min remaining → ≤30min tier)

    def test_experiment_wait_adaptive_interval_long(self, make_orchestrator):
        """Long remaining time → 10min poll interval."""
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 600},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0]})

        action = o.get_next_action()
        assert action["action_type"] == "experiment_wait"
        assert action["experiment_monitor"]["poll_interval_sec"] == 600  # 10 min (>120min)

    def test_schedules_new_batch_when_pending_tasks_exist(self, make_orchestrator):
        """When some tasks are running but others are pending, schedule new batch."""
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        # Only "a" is running; "b" is still pending
        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0]})

        action = o.get_next_action()
        # Should schedule "b", not return experiment_wait
        assert action["action_type"] in ("skill", "skills_parallel")

    def test_does_not_return_gpu_poll_when_experiments_running(self, make_orchestrator):
        """Bug fix: gpu_poll should NOT be returned when experiments are already running."""
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=True)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0]})

        action = o.get_next_action()
        # Must NOT be gpu_poll — experiments are already running!
        assert action["action_type"] == "experiment_wait"
        assert action["action_type"] != "gpu_poll"

    def test_empty_running_sources_returns_bash_advance(self, make_orchestrator):
        """Guard: if both experiment_state and gpu_progress show no running tasks,
        _experiment_wait_action should return a bash action (not infinite poll)."""
        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        # Call _experiment_wait_action directly with empty lists
        action = o._experiment_wait_action("experiment_cycle", [], [])
        # Should NOT return experiment_wait — guard returns bash
        assert action.action_type == "bash"
        assert "no running tasks" in action.bash_command

    def test_all_gpus_occupied_returns_wait_not_schedule(self, make_orchestrator):
        """When all GPUs are occupied, don't try to schedule — return experiment_wait."""
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks

        # max_gpus=2, both occupied
        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=False, max_gpus=2)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
            {"id": "c", "depends_on": [], "gpu_count": 1, "estimated_minutes": 60},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        # a and b running on GPU 0,1 — c pending but no free GPUs
        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        register_task(state, "b", gpu_ids=[1])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0], "b": [1]})

        action = o.get_next_action()
        assert action["action_type"] == "experiment_wait"


# ══════════════════════════════════════════════
# CLI: cli_recover_experiments
# ══════════════════════════════════════════════

class TestCliRecoverExperiments:
    def test_no_running_tasks(self, make_orchestrator):
        from sibyl.orchestrate import cli_recover_experiments
        import io
        import sys
        o = make_orchestrator(stage="pilot_experiments")
        captured = io.StringIO()
        sys.stdout = captured
        cli_recover_experiments(str(o.ws.root))
        sys.stdout = sys.__stdout__
        result = json.loads(captured.getvalue())
        assert result["status"] == "no_recovery_needed"

    def test_with_running_tasks(self, make_orchestrator):
        from sibyl.orchestrate import cli_recover_experiments
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        import io
        import sys
        o = make_orchestrator(stage="pilot_experiments")
        state = ExperimentState()
        register_task(state, "task_a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)

        captured = io.StringIO()
        sys.stdout = captured
        cli_recover_experiments(str(o.ws.root))
        sys.stdout = sys.__stdout__
        result = json.loads(captured.getvalue())
        assert result["status"] == "has_running_tasks"
        assert "task_a" in result["running_tasks"]
        assert "detection_script" in result


# ══════════════════════════════════════════════
# CLI: cli_apply_recovery
# ══════════════════════════════════════════════

class TestCliApplyRecovery:
    def test_apply_recovery_updates_state(self, make_orchestrator):
        from sibyl.orchestrate import cli_apply_recovery
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks
        import io
        import sys

        o = make_orchestrator(stage="pilot_experiments")
        state = ExperimentState()
        register_task(state, "task_a", gpu_ids=[0])
        register_task(state, "task_b", gpu_ids=[1])
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"task_a": [0], "task_b": [1]})

        ssh_output = (
            'DONE:task_a:{"status":"success","summary":"ok"}\n'
            'RUNNING:task_b:{"epoch":50,"total_epochs":100}\n'
        )

        captured = io.StringIO()
        sys.stdout = captured
        cli_apply_recovery(str(o.ws.root), ssh_output)
        sys.stdout = sys.__stdout__
        result = json.loads(captured.getvalue())

        assert result["status"] == "recovered"
        assert "task_a" in result["recovered_completed"]
        assert "task_b" in result["still_running"]
        assert result["progress"]["task_b"]["epoch"] == 50


class TestExperimentStateArchive:
    def test_iteration_cleanup_archives_experiment_state(self, make_orchestrator):
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
            load_experiment_state,
        )
        o = make_orchestrator(stage="quality_gate", iteration=1)
        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        state.tasks["a"]["status"] = "completed"
        save_experiment_state(o.ws.active_root, state)

        o._clear_iteration_artifacts(1)

        # experiment_state.json should be gone from active root
        fresh = load_experiment_state(o.ws.active_root)
        assert fresh.tasks == {}

        # But archived version should exist
        archive = o.ws.active_root / "exp" / "history" / "experiment_state_iter_001.json"
        assert archive.exists()
        import json as _json
        archived_data = _json.loads(archive.read_text())
        assert "a" in archived_data["tasks"]


class TestNaturalNextStageExperimentState:
    def test_stays_in_stage_when_experiment_state_has_running(self, make_orchestrator):
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        # experiment_state says running, but gpu_progress is empty
        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)

        # record_result should stay in pilot_experiments
        o.record_result("pilot_experiments")
        assert o.ws.get_status().stage == "pilot_experiments"


class TestCliExperimentStatusEnhanced:
    def test_status_shows_progress(self, make_orchestrator):
        from sibyl.orchestrate import cli_experiment_status
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
        )
        from sibyl.gpu_scheduler import register_running_tasks
        import io
        import sys

        o = make_orchestrator(stage="pilot_experiments")
        tasks = [{"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10}]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))

        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        state.tasks["a"]["progress"] = {"epoch": 50, "total_epochs": 100, "loss": 0.3}
        save_experiment_state(o.ws.active_root, state)
        register_running_tasks(o.ws.active_root, {"a": [0]})

        captured = io.StringIO()
        sys.stdout = captured
        cli_experiment_status(str(o.ws.root))
        sys.stdout = sys.__stdout__
        result = json.loads(captured.getvalue())
        assert "task_progress" in result
        assert result["task_progress"]["a"]["epoch"] == 50


class TestResetExperimentRuntimeClearsState:
    def test_reset_experiment_runtime_clears_experiment_state(self, make_orchestrator):
        from sibyl.experiment_recovery import (
            ExperimentState, register_task, save_experiment_state,
            load_experiment_state,
        )
        o = make_orchestrator(stage="pilot_experiments")
        state = ExperimentState()
        register_task(state, "a", gpu_ids=[0])
        save_experiment_state(o.ws.active_root, state)

        o._reset_experiment_runtime_state()
        fresh = load_experiment_state(o.ws.active_root)
        assert fresh.tasks == {}
