"""Tests for support modules: config, context_builder, evolution, experiment_records, reflection."""

import pytest

from sibyl.config import Config
from sibyl.context_builder import ContextBuilder, estimate_tokens, truncate_to_tokens
from sibyl.evolution import EvolutionEngine, IssueCategory
from sibyl.experiment_records import ExperimentDB, ExperimentRecord
from sibyl.reflection import IterationLogger


# ══════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════

class TestConfig:
    def test_defaults(self):
        c = Config()
        assert c.ssh_server == "default"
        assert c.pilot_samples == 16
        assert c.writing_mode == "parallel"
        assert c.experiment_mode == "ssh_mcp"
        assert c.lark_enabled is True
        assert c.evolution_enabled is True
        assert c.codex_enabled is False

    def test_from_yaml(self, tmp_path):
        yaml_content = """
workspaces_dir: /tmp/test_ws
ssh_server: myserver
pilot_samples: 32
writing_mode: parallel
experiment_mode: server_codex
lark_enabled: false
"""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")
        c = Config.from_yaml(str(yaml_path))
        assert c.ssh_server == "myserver"
        assert c.pilot_samples == 32
        assert c.writing_mode == "parallel"
        assert c.experiment_mode == "server_codex"
        assert c.lark_enabled is False

    def test_invalid_writing_mode(self, tmp_path):
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text("writing_mode: invalid", encoding="utf-8")
        with pytest.raises(ValueError, match="writing_mode"):
            Config.from_yaml(str(yaml_path))

    def test_invalid_experiment_mode(self, tmp_path):
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text("experiment_mode: invalid", encoding="utf-8")
        with pytest.raises(ValueError, match="experiment_mode"):
            Config.from_yaml(str(yaml_path))

    def test_model_tiers_merge(self, tmp_path):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text('model_tiers:\n  heavy: "custom-model"', encoding="utf-8")
        c = Config.from_yaml(str(yaml_path))
        assert c.model_tiers["heavy"] == "custom-model"
        assert c.model_tiers["standard"] == "claude-opus-4-6"  # default preserved

    def test_empty_yaml(self, tmp_path):
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("", encoding="utf-8")
        c = Config.from_yaml(str(yaml_path))
        assert c.ssh_server == "default"  # all defaults

    def test_remote_env_cmd_conda(self):
        c = Config()
        cmd = c.get_remote_env_cmd("myproj")
        assert "conda" in cmd
        assert "sibyl_myproj" in cmd
        assert "miniconda3" in cmd
        assert "--no-banner" not in cmd

    def test_remote_env_cmd_conda_custom_path(self):
        c = Config(remote_conda_path="/opt/conda/bin/conda")
        cmd = c.get_remote_env_cmd("myproj")
        assert "/opt/conda/bin/conda" in cmd
        assert "sibyl_myproj" in cmd

    def test_remote_env_cmd_conda_custom_env_name(self):
        c = Config(remote_conda_env_name="base")
        cmd = c.get_remote_env_cmd("myproj")
        assert " -n base" in cmd
        assert "sibyl_myproj" not in cmd

    def test_remote_env_cmd_venv(self):
        c = Config(remote_env_type="venv")
        cmd = c.get_remote_env_cmd("myproj")
        assert "source" in cmd
        assert ".venv/bin/activate" in cmd
        assert "myproj" in cmd

    def test_new_config_fields_from_yaml(self, tmp_path):
        yaml_content = """
remote_env_type: venv
remote_conda_path: /custom/conda
remote_conda_env_name: shared-env
iteration_dirs: true
"""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")
        c = Config.from_yaml(str(yaml_path))
        assert c.remote_env_type == "venv"
        assert c.remote_conda_path == "/custom/conda"
        assert c.remote_conda_env_name == "shared-env"
        assert c.iteration_dirs is True

    def test_invalid_remote_env_type(self, tmp_path):
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text("remote_env_type: invalid", encoding="utf-8")
        with pytest.raises(ValueError, match="remote_env_type"):
            Config.from_yaml(str(yaml_path))

    def test_config_defaults_new_fields(self):
        c = Config()
        assert c.remote_env_type == "conda"
        assert c.remote_conda_path == ""
        assert c.remote_conda_env_name == ""
        assert c.iteration_dirs is False


# ══════════════════════════════════════════════
# ContextBuilder
# ══════════════════════════════════════════════

