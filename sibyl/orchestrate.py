"""Sibyl orchestrator for Claude Code native mode.

This module provides a state-machine orchestrator that returns the next action
for the main Claude Code session to execute. It does NOT call claude-agent-sdk.

Usage (called by Skill via Bash):
    python -c "from sibyl.orchestrate import FarsOrchestrator; ..."
"""
import json
from functools import partial, update_wrapper
from pathlib import Path

from sibyl.config import Config
from sibyl.event_logger import EventLogger
from sibyl import gpu_scheduler as _gpu_scheduler
from sibyl.workspace import Workspace
from sibyl.orchestration import cli_core as _cli_core
from sibyl.orchestration import checkpointing as _checkpointing
from sibyl.orchestration import common_utils as _common_utils
from sibyl.orchestration import constants as _constants
from sibyl.orchestration.constants import CHECKPOINT_DIRS, PIPELINE_STAGES
from sibyl.orchestration import dashboard_data as _dashboard_data
from sibyl.orchestration import lifecycle as _lifecycle
from sibyl.orchestration.common_utils import slugify_project_name
from sibyl.orchestration.config_helpers import (
    load_effective_config,
    write_project_config,
)
from sibyl.orchestration import experiment_actions as _experiment_actions
from sibyl.orchestration import migration_cli as _migration_cli
from sibyl.orchestration import ops_cli as _ops_cli
from sibyl.orchestration import project_cli as _project_cli
from sibyl.orchestration import prompt_loader as _prompt_loader
from sibyl.orchestration.prompt_loader import _load_workspace_action_plan
from sibyl.orchestration import reflection_postprocess as _reflection_postprocess
from sibyl.orchestration import runtime_cli as _runtime_cli
from sibyl.orchestration import simple_actions as _simple_actions
from sibyl.orchestration import state_machine as _state_machine
from sibyl.orchestration import team_actions as _team_actions
from sibyl.orchestration import models as _models
from sibyl.orchestration import writing_artifacts as _writing_artifacts
from sibyl.orchestration import workspace_paths as _workspace_paths
from sibyl.orchestration.workspace_paths import (
    load_workspace_iteration_dirs,
    resolve_active_workspace_path,
    resolve_workspace_root,
)

load_prompt = _prompt_loader.load_prompt
load_common_prompt = _prompt_loader.load_common_prompt
render_skill_prompt = _prompt_loader.render_skill_prompt
render_team_prompt = _prompt_loader.render_team_prompt
render_control_plane_prompt = _prompt_loader.render_control_plane_prompt
cli_write_ralph_prompt = _prompt_loader.cli_write_ralph_prompt
PAPER_SECTIONS = _constants.PAPER_SECTIONS
build_repo_python_cli_command = _common_utils.build_repo_python_cli_command
self_heal_status_file = _common_utils.self_heal_status_file
collect_dashboard_data = _dashboard_data.collect_dashboard_data
extract_section_figure_artifacts = _writing_artifacts.extract_section_figure_artifacts
project_marker_file = _workspace_paths.project_marker_file
Action = _models.Action
AgentTask = _models.AgentTask


def _bind_cli(func, /, *args, **kwargs):
    """Bind shared compatibility kwargs onto extracted CLI helpers."""
    bound = partial(func, *args, **kwargs)
    return update_wrapper(bound, func)


def _experiment_plan_candidates(workspace_path: str | Path) -> list[Path]:
    """Return compatibility search paths for experiment/task plans."""
    workspace_root = resolve_workspace_root(workspace_path)
    active_root = resolve_active_workspace_path(workspace_path)
    candidates = [
        active_root / "plan" / "task_plan.json",
        workspace_root / "plan" / "task_plan.json",
        active_root / "exp" / "experiment_plan.json",
        workspace_root / "exp" / "experiment_plan.json",
    ]
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def _load_experiment_plan(workspace_path: str | Path) -> dict:
    """Backward-compatible loader for the structured experiment plan."""
    for plan_path in _experiment_plan_candidates(workspace_path):
        if not plan_path.exists():
            continue
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict):
            return payload
    searched = ", ".join(str(path) for path in _experiment_plan_candidates(workspace_path))
    raise FileNotFoundError(f"Experiment plan not found. Searched: {searched}")


