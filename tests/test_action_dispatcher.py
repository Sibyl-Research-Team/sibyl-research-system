"""Tests for sibyl.orchestration.action_dispatcher module."""

import pytest

from sibyl.orchestration.action_dispatcher import render_execution_script


class TestRenderExecutionScript:
    """Test execution script generation for all action types."""

    def test_skill_basic(self):
        action = {
            "action_type": "skill",
            "skills": [{"name": "sibyl-literature", "args": "/ws topic"}],
            "stage": "literature_search",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: skill" in script
        assert "sibyl-literature" in script
        assert "/ws topic" in script
        assert "cli_record" in script
        assert "literature_search" in script

    def test_skill_no_skills_returns_empty(self):
        action = {"action_type": "skill", "skills": [], "stage": "x"}
        assert render_execution_script(action) == ""

    def test_skills_parallel(self):
        action = {
            "action_type": "skills_parallel",
            "skills": [
                {"name": "sibyl-critic", "args": "/ws"},
                {"name": "sibyl-supervisor", "args": "/ws"},
            ],
            "stage": "review",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: skills_parallel" in script
        assert "2 Agent" in script
        assert "sibyl-critic" in script
        assert "sibyl-supervisor" in script

    def test_skills_parallel_with_experiment_monitor(self):
        action = {
            "action_type": "skills_parallel",
            "skills": [{"name": "sibyl-experimenter", "args": "ws PILOT"}],
            "stage": "pilot_experiments",
            "experiment_monitor": {
                "background_agent": {
                    "name": "sibyl-experiment-supervisor",
                    "args": "ws PILOT srv",
                },
            },
        }
        script = render_execution_script(action)
        assert "sibyl-experiment-supervisor" in script
        assert "run_in_background" in script

    def test_skills_parallel_monitor_no_background_agent(self):
        action = {
            "action_type": "skills_parallel",
            "skills": [{"name": "sibyl-experimenter", "args": "ws"}],
            "stage": "pilot_experiments",
            "experiment_monitor": {"poll_interval_sec": 120},
        }
        script = render_execution_script(action)
        assert "Hook auto-starts" in script

    def test_team(self):
        action = {
            "action_type": "team",
            "team": {
                "team_name": "idea-debate",
                "teammates": [
                    {"name": "innovator", "skill": "sibyl-innovator", "args": "/ws"},
                    {"name": "pragmatist", "skill": "sibyl-pragmatist", "args": "/ws"},
                ],
                "post_steps": [
                    {"type": "skill", "name": "sibyl-synthesizer", "args": "/ws"},
                ],
            },
            "stage": "idea_debate",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: team" in script
        assert "TeamCreate" in script
        assert "idea-debate" in script
        assert "innovator" in script
        assert "pragmatist" in script
        assert "post_step" in script
        assert "sibyl-synthesizer" in script

    def test_team_no_post_steps(self):
        action = {
            "action_type": "team",
            "team": {
                "team_name": "t",
                "teammates": [{"name": "a", "skill": "s", "args": ""}],
                "post_steps": [],
            },
            "stage": "idea_debate",
        }
        script = render_execution_script(action)
        assert "post_step" not in script

    def test_bash(self):
        action = {
            "action_type": "bash",
            "bash_command": "echo 'hello'",
            "stage": "quality_gate",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: bash" in script
        assert "echo 'hello'" in script
        # quality_gate should NOT have cli_record
        assert "cli_record" not in script

    def test_bash_with_recordable_stage(self):
        action = {
            "action_type": "bash",
            "bash_command": "echo 'test'",
            "stage": "literature_search",
        }
        script = render_execution_script(action)
        assert "cli_record" in script

    def test_gpu_poll(self):
        action = {
            "action_type": "gpu_poll",
            "gpu_poll": {
                "script": "#!/bin/bash\nnvidia-smi",
                "marker_file": "/tmp/test.json",
                "interval_sec": 60,
                "max_attempts": 100,
            },
            "stage": "pilot_experiments",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: gpu_poll" in script
        assert "/tmp/test.json" in script
        assert "60s" in script
        assert "永不放弃" in script

    def test_gpu_poll_no_script(self):
        action = {
            "action_type": "gpu_poll",
            "gpu_poll": {"marker_file": "/tmp/x.json"},
            "stage": "pilot_experiments",
        }
        script = render_execution_script(action)
        assert "Fallback" in script

    def test_experiment_wait(self):
        action = {
            "action_type": "experiment_wait",
            "experiment_monitor": {
                "task_ids": ["task_1a", "task_1b"],
                "poll_interval_sec": 300,
                "wake_check_interval_sec": 90,
                "max_remaining_min": 45,
            },
            "stage": "pilot_experiments",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: experiment_wait" in script
        assert "2 task(s)" in script
        assert "45min" in script
        assert "300s" in script
        assert "cli_experiment_status" in script or "status panel" in script

    def test_experiment_wait_with_supervisor(self):
        action = {
            "action_type": "experiment_wait",
            "experiment_monitor": {
                "task_ids": ["t1"],
                "poll_interval_sec": 120,
                "wake_check_interval_sec": 60,
                "max_remaining_min": 10,
                "background_agent": {
                    "name": "sibyl-experiment-supervisor",
                    "args": "ws",
                },
            },
            "stage": "pilot_experiments",
        }
        script = render_execution_script(action)
        assert "Background supervisor" in script
        assert "sibyl-experiment-supervisor" in script

    def test_agents_parallel(self):
        action = {
            "action_type": "agents_parallel",
            "agents": [
                {"name": "optimist", "description": "Evaluate from optimistic angle"},
                {"name": "skeptic", "description": "Evaluate from skeptical angle"},
            ],
            "stage": "writing_critique",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: agents_parallel" in script
        assert "2 agent(s)" in script
        assert "optimist" in script
        assert "skeptic" in script

    def test_done(self):
        action = {
            "action_type": "done",
            "description": "Pipeline complete (score=8.5)",
            "stage": "done",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: done" in script
        assert "SIBYL_PIPELINE_COMPLETE" in script
        assert "score=8.5" in script

    def test_stopped(self):
        action = {
            "action_type": "stopped",
            "description": "项目已手动停止。",
            "stage": "planning",
        }
        script = render_execution_script(action)
        assert "## EXECUTION: stopped" in script
        assert "cli_resume" in script

    def test_unknown_action_type_returns_empty(self):
        action = {"action_type": "nonexistent", "stage": "x"}
        assert render_execution_script(action) == ""

    def test_empty_action_returns_empty(self):
        assert render_execution_script({}) == ""

    def test_malformed_action_returns_empty(self):
        """Handler exceptions should be caught and return empty string."""
        action = {"action_type": "skill", "skills": None, "stage": "x"}
        assert render_execution_script(action) == ""


class TestExecutionScriptIntegration:
    """Test that execution_script is injected into cli_next output."""

    def test_action_model_has_execution_script_field(self):
        from sibyl.orchestration.models import Action
        a = Action(action_type="bash", bash_command="echo hi", stage="init")
        assert a.execution_script == ""

    def test_lifecycle_injects_execution_script(self, make_orchestrator):
        """cli_next should inject execution_script into the action dict."""
        o = make_orchestrator(stage="literature_search")
        action = o.get_next_action()
        assert "execution_script" in action
        assert action["execution_script"] != ""
        assert "## EXECUTION:" in action["execution_script"]

    def test_init_stage_gets_bash_script(self, make_orchestrator):
        o = make_orchestrator(stage="init")
        action = o.get_next_action()
        assert "## EXECUTION: bash" in action["execution_script"]

    def test_done_stage_gets_done_script(self, make_orchestrator):
        o = make_orchestrator(stage="done")
        action = o.get_next_action()
        assert "## EXECUTION: done" in action["execution_script"]

    def test_stopped_project_gets_stopped_script(self, make_orchestrator):
        o = make_orchestrator(stage="planning")
        o.ws.pause("user_stop")
        # Mark stop_requested
        import json
        status_path = o.ws.root / "status.json"
        data = json.loads(status_path.read_text())
        data["stop_requested"] = True
        status_path.write_text(json.dumps(data))
        action = o.get_next_action()
        assert "## EXECUTION: stopped" in action["execution_script"]