class TestContextBuilder:
    def test_empty_build(self):
        cb = ContextBuilder(budget=1000)
        assert cb.build() == ""

    def test_single_item(self):
        cb = ContextBuilder(budget=10000)
        cb.add("Test", "Hello world", priority=5)
        result = cb.build()
        assert "## Test" in result
        assert "Hello world" in result

    def test_priority_ordering(self):
        cb = ContextBuilder(budget=10000)
        cb.add("Low", "low content", priority=1)
        cb.add("High", "high content", priority=9)
        result = cb.build()
        # High priority should come first
        high_pos = result.index("## High")
        low_pos = result.index("## Low")
        assert high_pos < low_pos

    def test_budget_truncation(self):
        cb = ContextBuilder(budget=10)
        cb.add("Big", "x" * 10000, priority=5)
        result = cb.build()
        assert "[truncated]" in result
        assert len(result) < 10000

    def test_zero_priority_no_crash(self):
        """Regression test: ZeroDivisionError when all priorities are 0."""
        cb = ContextBuilder(budget=1000)
        cb.add("Test", "content", priority=0)
        result = cb.build()
        assert len(result) > 0

    def test_empty_content_skipped(self):
        cb = ContextBuilder(budget=1000)
        cb.add("Empty", "", priority=5)
        cb.add("Whitespace", "   ", priority=5)
        cb.add("Real", "real content", priority=5)
        assert len(cb.items) == 1

    def test_chaining(self):
        result = (ContextBuilder(budget=10000)
                  .add("A", "a", priority=5)
                  .add("B", "b", priority=5)
                  .build())
        assert "## A" in result
        assert "## B" in result

    def test_max_tokens_cap(self):
        cb = ContextBuilder(budget=50)
        cb.add("Capped", "x" * 10000, priority=9, max_tokens=10)
        result = cb.build()
        assert "[truncated]" in result


class TestTokenEstimation:
    def test_basic(self):
        assert estimate_tokens("hello") >= 1
        assert estimate_tokens("") == 1  # min 1

    def test_truncate_short(self):
        assert truncate_to_tokens("hello", 100) == "hello"

    def test_truncate_long(self):
        text = "x" * 10000
        result = truncate_to_tokens(text, 10)
        assert len(result) < 10000
        assert "[truncated]" in result


# ══════════════════════════════════════════════
# Evolution
# ══════════════════════════════════════════════

class TestIssueCategory:
    def test_system_classification(self):
        assert IssueCategory.classify("SSH connection timeout") == IssueCategory.SYSTEM
        assert IssueCategory.classify("OOM killed") == IssueCategory.SYSTEM
        assert IssueCategory.classify("GPU CUDA error") == IssueCategory.SYSTEM

    def test_pipeline_classification(self):
        assert IssueCategory.classify("Stage ordering issue") == IssueCategory.PIPELINE
        assert IssueCategory.classify("Missing step in pipeline") == IssueCategory.PIPELINE

    def test_experiment_classification(self):
        assert IssueCategory.classify("Weak experiment design") == IssueCategory.EXPERIMENT
        assert IssueCategory.classify("Missing baseline comparison") == IssueCategory.EXPERIMENT

    def test_writing_classification(self):
        assert IssueCategory.classify("Paper writing clarity issues") == IssueCategory.WRITING
        assert IssueCategory.classify("Section structure is poor") == IssueCategory.WRITING

    def test_analysis_classification(self):
        assert IssueCategory.classify("Insufficient statistical analysis") == IssueCategory.ANALYSIS
        assert IssueCategory.classify("Cherry-pick results") == IssueCategory.ANALYSIS

    def test_ideation_classification(self):
        assert IssueCategory.classify("Idea lacks novelty") == IssueCategory.IDEATION

    def test_default_is_analysis(self):
        assert IssueCategory.classify("Something unknown") == IssueCategory.ANALYSIS


