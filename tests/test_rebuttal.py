"""Tests for sibyl.rebuttal subsystem."""

import json
import os
from pathlib import Path

import pytest

from sibyl.config import Config
from sibyl.rebuttal.config import RebuttalConfig
from sibyl.rebuttal.constants import REBUTTAL_STAGES, REBUTTAL_TEAM_ROLES, REBUTTAL_AGENT_TIERS
from sibyl.rebuttal.scoring import (
    RoundScore,
    get_current_round,
    load_round_score,
    load_score_trajectory,
    save_round_score,
    save_score_trajectory,
    set_current_round,
    should_stop,
)
from sibyl.rebuttal.orchestrator import RebuttalOrchestrator
from sibyl.rebuttal.workspace_setup import init_workspace
from sibyl.rebuttal import actions as rebuttal_actions
from sibyl.rebuttal import state_machine as rebuttal_sm


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════


@pytest.fixture
def rebuttal_ws(tmp_path):
    """Create a minimal rebuttal workspace with paper + 2 reviews."""
    paper = tmp_path / "paper.md"
    paper.write_text("# Test Paper\nA novel approach to X.")

    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "reviewer_1.md").write_text(
        "## Weaknesses\n1. Missing baselines\n2. Weak theory"
    )
    (reviews_dir / "reviewer_2.md").write_text(
        "## Weaknesses\n1. Novelty unclear\n2. Writing quality"
    )

    ws_dir = tmp_path / "ws"
    init_workspace(
        ws_dir,
        str(paper),
        str(reviews_dir),
        word_limit=500,
        language="en",
    )
    # Auto-advance past transient init stage (mirrors cli_rebuttal_init behavior)
    o = RebuttalOrchestrator(str(ws_dir))
    o.record_result("init")
    return ws_dir


@pytest.fixture
def make_rebuttal_orchestrator(rebuttal_ws):
    """Factory fixture for rebuttal orchestrators at a specific stage."""

    def _make(stage="parse_reviews", round_num=1):
        # Update status to desired stage
        status_file = rebuttal_ws / "status.json"
        data = json.loads(status_file.read_text())
        data["stage"] = stage
        status_file.write_text(json.dumps(data))
        set_current_round(rebuttal_ws, round_num)
        return RebuttalOrchestrator(str(rebuttal_ws))

    return _make


# ══════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════


class TestConstants:
    def test_pipeline_stages_start_with_init_end_with_done(self):
        assert REBUTTAL_STAGES[0] == "init"
        assert REBUTTAL_STAGES[-1] == "done"

    def test_all_team_roles_have_tier(self):
        for role in REBUTTAL_TEAM_ROLES:
            assert role in REBUTTAL_AGENT_TIERS, f"{role} missing tier"

    def test_score_evaluate_in_pipeline(self):
        assert "score_evaluate" in REBUTTAL_STAGES
        assert "rebuttal_draft" in REBUTTAL_STAGES
        assert "simulated_review" in REBUTTAL_STAGES


# ══════════════════════════════════════════════
# RebuttalConfig
# ══════════════════════════════════════════════


class TestRebuttalConfig:
    def test_defaults(self):
        rc = RebuttalConfig()
        assert rc.max_rounds == 3
        assert rc.score_threshold == 7.0
        assert rc.word_limit == 0
        assert rc.codex_enabled is False
        assert rc.reviewer_ids == []
        assert rc.reviewer_count == 0

    def test_from_workspace(self, rebuttal_ws):
        rc = RebuttalConfig.from_workspace(rebuttal_ws)
        assert rc.word_limit == 500
        assert rc.reviewer_ids == ["reviewer_1", "reviewer_2"]
        assert rc.reviewer_count == 2

    def test_from_workspace_inherits_base_config(self, rebuttal_ws):
        base = Config()
        base.codex_enabled = True
        base.language = "zh"
        rc = RebuttalConfig.from_workspace(rebuttal_ws, base)
        assert rc.codex_enabled is False  # workspace yaml overrides
        assert rc.language == "en"  # workspace yaml overrides

    def test_to_yaml_roundtrip(self):
        rc = RebuttalConfig(word_limit=300, reviewer_ids=["r1", "r2"])
        yaml_str = rc.to_yaml()
        assert "word_limit: 300" in yaml_str
        assert "r1" in yaml_str

    def test_reviewer_ids_not_shared_across_instances(self):
        rc1 = RebuttalConfig()
        rc2 = RebuttalConfig()
        rc1.reviewer_ids.append("test")
        assert rc2.reviewer_ids == []


