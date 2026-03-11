"""Simple stage action builders extracted from the legacy orchestrator."""

from __future__ import annotations

from typing import Any

from .agent_helpers import codex_reviewer_args
from .common_utils import pack_skill_args
from .prompt_loader import _load_workspace_action_plan


def build_literature_search_action(
    topic: str,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Single fork skill performs literature search via arXiv + WebSearch."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-literature", "args": pack_skill_args(ws, topic)}],
        description="文献调研：arXiv 搜索 + Web 搜索，建立领域现状基础",
        stage="literature_search",
    )


def build_planning_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the planning-stage action with pilot experiment config context."""
    pilot_config = (
        f"samples={orchestrator.config.pilot_samples}, "
        f"seeds={orchestrator.config.pilot_seeds}, "
        f"timeout={orchestrator.config.pilot_timeout}s"
    )
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-planner", "args": pack_skill_args(ws, "plan", pilot_config)}],
        description="Design experiment plan with pilot/full configs",
        stage="planning",
    )


def build_idea_validation_decision_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the pilot-validation decision action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-idea-validation-decision", "args": ws}],
        description="Review pilot evidence and decide ADVANCE / REFINE / PIVOT",
        stage="idea_validation_decision",
    )


def build_experiment_decision_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the post-experiment supervisor decision action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-supervisor-decision", "args": ws}],
        description="Supervisor analyzes results and decides PIVOT or PROCEED",
        stage="experiment_decision",
    )


def build_writing_outline_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the outline-writing action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-outline-writer", "args": ws}],
        description="Generate paper outline",
        stage="writing_outline",
    )


def build_writing_integrate_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the paper integration action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-editor", "args": ws}],
        description="Integrate all sections into coherent paper",
        stage="writing_integrate",
    )


def build_writing_final_review_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the final writing review action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-final-critic", "args": ws}],
        description="Top-tier conference-level paper review",
        stage="writing_final_review",
    )


def build_writing_latex_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the LaTeX conversion/compile action."""
    return action_cls(
        action_type="skill",
        skills=[{
            "name": "sibyl-latex-writer",
            "args": pack_skill_args(
                ws,
                orchestrator.config.ssh_server,
                orchestrator.config.remote_base,
            ),
        }],
        description="将论文转为 NeurIPS LaTeX 格式并编译 PDF",
        stage="writing_latex",
    )


def build_review_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the parallel critic/supervisor/Codex review action."""
    skills = [
        {"name": "sibyl-critic", "args": ws},
        {"name": "sibyl-supervisor", "args": ws},
    ]
    if orchestrator.config.codex_enabled:
        skills.append({
            "name": "sibyl-codex-reviewer",
            "args": codex_reviewer_args(orchestrator.config, "review", ws),
        })
    return action_cls(
        action_type="skills_parallel",
        skills=skills,
        description="并行审查：批评 + 监督" + (" + Codex" if orchestrator.config.codex_enabled else ""),
        stage="review",
    )


def build_reflection_action(
    ws: str,
    iteration: int,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the reflection action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-reflection", "args": pack_skill_args(ws, iteration)}],
        description="Reflection agent: classify issues, generate improvement plan and lessons",
        stage="reflection",
    )


def build_quality_gate_action(
    orchestrator: Any,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the display-only quality gate action."""
    is_done, score, threshold, max_iters, iteration = orchestrator._is_pipeline_done()
    action_plan = _load_workspace_action_plan(orchestrator.ws, persist_normalized=True) or {}
    trajectory = action_plan.get("quality_trajectory", "")
    focus = ""
    recommended_focus = action_plan.get("recommended_focus", [])
    if recommended_focus:
        focus = str(recommended_focus[0])[:120]
    extra_parts = []
    if trajectory:
        extra_parts.append(f"trajectory={trajectory}")
    if focus:
        extra_parts.append(f"focus={focus}")
    extra = f" ({'; '.join(extra_parts)})" if extra_parts else ""

    if is_done:
        return action_cls(
            action_type="done",
            description=(
                f"Pipeline complete (score={score}, threshold={threshold}, "
                f"iter={iteration}/{max_iters}).{extra}"
            ),
            stage="done",
        )

    return action_cls(
        action_type="bash",
        bash_command=f"echo 'Starting iteration {iteration + 1}'",
        description=(
            f"Quality gate: score={score} < {threshold}, "
            f"starting iteration {iteration + 1}{extra}"
        ),
        stage="quality_gate",
    )