class TestEvolutionEngine:
    def test_record_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        engine.record_outcome("proj1", "reflection", ["issue1"], 7.0, "notes")
        outcomes = engine._load_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0]["project"] == "proj1"
        assert outcomes[0]["score"] == 7.0

    def test_analyze_patterns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        assert engine.analyze_patterns() == []

    def test_analyze_patterns_frequent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["recurring issue"], 5.0)
        insights = engine.analyze_patterns()
        assert len(insights) >= 1
        assert insights[0].frequency >= 2

    def test_generate_overlay(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["test issue"], 5.0)
        written = engine.generate_lessons_overlay()
        # "test issue" → ANALYSIS → agents: supervisor, critic, skeptic, reflection
        assert "supervisor" in written
        assert "reflection" in written

    def test_reset_overlays(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["test"], 5.0)
        engine.generate_lessons_overlay()
        engine.reset_overlays()
        assert engine.get_overlay_content() == {}

    def test_corrupt_jsonl_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        engine.outcomes_path.write_text(
            'BAD JSON\n{"project":"p","stage":"s","issues":[],"score":5,"notes":"","timestamp":"","classified_issues":[]}\n',
            encoding="utf-8"
        )
        outcomes = engine._load_outcomes()
        assert len(outcomes) == 1

    def test_category_routes_to_agents(self, tmp_path, monkeypatch):
        """Overlay files are named after agents, not stages."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        # SSH issue → SYSTEM → experimenter, server_experimenter
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["SSH connection failed"], 4.0)
        written = engine.generate_lessons_overlay()
        assert "experimenter" in written
        assert "server_experimenter" in written

    def test_time_decay(self, tmp_path, monkeypatch):
        """Old issues should have lower weighted frequency."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        # Recent issues (default timestamp = now)
        engine.record_outcome("proj", "reflection", ["recent issue"], 5.0)
        engine.record_outcome("proj", "reflection", ["recent issue"], 5.0)
        insights = engine.analyze_patterns()
        assert len(insights) >= 1
        # Weighted freq should be close to 2.0 (both recent)
        assert insights[0].weighted_frequency > 1.5

    def test_quality_trend(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        engine.record_outcome("proj", "reflection", [], 5.0)
        engine.record_outcome("proj", "reflection", [], 7.0)
        trend = engine.get_quality_trend(project="proj")
        assert len(trend) == 2
        assert trend[0]["score"] == 5.0
        assert trend[1]["score"] == 7.0

    def test_classified_issues_passthrough(self, tmp_path, monkeypatch):
        """Pre-classified issues should be stored directly."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        ci = [{"description": "weak writing", "category": "writing", "severity": "high"}]
        engine.record_outcome("proj", "reflection", ["weak writing"], 5.0,
                              classified_issues=ci)
        outcomes = engine._load_outcomes()
        assert outcomes[0]["classified_issues"][0]["category"] == "writing"

    def test_record_success_patterns(self, tmp_path, monkeypatch):
        """Success patterns should be stored in outcome records."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        engine.record_outcome("proj", "reflection", [], 8.0,
                              success_patterns=["good ablation design", "clear writing"])
        outcomes = engine._load_outcomes()
        assert outcomes[0]["success_patterns"] == ["good ablation design", "clear writing"]

    def test_build_digest(self, tmp_path, monkeypatch):
        """Digest should aggregate outcomes into pattern entries."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["SSH timeout"], 5.0)
        engine.record_outcome("proj", "reflection", ["weak writing"], 6.0)
        digest = engine.build_digest()
        assert len(digest) >= 1
        ssh_entry = [d for d in digest if "ssh" in d.pattern_summary]
        assert len(ssh_entry) == 1
        assert ssh_entry[0].total_occurrences == 3
        assert ssh_entry[0].category == "system"

    def test_digest_cache(self, tmp_path, monkeypatch):
        """Digest should use cache when outcomes haven't changed."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["recurring"], 5.0)
        d1 = engine.build_digest()
        d2 = engine.build_digest()  # should use cache
        assert len(d1) == len(d2)

    def test_effectiveness_tracking(self, tmp_path, monkeypatch):
        """Issues with improving scores should be marked effective."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        # Early: low scores with this issue
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["bad analysis"], 4.0)
        # Late: higher scores (lesson took effect)
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["bad analysis"], 8.0)
        digest = engine.build_digest()
        entry = [d for d in digest if "bad analysis" in d.pattern_summary][0]
        assert entry.effectiveness == "effective"
        assert entry.effectiveness_delta > 0

    def test_ineffective_deprioritized(self, tmp_path, monkeypatch):
        """Ineffective lessons should have reduced weighted frequency."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        # Early: decent scores
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["persistent issue"], 7.0)
        # Late: scores declined (lesson not helping)
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["persistent issue"], 4.0)
        insights = engine.analyze_patterns()
        assert len(insights) >= 1
        ins = insights[0]
        assert ins.effectiveness == "ineffective"
        # weighted_frequency should be reduced by 0.3x factor
        assert ins.weighted_frequency < 3.0  # without penalty would be ~6.0

    def test_filter_relevant_lessons(self, tmp_path, monkeypatch):
        """Relevance filtering should prioritize stage-matching categories."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        # Record system and writing issues
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["SSH connection failed"], 5.0)
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["Paper writing clarity issues"], 5.0)
        result = engine.filter_relevant_lessons(
            agent_name="experimenter", stage="experiment"
        )
        # Experimenter should see system issues (relevant to experiments) ranked higher
        assert "SSH" in result.lower() or "ssh" in result.lower()

    def test_overlay_includes_success_section(self, tmp_path, monkeypatch):
        """Generated overlay should include success patterns section."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["test issue"], 5.0,
                                  success_patterns=["good baseline comparison"])
        written = engine.generate_lessons_overlay()
        assert len(written) > 0
        # At least one overlay should have success section
        any_success = any("继续保持" in content for content in written.values())
        assert any_success

    def test_self_check_declining_trend(self, tmp_path, monkeypatch):
        """Declining scores should trigger diagnostic."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        engine.record_outcome("proj", "reflection", [], 7.0)
        engine.record_outcome("proj", "reflection", [], 5.0)
        engine.record_outcome("proj", "reflection", [], 3.0)
        diag = engine.get_self_check_diagnostics("proj")
        assert diag is not None
        assert diag["declining_trend"] is True

    def test_self_check_recurring_errors(self, tmp_path, monkeypatch):
        """Recurring system errors should trigger diagnostic."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(5):
            engine.record_outcome("proj", "reflection", ["SSH connection timeout"], 5.0)
        diag = engine.get_self_check_diagnostics("proj")
        assert diag is not None
        assert "recurring_errors" in diag

    def test_self_check_all_clear(self, tmp_path, monkeypatch):
        """Good outcomes should return None diagnostic."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        engine.record_outcome("proj", "reflection", [], 7.0)
        engine.record_outcome("proj", "reflection", [], 8.0)
        engine.record_outcome("proj", "reflection", [], 9.0)
        diag = engine.get_self_check_diagnostics("proj")
        assert diag is None


# ══════════════════════════════════════════════
# ExperimentDB
# ══════════════════════════════════════════════

class TestExperimentDB:
    def test_record_and_query(self, tmp_path):
        db = ExperimentDB(tmp_path / "db.jsonl")
        rec = ExperimentRecord(
            experiment_id="exp1", project="proj", iteration=1,
            method="baseline", metrics={"acc": 0.9}, status="completed"
        )
        db.record(rec)
        results = db.query(project="proj")
        assert len(results) == 1
        assert results[0]["experiment_id"] == "exp1"

    def test_query_filter(self, tmp_path):
        db = ExperimentDB(tmp_path / "db.jsonl")
        db.record(ExperimentRecord("e1", "p1", 1, "m1", status="completed"))
        db.record(ExperimentRecord("e2", "p2", 1, "m2", status="failed"))
        assert len(db.query(project="p1")) == 1
        assert len(db.query(status="failed")) == 1

    def test_get_best(self, tmp_path):
        db = ExperimentDB(tmp_path / "db.jsonl")
        db.record(ExperimentRecord("e1", "p", 1, "m", metrics={"loss": 0.5}))
        db.record(ExperimentRecord("e2", "p", 1, "m", metrics={"loss": 0.3}))
        db.record(ExperimentRecord("e3", "p", 1, "m", metrics={"loss": 0.8}))
        best = db.get_best("loss", minimize=True)
        assert best["experiment_id"] == "e2"

    def test_get_best_no_metric(self, tmp_path):
        db = ExperimentDB(tmp_path / "db.jsonl")
        db.record(ExperimentRecord("e1", "p", 1, "m"))
        assert db.get_best("nonexistent") is None

    def test_compare(self, tmp_path):
        db = ExperimentDB(tmp_path / "db.jsonl")
        db.record(ExperimentRecord("e1", "p", 1, "m"))
        db.record(ExperimentRecord("e2", "p", 1, "m"))
        db.record(ExperimentRecord("e3", "p", 1, "m"))
        compared = db.compare(["e1", "e3"])
        assert len(compared) == 2

    def test_empty_db(self, tmp_path):
        db = ExperimentDB(tmp_path / "db.jsonl")
        assert db.query() == []
        assert db._load_all() == []


# ══════════════════════════════════════════════
# IterationLogger
# ══════════════════════════════════════════════

class TestIterationLogger:
    def test_log_and_retrieve(self, tmp_path):
        logger = IterationLogger(tmp_path)
        logger.log_iteration(1, "reflection", ["change1"], ["issue1"], [], 7.0)
        history = logger.get_history()
        assert len(history) == 1
        assert history[0]["iteration"] == 1
        assert history[0]["quality_score"] == 7.0

    def test_creates_individual_log(self, tmp_path):
        logger = IterationLogger(tmp_path)
        logger.log_iteration(2, "reflection", [], [], [], 8.0)
        log_file = tmp_path / "logs" / "iterations" / "iter_002_reflection.json"
        assert log_file.exists()

    def test_get_latest_score(self, tmp_path):
        logger = IterationLogger(tmp_path)
        logger.log_iteration(1, "reflection", [], [], [], 6.0)
        logger.log_iteration(2, "reflection", [], [], [], 8.0)
        assert logger.get_latest_score("reflection") == 8.0

    def test_get_latest_score_no_match(self, tmp_path):
        logger = IterationLogger(tmp_path)
        assert logger.get_latest_score("nonexistent") is None

    def test_empty_history(self, tmp_path):
        logger = IterationLogger(tmp_path)
        assert logger.get_history() == []