# ══════════════════════════════════════════════
# Scoring
# ══════════════════════════════════════════════


class TestScoring:
    def test_should_stop_score_above_threshold(self):
        assert should_stop(8.0, 1, 7.0, 3) is True

    def test_should_stop_max_rounds(self):
        assert should_stop(5.0, 3, 7.0, 3) is True

    def test_should_not_stop(self):
        assert should_stop(5.0, 1, 7.0, 3) is False

    def test_get_current_round_default(self, tmp_path):
        assert get_current_round(tmp_path) == 1

    def test_set_and_get_current_round(self, tmp_path):
        set_current_round(tmp_path, 3)
        assert get_current_round(tmp_path) == 3

    def test_save_and_load_round_score(self, tmp_path):
        score = RoundScore(
            round_num=1,
            per_reviewer={"r1": 7.0, "r2": 8.0},
            avg_score=7.5,
            concerns_addressed=5,
            concerns_remaining=2,
        )
        save_round_score(tmp_path, score)
        loaded = load_round_score(tmp_path, 1)
        assert loaded is not None
        assert loaded.avg_score == 7.5
        assert loaded.per_reviewer == {"r1": 7.0, "r2": 8.0}

    def test_load_round_score_missing(self, tmp_path):
        assert load_round_score(tmp_path, 99) is None

    def test_load_round_score_from_current_symlink(self, tmp_path):
        """Test fallback: load from rounds/current/ when numbered dir doesn't exist."""
        current_dir = tmp_path / "rounds" / "current"
        current_dir.mkdir(parents=True)
        (current_dir / "scores.json").write_text(json.dumps({
            "round_num": 1, "avg_score": 6.5, "per_reviewer": {},
        }))
        loaded = load_round_score(tmp_path, 1)
        assert loaded is not None
        assert loaded.avg_score == 6.5

    def test_score_trajectory(self, tmp_path):
        for i in range(1, 4):
            save_round_score(tmp_path, RoundScore(
                round_num=i, avg_score=5.0 + i,
                per_reviewer={"r1": 5.0 + i},
            ))
        traj = load_score_trajectory(tmp_path)
        assert len(traj) == 3
        assert traj[0]["avg_score"] == 6.0
        assert traj[2]["avg_score"] == 8.0

    def test_save_and_load_trajectory(self, tmp_path):
        traj = [{"round_num": 1, "avg_score": 7.0}]
        save_score_trajectory(tmp_path, traj)
        loaded = load_score_trajectory(tmp_path)
        assert loaded == traj

    def test_string_path_accepted(self, tmp_path):
        set_current_round(str(tmp_path), 2)
        assert get_current_round(str(tmp_path)) == 2


# ══════════════════════════════════════════════
# Workspace Setup
# ══════════════════════════════════════════════


