"""Tests for support modules: config, context_builder, evolution, experiment_records, reflection."""

import json

import pytest

from sibyl.config import Config
from sibyl.context_builder import ContextBuilder, estimate_tokens, truncate_to_tokens
from sibyl.evolution import (
    EvolutionEngine,
    IssueCategory,
    ensure_workspace_snapshot,
    normalize_action_plan,
    sync_workspace_snapshot,
    workspace_evolution_dir,
)
from sibyl.experiment_records import ExperimentDB, ExperimentRecord
from sibyl.orchestration.config_helpers import write_project_config
from sibyl.orchestration.prompt_loader import cli_write_ralph_prompt
from sibyl.reflection import IterationLogger
from sibyl.workspace import Workspace


# ══════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════

class TestConfig:
    def test_defaults(self):
        c = Config()
        assert c.ssh_server == "default"
        assert c.pilot_samples == 100
        assert c.idea_validation_rounds == 4
        assert c.max_iterations == 10
        assert c.max_iterations_cap == 100
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

    def test_from_yaml_resolves_workspaces_dir_relative_to_config(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        yaml_path = config_dir / "config.yaml"
        yaml_path.write_text("workspaces_dir: ../custom-workspaces\n", encoding="utf-8")

        c = Config.from_yaml(str(yaml_path))

        assert c.workspaces_dir == (tmp_path / "custom-workspaces").resolve()

    def test_from_yaml_resolves_orchestra_skills_dir_relative_to_config(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        yaml_path = config_dir / "config.yaml"
        yaml_path.write_text("orchestra_skills_dir: ../skills\n", encoding="utf-8")

        c = Config.from_yaml(str(yaml_path))

        assert c.orchestra_skills_dir == str((tmp_path / "skills").resolve())

    def test_from_yaml_chain_preserves_override_relative_base(self, tmp_path):
        base_dir = tmp_path / "base"
        override_dir = tmp_path / "override"
        base_dir.mkdir()
        override_dir.mkdir()
        base_path = base_dir / "config.yaml"
        override_path = override_dir / "config.yaml"
        base_path.write_text("workspaces_dir: ../base-workspaces\n", encoding="utf-8")
        override_path.write_text("workspaces_dir: ../override-workspaces\n", encoding="utf-8")

        c = Config.from_yaml_chain(str(base_path), str(override_path))

        assert c.workspaces_dir == (tmp_path / "override-workspaces").resolve()

    def test_write_project_config_normalizes_workspaces_dir_to_workspace_parent(self, tmp_path):
        cfg = Config(workspaces_dir=tmp_path / "some-other-root")
        ws_root = tmp_path / "actual-workspaces"
        ws = Workspace(ws_root, "demo-project")

        write_project_config(ws, cfg)

        stored = Config.from_yaml(str(ws.root / "config.yaml"))
        assert stored.workspaces_dir == ws_root.resolve()

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
idea_validation_rounds: 2
max_iterations: 12
max_iterations_cap: 200
"""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")
        c = Config.from_yaml(str(yaml_path))
        assert c.remote_env_type == "venv"
        assert c.remote_conda_path == "/custom/conda"
        assert c.remote_conda_env_name == "shared-env"
        assert c.iteration_dirs is True
        assert c.idea_validation_rounds == 2
        assert c.max_iterations == 12
        assert c.max_iterations_cap == 200

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
        assert c.idea_validation_rounds == 4
        assert c.max_iterations == 10
        assert c.max_iterations_cap == 100


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


class TestPromptLoader:
    def test_cli_write_ralph_prompt_persists_workspace_scoped_state(self, tmp_path, capsys):
        workspace = tmp_path / "demo-project"
        workspace.mkdir(parents=True)

        cli_write_ralph_prompt(str(workspace))
        result = json.loads(capsys.readouterr().out)

        prompt_path = workspace / ".claude" / "ralph-prompt.txt"
        state_path = workspace / ".sibyl" / "project" / "ralph_loop_state.json"

        assert prompt_path.exists()
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert result["workspace_path"] == str(workspace.resolve())
        assert result["output_path"] == str(prompt_path.resolve())
        assert state["workspace_path"] == str(workspace.resolve())
        assert state["output_path"] == str(prompt_path.resolve())


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
    def test_normalize_action_plan_schema_drift(self):
        normalized = normalize_action_plan({
            "issues_classified": [
                {
                    "description": "Need stronger literature comparison",
                    "category": "research",
                    "severity": "critical",
                    "status": "ongoing",
                }
            ],
            "quality_trajectory": "divergent",
        })

        issue = normalized["issues_classified"][0]
        assert issue["category"] == "analysis"
        assert issue["severity"] == "high"
        assert issue["status"] == "recurring"
        assert issue["issue_key"].startswith("analysis:")
        assert normalized["quality_trajectory"] == "stagnant"

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
        ssh_entry = [d for d in digest if "ssh" in d.pattern_summary.lower()]
        assert len(ssh_entry) == 1
        assert ssh_entry[0].total_occurrences == 3
        assert ssh_entry[0].category == "system"

    def test_build_digest_groups_by_issue_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        shared_key = "writing:word-limit"
        engine.record_outcome(
            "proj",
            "reflection",
            ["paper too long"],
            5.0,
            classified_issues=[
                {
                    "description": "论文篇幅仍远超 6,000 词限制",
                    "category": "writing",
                    "issue_key": shared_key,
                }
            ],
        )
        engine.record_outcome(
            "proj",
            "reflection",
            ["paper too long"],
            6.0,
            classified_issues=[
                {
                    "description": "正文仍然超过 6000 词限制",
                    "category": "writing",
                    "issue_key": shared_key,
                }
            ],
        )
        digest = engine.build_digest()
        writing_entries = [entry for entry in digest if entry.category == "writing"]
        assert len(writing_entries) == 1
        assert writing_entries[0].total_occurrences == 2

    def test_digest_cache(self, tmp_path, monkeypatch):
        """Digest should use cache when outcomes haven't changed."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["recurring"], 5.0)
        d1 = engine.build_digest()
        d2 = engine.build_digest()  # should use cache
        assert len(d1) == len(d2)

    def test_effectiveness_stays_unverified_without_causal_signal(self, tmp_path, monkeypatch):
        """Score drift alone should not mark a lesson effective/ineffective."""
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["bad analysis"], 4.0)
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["bad analysis"], 8.0)
        digest = engine.build_digest()
        entry = [d for d in digest if "bad analysis" in d.pattern_summary][0]
        assert entry.effectiveness == "unverified"
        assert entry.effectiveness_delta == 0.0

    def test_analyze_patterns_keeps_weight_without_fake_ineffective_penalty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["persistent issue"], 7.0)
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["persistent issue"], 4.0)
        insights = engine.analyze_patterns()
        assert len(insights) >= 1
        ins = insights[0]
        assert ins.effectiveness == "unverified"
        assert ins.weighted_frequency > 3.0

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

    def test_filter_relevant_lessons_understands_stage_aliases(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome("proj", "reflection", ["Paper writing clarity issues"], 5.0)
        result = engine.filter_relevant_lessons(
            agent_name="section_writer",
            stage="writing_sections",
        )
        assert "clarity" in result.lower()

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

    def test_overlay_success_patterns_are_agent_relevant(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome(
                "proj",
                "reflection",
                ["SSH connection failed"],
                5.0,
                success_patterns=["GPU retry kept experiments moving"],
            )
        for _ in range(3):
            engine.record_outcome(
                "proj",
                "reflection",
                ["Paper writing clarity issues"],
                6.0,
                success_patterns=["Paper clarity pass improved readability"],
            )
        written = engine.generate_lessons_overlay()
        assert "GPU retry kept experiments moving" in written["experimenter"]
        assert "Paper clarity pass improved readability" not in written["experimenter"]

    def test_overlay_success_counts_use_real_outcome_frequency(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        for _ in range(3):
            engine.record_outcome(
                "proj",
                "reflection",
                ["Paper writing clarity issues"],
                6.0,
                success_patterns=["paper clarity pass"],
            )
        for _ in range(3):
            engine.record_outcome(
                "proj",
                "reflection",
                ["Appendix missing"],
                6.0,
                success_patterns=["paper clarity pass"],
            )
        written = engine.generate_lessons_overlay()
        assert "paper clarity pass (出现 6 次)" in written["section_writer"]

    def test_generate_overlay_cleans_stale_files_without_insights(self, tmp_path, monkeypatch):
        monkeypatch.setattr(EvolutionEngine, "EVOLUTION_DIR", tmp_path / "evo")
        engine = EvolutionEngine()
        stale_path = engine.EVOLUTION_DIR / "lessons" / "stale_agent.md"
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_text("stale", encoding="utf-8")
        written = engine.generate_lessons_overlay()
        assert written == {}
        assert not stale_path.exists()

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

    def test_workspace_snapshot_freezes_global_evolution_until_resync(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SIBYL_EVOLUTION_DIR", raising=False)
        monkeypatch.setenv("SIBYL_STATE_DIR", str(tmp_path / "state"))

        global_engine = EvolutionEngine()
        for _ in range(3):
            global_engine.record_outcome("proj", "reflection", ["SSH connection failed"], 5.0)
        global_engine.run_cross_project_evolution()

        workspace = tmp_path / "workspace-a"
        workspace.mkdir(parents=True)
        snapshot_dir = ensure_workspace_snapshot(workspace)
        snapshot_engine = EvolutionEngine(snapshot_dir)
        initial_overlays = snapshot_engine.get_overlay_content()
        assert "experimenter" in initial_overlays

        for _ in range(3):
            global_engine.record_outcome(
                "proj",
                "reflection",
                ["Paper writing clarity issues"],
                6.0,
            )
        global_engine.run_cross_project_evolution()

        frozen_overlays = EvolutionEngine(snapshot_dir).get_overlay_content()
        assert "section_writer" not in frozen_overlays
        assert frozen_overlays == initial_overlays

        sync_workspace_snapshot(workspace)
        refreshed_overlays = EvolutionEngine(workspace_evolution_dir(workspace)).get_overlay_content()
        assert "section_writer" in refreshed_overlays


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
