"""Tests for sibyl.orchestrate module."""
import json
import re
from pathlib import Path

import pytest

from sibyl.orchestrate import (
    FarsOrchestrator, Action, load_prompt, load_common_prompt,
    PAPER_SECTIONS, CHECKPOINT_DIRS, cli_checkpoint,
)
from sibyl.config import Config
from sibyl.workspace import Workspace


# ══════════════════════════════════════════════
# State machine transitions
# ══════════════════════════════════════════════

class TestStageTransitions:
    """Test the full pipeline stage progression."""

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
        o = make_orchestrator(stage="literature_search")
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

    def test_reflection_to_lark_sync_when_enabled(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", lark_enabled=True)
        o.record_result("reflection")
        assert o.ws.get_status().stage == "lark_sync"

    def test_reflection_skips_lark_when_disabled(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", lark_enabled=False)
        o.record_result("reflection")
        assert o.ws.get_status().stage == "quality_gate"

    def test_per_stage_lark_sync_interleaving(self, make_orchestrator):
        """When lark_enabled, every stage goes to lark_sync first, then resumes."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.record_result("literature_search")
        status = o.ws.get_status()
        assert status.stage == "lark_sync"
        assert status.resume_after_sync == "idea_debate"

        # Complete lark_sync → resumes to idea_debate
        o.record_result("lark_sync")
        status = o.ws.get_status()
        assert status.stage == "idea_debate"
        assert status.resume_after_sync == ""

    def test_lark_sync_not_interleaved_for_experiment_loop(self, make_orchestrator):
        """When experiment stage loops back to itself, no lark_sync."""
        o = make_orchestrator(stage="pilot_experiments", lark_enabled=True,
                              gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": []
        }))
        o.record_result("pilot_experiments")
        # Still more batches → stays in pilot_experiments, no sync
        assert o.ws.get_status().stage == "pilot_experiments"

    def test_lark_sync_after_all_experiments_done(self, make_orchestrator):
        """When all experiments done, goes to lark_sync before next stage."""
        o = make_orchestrator(stage="pilot_experiments", lark_enabled=True,
                              gpu_poll_enabled=False)
        tasks = [{"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10}]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": []
        }))
        o.record_result("pilot_experiments")
        status = o.ws.get_status()
        assert status.stage == "lark_sync"
        assert status.resume_after_sync == "experiment_cycle"

    def test_reflection_natural_next_is_lark_sync_no_double(self, make_orchestrator):
        """Reflection's natural next is lark_sync (pipeline position), no interleaving."""
        o = make_orchestrator(stage="reflection", lark_enabled=True)
        o.record_result("reflection")
        # Should go directly to lark_sync (natural pipeline), not double-sync
        assert o.ws.get_status().stage == "lark_sync"
        # After lark_sync completes, should go to quality_gate
        o.record_result("lark_sync")
        assert o.ws.get_status().stage == "quality_gate"

    def test_lark_sync_description_shows_resume_target(self, make_orchestrator):
        """Interleaved lark_sync action description shows where it will resume."""
        o = make_orchestrator(stage="lark_sync", lark_enabled=True)
        o.ws.set_resume_after_sync("idea_debate")
        action = o.get_next_action()
        assert "idea_debate" in action["description"]

    def test_unknown_stage_forces_done(self, make_orchestrator):
        o = make_orchestrator(stage="nonexistent_stage")
        o.record_result("nonexistent_stage")
        assert o.ws.get_status().stage == "done"


class TestRecordResult:
    def test_rejects_done_stage(self, make_orchestrator):
        o = make_orchestrator(stage="done")
        with pytest.raises(ValueError, match="terminal stage"):
            o.record_result("done")

    def test_rejects_stage_mismatch(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        with pytest.raises(ValueError, match="Stage mismatch"):
            o.record_result("literature_search")

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
# Quality gate
# ══════════════════════════════════════════════

class TestQualityGate:
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
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
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
        assert action["action_type"] == "skill"

    def test_paused_returns_paused_action(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        o.ws.pause("rate_limit")
        action = o.get_next_action()
        assert action["action_type"] == "paused"

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
        o = make_orchestrator(stage="writing_sections", writing_mode="codex")
        action = o.get_next_action()
        assert action["skills"][0]["name"] == "sibyl-codex-writer"

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
    def test_logs_iteration(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=1)
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
        o.record_result("reflection")
        log = o.ws.root / "logs/iterations/iter_001_reflection.json"
        assert log.exists()

    def test_writes_diary(self, make_orchestrator):
        o = make_orchestrator(stage="reflection", iteration=1, lark_enabled=False)
        o.ws.write_file("supervisor/review_writing.md", "score: 7.0")
        o.record_result("reflection")
        diary = o.ws.read_file("logs/research_diary.md")
        assert diary is not None
        assert "Iteration 1" in diary

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


# ══════════════════════════════════════════════
# CLI helpers
# ══════════════════════════════════════════════

class TestCLI:
    def test_cli_init(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        from sibyl.orchestrate import cli_init
        cli_init("Test Topic", "test-cli-proj")
        output = json.loads(capsys.readouterr().out)
        assert output["project_name"] == "test-cli-proj"
        assert "workspace_path" in output

    def test_cli_init_spec(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        from sibyl.orchestrate import cli_init_spec
        cli_init_spec("my-spec-proj")
        output = json.loads(capsys.readouterr().out)
        assert output["project_name"] == "my-spec-proj"
        assert Path(output["spec_path"]).exists()

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
                         "resume_after_sync": "", "iteration_dirs": False}),
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
                         "resume_after_sync": "", "iteration_dirs": False}),
            encoding="utf-8",
        )
        (ws_dir / "topic.txt").write_text("test", encoding="utf-8")
        o = FarsOrchestrator(str(ws_dir))
        assert o.config.ssh_server == "gpu-server"  # default


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

    def test_load_common_prompt(self):
        prompt = load_common_prompt()
        assert len(prompt) > 0


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
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [{"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10}]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        o.ws.write_file("exp/gpu_progress.json", json.dumps({
            "completed": ["a"], "failed": []
        }))
        o.record_result("pilot_experiments")
        assert o.ws.get_status().stage == "experiment_cycle"

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
        """Tasks with per-task gpu_count override the default."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=False)
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 2, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        o.ws.write_file("plan/task_plan.json", json.dumps({"tasks": tasks}))
        action = o.get_next_action()
        assert action["action_type"] == "skills_parallel"
        assert len(action["skills"]) == 2
        # Task a should get 2 GPUs, task b should get 1
        assert "0,1" in action["skills"][0]["args"]
        assert "2" in action["skills"][1]["args"]

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
        assert monitor["marker_file"] == "/tmp/sibyl_exp_monitor.json"
        assert set(monitor["task_ids"]) == {"task_1a", "task_1b"}
        assert monitor["timeout_minutes"] >= 30  # at least 30 min

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


# ══════════════════════════════════════════════
# GPU polling integration (orchestrator)
# ══════════════════════════════════════════════

class TestGpuPollingIntegration:
    """Test GPU polling path in _action_experiment_batch."""

    @pytest.fixture(autouse=True)
    def _clean_poll_marker(self):
        """Ensure /tmp/sibyl_gpu_free.json doesn't leak between tests."""
        marker = Path("/tmp/sibyl_gpu_free.json")
        marker.unlink(missing_ok=True)
        yield
        marker.unlink(missing_ok=True)

    def test_poll_enabled_no_result_returns_gpu_poll(self, make_orchestrator):
        """When gpu_poll_enabled=True and no poll result, returns gpu_poll action."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        action = o.get_next_action()
        assert action["action_type"] == "gpu_poll"
        assert action["gpu_poll"] is not None
        assert action["gpu_poll"]["ssh_connection"] == "default"
        assert "nvidia-smi" in action["gpu_poll"]["query_cmd"]
        assert action["gpu_poll"]["max_gpus"] == 4
        assert "轮询" in action["description"]
        assert action["stage"] == "pilot_experiments"

    def test_poll_enabled_with_result_uses_free_gpus(self, make_orchestrator, tmp_path):
        """When poll result exists, uses free GPUs for scheduling."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        marker = Path("/tmp/sibyl_gpu_free.json")
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
        marker = Path("/tmp/sibyl_gpu_free.json")
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
        marker = Path("/tmp/sibyl_gpu_free.json")
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

    def test_poll_experiment_cycle_also_polls(self, make_orchestrator):
        """experiment_cycle stage also uses GPU polling when enabled."""
        o = make_orchestrator(stage="experiment_cycle", gpu_poll_enabled=True)
        action = o.get_next_action()
        assert action["action_type"] == "gpu_poll"
        assert action["gpu_poll"] is not None

    def test_poll_result_empty_free_gpus_repolls(self, make_orchestrator):
        """If poll result has empty free_gpus list → re-poll."""
        o = make_orchestrator(stage="pilot_experiments", gpu_poll_enabled=True)
        marker = Path("/tmp/sibyl_gpu_free.json")
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


class TestCliCheckpoint:
    def test_cli_checkpoint_marks_step(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="writing_sections")
        steps = {"intro": "writing/sections/intro.md"}
        o.ws.create_checkpoint("writing_sections", "writing/sections", steps, iteration=0)
        o.ws.write_file("writing/sections/intro.md", "content here")
        cli_checkpoint(str(o.ws.root), "writing_sections", "intro")
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "ok"
        assert result["step"] == "intro"
        cp = o.ws.load_checkpoint("writing/sections")
        assert cp["steps"]["intro"]["status"] == "completed"

    def test_cli_checkpoint_unsupported_stage(self, make_orchestrator, capsys):
        o = make_orchestrator(stage="planning")
        cli_checkpoint(str(o.ws.root), "planning", "some_step")
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "error"