class TestWorkspaceSetup:
    def test_init_creates_structure(self, rebuttal_ws):
        assert (rebuttal_ws / "status.json").exists()
        assert (rebuttal_ws / "rebuttal_config.yaml").exists()
        assert (rebuttal_ws / "input/paper.md").exists()
        assert (rebuttal_ws / "input/reviews/reviewer_1.md").exists()
        assert (rebuttal_ws / "input/reviews/reviewer_2.md").exists()
        assert (rebuttal_ws / "rounds/round_001/team").is_dir()
        assert (rebuttal_ws / "rounds/current").is_symlink()
        assert (rebuttal_ws / "output/per_reviewer").is_dir()

    def test_init_status_auto_advanced(self, rebuttal_ws):
        """After fixture setup (which mirrors cli_rebuttal_init), stage is parse_reviews."""
        status = RebuttalOrchestrator(str(rebuttal_ws)).ws.get_status()
        assert status.stage == "parse_reviews"

    def test_init_config(self, rebuttal_ws):
        rc = RebuttalConfig.from_workspace(rebuttal_ws)
        assert rc.reviewer_ids == ["reviewer_1", "reviewer_2"]
        assert rc.word_limit == 500

    def test_init_no_reviews_raises(self, tmp_path):
        paper = tmp_path / "paper.md"
        paper.write_text("test")
        empty_dir = tmp_path / "empty_reviews"
        empty_dir.mkdir()
        with pytest.raises(ValueError, match="No review files"):
            init_workspace(tmp_path / "ws", str(paper), str(empty_dir))

    def test_init_missing_paper_raises(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / "r1.md").write_text("review")
        with pytest.raises(FileNotFoundError, match="Paper not found"):
            init_workspace(tmp_path / "ws", "/nonexistent/paper.md", str(reviews))

    def test_init_source_repo_symlink(self, tmp_path):
        paper = tmp_path / "paper.md"
        paper.write_text("test")
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / "r1.md").write_text("review")
        repo = tmp_path / "code_repo"
        repo.mkdir()

        ws_dir = tmp_path / "ws"
        init_workspace(ws_dir, str(paper), str(reviews), source_repo=str(repo))
        assert (ws_dir / "input/source_repo").is_symlink()

    def test_no_research_pipeline_pollution(self, rebuttal_ws):
        """Workspace must NOT contain research pipeline directories."""
        for forbidden in ["idea", "exp", "plan", "writing", "supervisor", "critic"]:
            assert not (rebuttal_ws / forbidden).exists(), f"{forbidden}/ should not exist"


# ══════════════════════════════════════════════
# State Machine
# ══════════════════════════════════════════════