def get_next_batch(
    workspace_path: str | Path,
    gpu_ids: list[int],
    mode: str = "PILOT",
    gpus_per_task: int = 1,
) -> list[dict] | None:
    """Backward-compatible public wrapper around the GPU batch scheduler."""
    active_root = resolve_active_workspace_path(workspace_path)
    return _gpu_scheduler.get_next_batch(
        active_root,
        gpu_ids,
        mode=mode,
        gpus_per_task=gpus_per_task,
    )


class FarsOrchestrator:
    """State-machine orchestrator for Sibyl research pipeline.

    Called by the Sibyl Skill, returns the next action for Claude Code to execute.
    """

    # Pipeline stages in order
    STAGES = PIPELINE_STAGES

    def __init__(self, workspace_path: str, config: Config | None = None):
        ws_path = resolve_workspace_root(Path(workspace_path).expanduser())
        if config is not None:
            self.config = config
        else:
            self.config = load_effective_config(ws_path)
        _migration_cli.ensure_workspace_iteration_dirs(
            ws_path,
            preferred_enabled=self.config.iteration_dirs,
        )
        iteration_dirs = load_workspace_iteration_dirs(ws_path, self.config.iteration_dirs)
        self.ws = Workspace(
            ws_path.parent,
            ws_path.name,
            iteration_dirs=iteration_dirs,
        )
        self.project_path = str(self.ws.root)
        self.workspace_path = str(self.ws.active_root)

    @classmethod
    def init_project(cls, topic: str, project_name: str | None = None,
                     config_path: str | None = None) -> dict:
        """Initialize a new research project. Returns project info."""
        config = load_effective_config(config_path=config_path)

        if project_name is None:
            project_name = cls._slugify(topic)

        ws = Workspace(
            config.workspaces_dir,
            project_name,
            iteration_dirs=config.iteration_dirs,
        )

        write_project_config(ws, config)
        ws.write_file("topic.txt", topic)
        ws.update_stage("init")
        ws.git_init()

        return {
            "project_name": project_name,
            "workspace_path": str(ws.root),
            "topic": topic,
            "config": {
                "ssh_server": config.ssh_server,
                "remote_base": config.remote_base,
                "max_gpus": config.max_gpus,
                "pilot_samples": config.pilot_samples,
                "pilot_seeds": config.pilot_seeds,
                "full_seeds": config.full_seeds,
                "debate_rounds": config.debate_rounds,
                "idea_exp_cycles": config.idea_exp_cycles,
                "lark_enabled": config.lark_enabled,
                "iteration_dirs": config.iteration_dirs,
                "language": config.language,
            },
        }

    def get_next_action(self) -> dict:
        """Determine and return the next action based on current state."""
        return _lifecycle.get_next_action(self, action_cls=Action)

    def record_result(self, stage: str, result: str = "",
                      score: float | None = None):
        """Record the result of a completed stage and advance state."""
        _lifecycle.record_result(self, stage, result, score)

    def _append_pending_sync(self, stage: str):
        """Append a sync trigger to lark_sync/pending_sync.jsonl."""
        _lifecycle.append_pending_sync(self, stage)

    def get_status(self) -> dict:
        """Get current project status."""
        meta = self.ws.get_project_metadata()
        meta["topic"] = self.ws.read_file("topic.txt") or ""
        return meta

    def _compute_action(self, stage: str, topic: str, iteration: int) -> Action:
        """Compute the next action based on current stage."""
        ws = self.workspace_path

        # Backward compat: migrate old stage names
        if stage in ("critic_review", "supervisor_review"):
            stage = "review"
            self.ws.update_stage("review")

        if stage == "init":
            # init is a transient stage; the real research work starts at
            # literature_search after callers record init as complete.
            return Action(
                action_type="bash",
                bash_command="echo 'Sibyl project initialized'",
                description="项目初始化完成，推进到 literature_search 后再执行文献调研",
                stage="init",
            )

        stage_dispatch = {
            "literature_search": lambda: self._action_literature_search(topic, ws),
            "idea_debate": lambda: self._action_idea_debate(topic, ws),
            "planning": lambda: self._action_planning(ws),
            "pilot_experiments": lambda: self._action_pilot_experiments(ws),
            "idea_validation_decision": lambda: self._action_idea_validation_decision(ws),
            "experiment_cycle": lambda: self._action_experiment_cycle(ws, iteration),
            "result_debate": lambda: self._action_result_debate(ws),
            "experiment_decision": lambda: self._action_experiment_decision(ws),
            "writing_outline": lambda: self._action_writing_outline(ws),
            "writing_sections": lambda: self._action_writing_sections(ws),
            "writing_critique": lambda: self._action_writing_critique(ws),
            "writing_integrate": lambda: self._action_writing_integrate(ws),
            "writing_final_review": lambda: self._action_writing_final_review(ws),
            "writing_latex": lambda: self._action_writing_latex(ws),
            "review": lambda: self._action_review(ws),
            "reflection": lambda: self._action_reflection(ws, iteration),
            "quality_gate": self._action_quality_gate,
        }
        if stage in stage_dispatch:
            return stage_dispatch[stage]()

        if stage == "done":
            return Action(action_type="done", description="Pipeline complete", stage="done")

        return Action(action_type="done", description="Unknown stage", stage="done")

    # ══════════════════════════════════════════════
    # Action builders
    # ══════════════════════════════════════════════

    def _action_literature_search(self, topic: str, ws: str) -> Action:
        return _simple_actions.build_literature_search_action(
            topic,
            ws,
            action_cls=Action,
        )

    def _action_idea_debate(self, topic: str, ws: str) -> Action:
        """Agent Team: 6 teammates generate, debate, and synthesize research ideas."""
        return _team_actions.build_idea_debate_action(
            self,
            topic,
            ws,
            action_cls=Action,
        )

    def _action_planning(self, ws: str) -> Action:
        return _simple_actions.build_planning_action(
            self,
            ws,
            action_cls=Action,
        )

    def _action_pilot_experiments(self, ws: str) -> Action:
        return self._action_experiment_batch(ws, "PILOT", "pilot_experiments")

    def _action_idea_validation_decision(self, ws: str) -> Action:
        return _simple_actions.build_idea_validation_decision_action(
            ws,
            action_cls=Action,
        )

    def _action_experiment_cycle(self, ws: str, iteration: int) -> Action:
        return self._action_experiment_batch(ws, "FULL", "experiment_cycle")

    def _action_experiment_batch(self, ws: str, mode: str, stage: str) -> Action:
        """Build experiment action with GPU-aware batch scheduling."""
        return _experiment_actions.build_experiment_batch_action(
            self,
            ws,
            mode,
            stage,
            action_cls=Action,
        )

    def _experiment_skill_dict(self, mode: str, ws: str, gpu_ids: list[int],
                                task_ids: str = "") -> dict:
        """Build a single experimenter skill dict."""
        return _experiment_actions.build_experiment_skill_dict(
            self,
            mode,
            ws,
            gpu_ids,
            task_ids,
        )

    def _experiment_skill(self, mode: str, ws: str, gpu_ids: list[int],
                          stage: str) -> Action:
        """Single-agent experiment action (fallback when no task_plan)."""
        return _experiment_actions.build_experiment_skill_action(
            self,
            mode,
            ws,
            gpu_ids,
            stage,
            action_cls=Action,
        )

    def _build_experiment_monitor(self, mode: str, task_ids: list[str],
                                    estimated_minutes: int) -> dict:
        """Build experiment monitor config for background progress tracking."""
        return _experiment_actions.build_experiment_monitor(
            self,
            mode,
            task_ids,
            estimated_minutes,
        )

    def _gpu_poll_action(self, stage: str) -> Action:
        """Return a gpu_poll action for the main session to execute."""
        return _experiment_actions.build_gpu_poll_action(
            self,
            stage,
            action_cls=Action,
        )

    def _experiment_wait_action(self, stage: str, running_tasks: list[str],
                                running_gpus: list[int]) -> Action:
        """Return an experiment_wait action when experiments are running."""
        return _experiment_actions.build_experiment_wait_action(
            self,
            stage,
            running_tasks,
            running_gpus,
            action_cls=Action,
        )

    def _action_result_debate(self, ws: str) -> Action:
        """Agent Team: 6 teammates analyze results from diverse angles, then synthesize."""
        return _team_actions.build_result_debate_action(
            self,
            ws,
            action_cls=Action,
        )

    def _action_experiment_decision(self, ws: str) -> Action:
        return _simple_actions.build_experiment_decision_action(
            ws,
            action_cls=Action,
        )

    def _action_writing_outline(self, ws: str) -> Action:
        return _simple_actions.build_writing_outline_action(
            ws,
            action_cls=Action,
        )

    def _action_writing_sections(self, ws: str) -> Action:
        return _team_actions.build_writing_sections_action(
            self,
            ws,
            action_cls=Action,
        )

    def _action_writing_critique(self, ws: str) -> Action:
        return _team_actions.build_writing_critique_action(
            self,
            ws,
            action_cls=Action,
        )

    def _action_writing_integrate(self, ws: str) -> Action:
        return _simple_actions.build_writing_integrate_action(
            ws,
            action_cls=Action,
        )

    def _action_writing_final_review(self, ws: str) -> Action:
        return _simple_actions.build_writing_final_review_action(
            ws,
            action_cls=Action,
        )

    def _action_writing_latex(self, ws: str) -> Action:
        return _simple_actions.build_writing_latex_action(
            self,
            ws,
            action_cls=Action,
        )

    def _action_review(self, ws: str) -> Action:
        return _simple_actions.build_review_action(
            self,
            ws,
            action_cls=Action,
        )

    def _action_reflection(self, ws: str, iteration: int) -> Action:
        return _simple_actions.build_reflection_action(
            ws,
            iteration,
            action_cls=Action,
        )

    def _action_quality_gate(self) -> Action:
        """Pure computation — no side effects. Side effects in _get_next_stage."""
        return _simple_actions.build_quality_gate_action(
            self,
            action_cls=Action,
        )

    # ══════════════════════════════════════════════
    # Post-reflection hook (processes reflection agent outputs)
    # ══════════════════════════════════════════════

    def _post_reflection_hook(self):
        """Process reflection agent outputs: log iteration, record evolution, generate overlay."""
        _reflection_postprocess.run_post_reflection_hook(
            self,
            load_workspace_action_plan=_load_workspace_action_plan,
        )

    @staticmethod
    def _slugify(text: str) -> str:
        return slugify_project_name(text)


FarsOrchestrator._get_or_create_checkpoint = _checkpointing.get_or_create_checkpoint
FarsOrchestrator._is_pipeline_done = _state_machine.is_pipeline_done
FarsOrchestrator._parse_quality_gate_params = _state_machine.parse_quality_gate_params
FarsOrchestrator._get_next_stage = _state_machine.get_next_stage
FarsOrchestrator._natural_next_stage = _state_machine.natural_next_stage
FarsOrchestrator._clear_iteration_artifacts = _state_machine.clear_iteration_artifacts
FarsOrchestrator._reset_experiment_runtime_state = _state_machine.reset_experiment_runtime_state
FarsOrchestrator._get_current_cycle = _state_machine.get_current_cycle
FarsOrchestrator._get_current_validation_round = _state_machine.get_current_validation_round
FarsOrchestrator._prepare_idea_refinement_round = _state_machine.prepare_idea_refinement_round
FarsOrchestrator._load_json_artifact = _state_machine.load_json_artifact
FarsOrchestrator._load_idea_validation_decision = _state_machine.load_idea_validation_decision
FarsOrchestrator._task_matches_candidate = _state_machine.task_matches_candidate
FarsOrchestrator._apply_candidate_selection = _state_machine.apply_candidate_selection


# ══════════════════════════════════════════════
# CLI helpers for Bash invocation
# ══════════════════════════════════════════════