class TestStateMachine:
    def test_linear_progression(self, make_rebuttal_orchestrator):
        """Non-looping stages advance linearly."""
        o = make_rebuttal_orchestrator("parse_reviews")
        next_stage, _ = rebuttal_sm.get_next_stage(o, "parse_reviews")
        assert next_stage == "strategy"

        next_stage, _ = rebuttal_sm.get_next_stage(o, "strategy")
        assert next_stage == "rebuttal_draft"

    def test_codex_review_skipped_when_disabled(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("simulated_review")
        assert o.rebuttal_config.codex_enabled is False
        next_stage, _ = rebuttal_sm.get_next_stage(o, "simulated_review")
        assert next_stage == "score_evaluate"

    def test_loop_back_on_low_score(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate", round_num=1)
        ws = Path(o.workspace_path)
        save_round_score(ws, RoundScore(round_num=1, avg_score=5.0))

        next_stage, new_round = rebuttal_sm.get_next_stage(o, "score_evaluate")
        assert next_stage == "rebuttal_draft"
        assert new_round == 2

    def test_converge_on_high_score(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate", round_num=1)
        ws = Path(o.workspace_path)
        save_round_score(ws, RoundScore(round_num=1, avg_score=8.0))

        next_stage, new_round = rebuttal_sm.get_next_stage(o, "score_evaluate")
        assert next_stage == "final_synthesis"
        assert new_round is None

    def test_converge_on_max_rounds(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate", round_num=3)
        ws = Path(o.workspace_path)
        save_round_score(ws, RoundScore(round_num=3, avg_score=4.0))

        next_stage, _ = rebuttal_sm.get_next_stage(o, "score_evaluate")
        assert next_stage == "final_synthesis"

    def test_final_synthesis_to_done(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("final_synthesis")
        next_stage, _ = rebuttal_sm.get_next_stage(o, "final_synthesis")
        assert next_stage == "done"

    def test_prepare_next_round_creates_dirs(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate", round_num=1)
        ws = Path(o.workspace_path)
        save_round_score(ws, RoundScore(round_num=1, avg_score=5.0))

        rebuttal_sm.get_next_stage(o, "score_evaluate")

        round2 = ws / "rounds/round_002"
        assert round2.is_dir()
        assert (round2 / "team").is_dir()
        assert (round2 / "synthesis").is_dir()
        assert (round2 / "sim_review").is_dir()
        assert (round2 / "prev_round_feedback.json").exists()

    def test_prepare_next_round_updates_symlink(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate", round_num=1)
        ws = Path(o.workspace_path)
        save_round_score(ws, RoundScore(round_num=1, avg_score=5.0))

        rebuttal_sm.get_next_stage(o, "score_evaluate")

        current = ws / "rounds/current"
        assert current.is_symlink()
        assert os.readlink(str(current)) == "round_002"

    def test_prepare_next_round_aggregates_sim_reviews(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate", round_num=1)
        ws = Path(o.workspace_path)

        # Write mock sim reviews for round 1
        sim_dir = ws / "rounds/round_001/sim_review"
        sim_dir.mkdir(parents=True, exist_ok=True)
        (sim_dir / "reviewer_1.md").write_text("Score: 6/10. Missing baselines still.")
        (sim_dir / "reviewer_1.json").write_text(json.dumps({"score": 6.0}))

        save_round_score(ws, RoundScore(round_num=1, avg_score=5.0))
        rebuttal_sm.get_next_stage(o, "score_evaluate")

        feedback = json.loads((ws / "rounds/round_002/prev_round_feedback.json").read_text())
        assert "reviewer_1" in feedback["sim_reviews"]
        assert "Missing baselines" in feedback["sim_reviews"]["reviewer_1"]
        assert feedback["sim_reviews_reviewer_1_json"]["score"] == 6.0

    def test_no_score_file_loops_back(self, make_rebuttal_orchestrator):
        """If no scores.json exists, avg=0 → loop back."""
        o = make_rebuttal_orchestrator("score_evaluate", round_num=1)
        next_stage, new_round = rebuttal_sm.get_next_stage(o, "score_evaluate")
        assert next_stage == "rebuttal_draft"
        assert new_round == 2


# ══════════════════════════════════════════════
# Actions
# ══════════════════════════════════════════════


class TestActions:
    def test_parse_reviews_action(self, rebuttal_ws):
        action = rebuttal_actions.build_parse_reviews_action(str(rebuttal_ws))
        assert action.action_type == "skill"
        assert action.stage == "parse_reviews"
        assert action.skills[0]["name"] == "sibyl-rebuttal-strategist"
        assert "parse" in action.skills[0]["args"]

    def test_strategy_action(self, rebuttal_ws):
        action = rebuttal_actions.build_strategy_action(str(rebuttal_ws))
        assert action.action_type == "skill"
        assert action.stage == "strategy"

    def test_rebuttal_draft_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("rebuttal_draft")
        action = rebuttal_actions.build_rebuttal_draft_action(o, o.workspace_path)
        assert action.action_type == "team"
        assert len(action.team["teammates"]) == 8
        assert action.team["team_name"] == "sibyl-rebuttal-team"
        assert len(action.team["post_steps"]) == 1
        assert action.team["post_steps"][0]["skill"] == "sibyl-rebuttal-synthesizer"

    def test_rebuttal_draft_word_limit_in_prompt(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("rebuttal_draft")
        action = rebuttal_actions.build_rebuttal_draft_action(o, o.workspace_path)
        assert "500 words" in action.team["prompt"]

    def test_rebuttal_draft_refinement_hint(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("rebuttal_draft", round_num=2)
        action = rebuttal_actions.build_rebuttal_draft_action(o, o.workspace_path)
        assert "refinement round 2" in action.team["prompt"]

    def test_simulated_review_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("simulated_review")
        action = rebuttal_actions.build_simulated_review_action(o, o.workspace_path)
        assert action.action_type == "skills_parallel"
        assert len(action.skills) == 2
        assert action.skills[0]["name"] == "sibyl-simulated-reviewer"
        assert "reviewer_1" in action.skills[0]["args"]
        assert "reviewer_2" in action.skills[1]["args"]

    def test_simulated_review_empty_reviewers_raises(self, tmp_path):
        """Empty reviewer_ids must raise, not produce a silent no-op."""
        paper = tmp_path / "paper.md"
        paper.write_text("test")
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / "r1.md").write_text("review")

        ws_dir = tmp_path / "ws"
        init_workspace(ws_dir, str(paper), str(reviews))

        # Manually clear reviewer_ids to simulate misconfiguration
        rc_file = ws_dir / "rebuttal_config.yaml"
        import yaml
        data = yaml.safe_load(rc_file.read_text())
        data["reviewer_ids"] = []
        rc_file.write_text(yaml.safe_dump(data))

        o = RebuttalOrchestrator(str(ws_dir))
        with pytest.raises(ValueError, match="No reviewer_ids"):
            rebuttal_actions.build_simulated_review_action(o, o.workspace_path)

    def test_score_evaluate_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("score_evaluate")
        action = rebuttal_actions.build_score_evaluate_action(o, o.workspace_path)
        assert action.action_type == "skill"
        assert action.stage == "score_evaluate"
        assert "evaluate" in action.skills[0]["args"]

    def test_final_synthesis_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("final_synthesis")
        action = rebuttal_actions.build_final_synthesis_action(o, o.workspace_path)
        assert action.action_type == "skill"
        assert action.stage == "final_synthesis"
        assert "final" in action.skills[0]["args"]

    def test_codex_review_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("codex_review")
        action = rebuttal_actions.build_codex_review_action(o, o.workspace_path)
        assert action.action_type == "skill"
        assert action.skills[0]["name"] == "sibyl-codex-reviewer"


# ══════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════


class TestOrchestrator:
    def test_get_next_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("parse_reviews")
        action = o.get_next_action()
        assert action["stage"] == "parse_reviews"
        assert action["action_type"] == "skill"
        assert action["language"] == "en"
        assert action["round"] == 1

    def test_record_result_advances_stage(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("parse_reviews")
        result = o.record_result("parse_reviews")
        assert result["new_stage"] == "strategy"

    def test_record_result_stage_mismatch(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("parse_reviews")
        with pytest.raises(ValueError, match="Stage mismatch"):
            o.record_result("strategy")

    def test_get_status(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("rebuttal_draft")
        status = o.get_status()
        assert status["stage"] == "rebuttal_draft"
        assert status["round"] == 1
        assert status["reviewer_count"] == 2
        assert status["reviewer_ids"] == ["reviewer_1", "reviewer_2"]
        assert status["max_rounds"] == 3
        assert status["score_threshold"] == 7.0

    def test_done_action(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("done")
        action = o.get_next_action()
        assert action["action_type"] == "done"

    def test_unknown_stage_returns_done(self, make_rebuttal_orchestrator):
        o = make_rebuttal_orchestrator("nonexistent_stage")
        action = o.get_next_action()
        assert action["action_type"] == "done"

    def test_no_research_workspace_pollution(self, rebuttal_ws):
        """Opening a rebuttal workspace must not create research pipeline dirs."""
        o = RebuttalOrchestrator(str(rebuttal_ws))
        assert not (rebuttal_ws / "idea").exists()
        assert not (rebuttal_ws / "exp").exists()
        assert not (rebuttal_ws / "plan").exists()


# ══════════════════════════════════════════════
# Full Pipeline Integration
# ══════════════════════════════════════════════


class TestFullPipeline:
    def test_full_converge_in_one_round(self, rebuttal_ws):
        """Pipeline converges when first round score exceeds threshold."""
        o = RebuttalOrchestrator(str(rebuttal_ws))

        # Advance through linear stages
        for stage in ["parse_reviews", "strategy", "rebuttal_draft", "simulated_review"]:
            o.record_result(stage)
            o = RebuttalOrchestrator(str(rebuttal_ws))

        # Write high scores
        save_round_score(rebuttal_ws, RoundScore(round_num=1, avg_score=8.0))

        o.record_result("score_evaluate")
        o = RebuttalOrchestrator(str(rebuttal_ws))
        assert o.ws.get_status().stage == "final_synthesis"

        o.record_result("final_synthesis")
        o = RebuttalOrchestrator(str(rebuttal_ws))
        assert o.ws.get_status().stage == "done"

    def test_full_loop_then_converge(self, rebuttal_ws):
        """Pipeline loops once on low score, then converges."""
        o = RebuttalOrchestrator(str(rebuttal_ws))

        # Round 1
        for stage in ["parse_reviews", "strategy", "rebuttal_draft", "simulated_review"]:
            o.record_result(stage)
            o = RebuttalOrchestrator(str(rebuttal_ws))

        save_round_score(rebuttal_ws, RoundScore(round_num=1, avg_score=5.0))
        result = o.record_result("score_evaluate")
        assert result["new_stage"] == "rebuttal_draft"
        assert result["round"] == 2

        # Round 2
        o = RebuttalOrchestrator(str(rebuttal_ws))
        for stage in ["rebuttal_draft", "simulated_review"]:
            o.record_result(stage)
            o = RebuttalOrchestrator(str(rebuttal_ws))

        save_round_score(rebuttal_ws, RoundScore(round_num=2, avg_score=8.5))
        result = o.record_result("score_evaluate")
        assert result["new_stage"] == "final_synthesis"

    def test_max_rounds_forces_convergence(self, rebuttal_ws):
        """Pipeline converges when max_rounds reached even with low scores."""
        # Set max_rounds=1
        import yaml
        rc_file = rebuttal_ws / "rebuttal_config.yaml"
        data = yaml.safe_load(rc_file.read_text())
        data["max_rounds"] = 1
        rc_file.write_text(yaml.safe_dump(data))

        o = RebuttalOrchestrator(str(rebuttal_ws))
        for stage in ["parse_reviews", "strategy", "rebuttal_draft", "simulated_review"]:
            o.record_result(stage)
            o = RebuttalOrchestrator(str(rebuttal_ws))

        save_round_score(rebuttal_ws, RoundScore(round_num=1, avg_score=3.0))
        result = o.record_result("score_evaluate")
        assert result["new_stage"] == "final_synthesis"


# ══════════════════════════════════════════════
# Prompt Helpers
# ══════════════════════════════════════════════


class TestPromptHelpers:
    def test_render_rebuttal_skill_prompt(self, rebuttal_ws):
        from sibyl.rebuttal.prompt_helpers import render_rebuttal_skill_prompt
        prompt = render_rebuttal_skill_prompt(
            "rebuttal_strategist", str(rebuttal_ws), mode="parse"
        )
        assert "rebuttal_strategist" in prompt
        assert "Mode: parse" in prompt
        assert len(prompt) > 100

    def test_render_reviewer_persona_prompt(self, rebuttal_ws):
        from sibyl.rebuttal.prompt_helpers import render_reviewer_persona_prompt
        prompt = render_reviewer_persona_prompt(str(rebuttal_ws), "reviewer_1", 1)
        assert "reviewer_1" in prompt
        assert "Missing baselines" in prompt
        assert len(prompt) > 100

    def test_render_reviewer_unknown_id(self, rebuttal_ws):
        from sibyl.rebuttal.prompt_helpers import render_reviewer_persona_prompt
        prompt = render_reviewer_persona_prompt(str(rebuttal_ws), "nonexistent", 1)
        assert "not found" in prompt

    def test_render_nonexistent_agent(self, rebuttal_ws):
        from sibyl.rebuttal.prompt_helpers import render_rebuttal_skill_prompt
        prompt = render_rebuttal_skill_prompt("nonexistent_agent", str(rebuttal_ws))
        assert prompt == ""


# ══════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════


class TestCLI:
    def test_cli_rebuttal_init(self, tmp_path, capsys):
        paper = tmp_path / "paper.md"
        paper.write_text("test paper")
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / "r1.md").write_text("review 1")

        from sibyl.rebuttal.cli import cli_rebuttal_init
        result = cli_rebuttal_init(
            str(paper), str(reviews),
            workspace_dir=str(tmp_path / "ws"),
        )
        data = json.loads(result)
        assert data["reviewer_count"] == 1
        assert "r1" in data["reviewer_ids"]

    def test_cli_rebuttal_next(self, rebuttal_ws, capsys):
        from sibyl.rebuttal.cli import cli_rebuttal_next
        result = cli_rebuttal_next(str(rebuttal_ws))
        data = json.loads(result)
        assert data["stage"] == "parse_reviews"

    def test_cli_rebuttal_record(self, rebuttal_ws, capsys):
        from sibyl.rebuttal.cli import cli_rebuttal_record
        result = cli_rebuttal_record(str(rebuttal_ws), "parse_reviews")
        data = json.loads(result)
        assert data["new_stage"] == "strategy"

    def test_cli_rebuttal_status(self, rebuttal_ws, capsys):
        from sibyl.rebuttal.cli import cli_rebuttal_status
        result = cli_rebuttal_status(str(rebuttal_ws))
        data = json.loads(result)
        assert "stage" in data
        assert "reviewer_ids" in data
        assert "score_trajectory" in data