_write_sentinel_heartbeat = _cli_core.write_sentinel_heartbeat
_write_breadcrumb = _cli_core.write_breadcrumb
cli_init = _bind_cli(
    _cli_core.cli_init,
    orchestrator_cls=FarsOrchestrator,
    event_logger_cls=EventLogger,
)
cli_next = _bind_cli(
    _cli_core.cli_next,
    orchestrator_cls=FarsOrchestrator,
    event_logger_cls=EventLogger,
)
cli_record = _bind_cli(
    _cli_core.cli_record,
    orchestrator_cls=FarsOrchestrator,
    event_logger_cls=EventLogger,
)
cli_pause = _bind_cli(
    _cli_core.cli_pause,
    orchestrator_cls=FarsOrchestrator,
    event_logger_cls=EventLogger,
)
cli_resume = _bind_cli(
    _cli_core.cli_resume,
    orchestrator_cls=FarsOrchestrator,
    event_logger_cls=EventLogger,
)
cli_status = _cli_core.cli_status
cli_checkpoint = _bind_cli(
    _cli_core.cli_checkpoint,
    checkpoint_dirs=CHECKPOINT_DIRS,
)
cli_experiment_status = _runtime_cli.cli_experiment_status
cli_experiment_supervisor_claim = _runtime_cli.cli_experiment_supervisor_claim
cli_experiment_supervisor_heartbeat = _runtime_cli.cli_experiment_supervisor_heartbeat
cli_experiment_supervisor_notify_main = _runtime_cli.cli_experiment_supervisor_notify_main
cli_experiment_supervisor_release = _runtime_cli.cli_experiment_supervisor_release
cli_experiment_supervisor_drain_wake = _runtime_cli.cli_experiment_supervisor_drain_wake
cli_experiment_supervisor_snapshot = _runtime_cli.cli_experiment_supervisor_snapshot
cli_record_gpu_poll = _runtime_cli.cli_record_gpu_poll
cli_requeue_experiment_task = _runtime_cli.cli_requeue_experiment_task
cli_sentinel_session = _cli_core.cli_sentinel_session
cli_sentinel_config = _cli_core.cli_sentinel_config
cli_dispatch_tasks = _bind_cli(
    _runtime_cli.cli_dispatch_tasks,
    orchestrator_factory=FarsOrchestrator,
    skill_builder=lambda orchestrator, mode, active_workspace, gpu_ids, task_ids:
        orchestrator._experiment_skill_dict(mode, active_workspace, gpu_ids, task_ids),
)
cli_recover_experiments = _bind_cli(
    _runtime_cli.cli_recover_experiments,
    orchestrator_factory=FarsOrchestrator,
)
cli_apply_recovery = _runtime_cli.cli_apply_recovery
cli_sync_experiment_completions = _runtime_cli.cli_sync_experiment_completions
cli_list_projects = _project_cli.cli_list_projects
cli_init_spec = _project_cli.cli_init_spec
cli_init_from_spec = _project_cli.cli_init_from_spec
_infer_topic_for_workspace = _migration_cli.infer_topic_for_workspace
_detect_workspace_iteration_dirs = _migration_cli.detect_workspace_iteration_dirs
_strip_leading_title = _migration_cli.strip_leading_title
_build_migrated_spec = _migration_cli.build_migrated_spec
_ensure_workspace_gitignore = _migration_cli.ensure_workspace_gitignore
_ensure_workspace_git_repo = _migration_cli.ensure_workspace_git_repo
_merge_pending_sync_jsonl = _migration_cli.merge_pending_sync_jsonl
_cleanup_legacy_nested_workspace_dir = _migration_cli.cleanup_legacy_nested_workspace_dir
migrate_workspace = _migration_cli.migrate_workspace
cli_migrate = _migration_cli.cli_migrate
cli_migrate_all = _migration_cli.cli_migrate_all
cli_migrate_server = _migration_cli.cli_migrate_server


# ══════════════════════════════════════════════
# Self-Healing CLI
# ══════════════════════════════════════════════

cli_self_heal_scan = _ops_cli.cli_self_heal_scan
cli_self_heal_record = _ops_cli.cli_self_heal_record
cli_self_heal_status = _ops_cli.cli_self_heal_status
cli_self_heal_daemon_start = _ops_cli.cli_self_heal_daemon_start
self_heal_monitor_script = _ops_cli.self_heal_monitor_script


# ══════════════════════════════════════════════
# Event logging & dashboard CLI
# ══════════════════════════════════════════════

cli_log_agent = _ops_cli.cli_log_agent
cli_dashboard_data = _cli_core.cli_dashboard_data
