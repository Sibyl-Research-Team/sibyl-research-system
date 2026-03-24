"""Rebuttal action builders for each pipeline stage."""

from __future__ import annotations

from typing import Any

from sibyl.orchestration.common_utils import pack_skill_args
from sibyl.orchestration.models import Action
from sibyl.orchestration.prompt_loader import render_team_prompt

from .constants import REBUTTAL_TEAM_ROLES
from .scoring import get_current_round


def build_parse_reviews_action(ws: str) -> Action:
    """Parse reviewer comments into structured atomic concerns."""
    return Action(
        action_type="skill",
        skills=[{"name": "sibyl-rebuttal-strategist", "args": pack_skill_args(ws, "parse")}],
        description="解析 reviewer 评价，分解为原子 concern，生成 reviewer 人格画像",
        stage="parse_reviews",
    )


def build_strategy_action(ws: str) -> Action:
    """Strategist analyzes concerns and builds response priority matrix."""
    return Action(
        action_type="skill",
        skills=[{"name": "sibyl-rebuttal-strategist", "args": pack_skill_args(ws, "strategy")}],
        description="策略分析：优先级排序、回应路线图、证据需求清单",
        stage="strategy",
    )


def build_rebuttal_draft_action(
    orchestrator: Any,
    ws: str,
) -> Action:
    """Team action: 8 rebuttal agents + synthesizer post_step (+optional Codex)."""
    rc = orchestrator.rebuttal_config
    round_num = get_current_round(orchestrator.workspace_path)

    teammates = [
        {"name": "strategist", "skill": "sibyl-rebuttal-strategist",
         "args": pack_skill_args(ws, "draft", round_num)},
        {"name": "scholar", "skill": "sibyl-rebuttal-scholar",
         "args": pack_skill_args(ws, round_num)},
        {"name": "theorist", "skill": "sibyl-rebuttal-theorist",
         "args": pack_skill_args(ws, round_num)},
        {"name": "experimentalist", "skill": "sibyl-rebuttal-experimentalist",
         "args": pack_skill_args(ws, round_num)},
        {"name": "writer", "skill": "sibyl-rebuttal-writer",
         "args": pack_skill_args(ws, round_num)},
        {"name": "advocate", "skill": "sibyl-rebuttal-advocate",
         "args": pack_skill_args(ws, round_num)},
        {"name": "diplomat", "skill": "sibyl-rebuttal-diplomat",
         "args": pack_skill_args(ws, round_num)},
        {"name": "checker", "skill": "sibyl-rebuttal-checker",
         "args": pack_skill_args(ws, round_num)},
    ]

    post_steps = [
        {"type": "skill", "skill": "sibyl-rebuttal-synthesizer",
         "args": pack_skill_args(ws, round_num)},
    ]

    word_limit_hint = ""
    if rc.word_limit > 0:
        word_limit_hint = (
            f"\n\n**Word Limit**: Each per-reviewer response must stay within "
            f"{rc.word_limit} words. Prioritize impact over completeness."
        )

    team_instructions = (
        f"Rebuttal Draft — Round {round_num}\n\n"
        f"Read parsed concerns from {ws}/parsed/concerns.json and strategy from "
        f"{ws}/parsed/priority_matrix.json.\n\n"
        f"Each teammate writes their analysis to {ws}/rounds/current/team/<role>.md\n\n"
        f"**Roles**:\n"
        f"- strategist: Update response strategy based on previous round feedback\n"
        f"- scholar: Search literature for supporting evidence and citations\n"
        f"- theorist: Strengthen theoretical arguments and proofs\n"
        f"- experimentalist: Design supplementary experiments (plan only, NOT execute)\n"
        f"- writer: Draft formal rebuttal responses per reviewer\n"
        f"- advocate: Find every possible supporting angle\n"
        f"- diplomat: Ensure respectful tone, acknowledge valid criticisms\n"
        f"- checker: QA — verify logic consistency, catch self-contradictions\n\n"
        f"After all teammates finish, the synthesizer merges into a structured rebuttal "
        f"at {ws}/rounds/current/synthesis/\n"
        f"{word_limit_hint}"
    )

    if round_num > 1:
        team_instructions = (
            f"**This is refinement round {round_num}**. Read simulated reviewer feedback "
            f"from the previous round at {ws}/rounds/current/prev_round_feedback.json "
            f"and the simulated reviews at the path indicated therein. "
            f"Focus on addressing remaining and new concerns.\n\n"
            + team_instructions
        )

    team_prompt = render_team_prompt(
        f"Rebuttal Draft Round {round_num}",
        team_instructions,
        workspace_path=ws,
        language=rc.language,
    )

    return Action(
        action_type="team",
        team={
            "team_name": "sibyl-rebuttal-team",
            "teammates": teammates,
            "post_steps": post_steps,
            "prompt": team_prompt,
        },
        description=f"Rebuttal Team: 8人起草 + 综合 (Round {round_num})",
        stage="rebuttal_draft",
    )


def build_simulated_review_action(
    orchestrator: Any,
    ws: str,
) -> Action:
    """Parallel simulated reviewers re-evaluate the rebuttal."""
    rc = orchestrator.rebuttal_config
    if not rc.reviewer_ids:
        raise ValueError(
            f"No reviewer_ids configured for workspace {ws}. "
            "Run cli_rebuttal_init first or check rebuttal_config.yaml."
        )
    round_num = get_current_round(orchestrator.workspace_path)

    skills = [
        {"name": "sibyl-simulated-reviewer",
         "args": pack_skill_args(ws, reviewer_id, round_num)}
        for reviewer_id in rc.reviewer_ids
    ]

    return Action(
        action_type="skills_parallel",
        skills=skills,
        description=f"模拟 {len(skills)} 位 Reviewer 攻击 rebuttal (Round {round_num})",
        stage="simulated_review",
    )


def build_codex_review_action(
    orchestrator: Any,
    ws: str,
) -> Action:
    """Optional Codex independent review of the current rebuttal draft."""
    round_num = get_current_round(orchestrator.workspace_path)
    args = pack_skill_args(ws, "rebuttal", round_num)
    if orchestrator.rebuttal_config.codex_model:
        args = pack_skill_args(ws, "rebuttal", round_num, orchestrator.rebuttal_config.codex_model)

    return Action(
        action_type="skill",
        skills=[{"name": "sibyl-codex-reviewer", "args": args}],
        description=f"Codex 独立审查 rebuttal (Round {round_num})",
        stage="codex_review",
    )


def build_score_evaluate_action(
    orchestrator: Any,
    ws: str,
) -> Action:
    """Evaluate round scores and decide: iterate or finalize."""
    round_num = get_current_round(orchestrator.workspace_path)
    return Action(
        action_type="skill",
        skills=[{"name": "sibyl-rebuttal-strategist",
                 "args": pack_skill_args(ws, "evaluate", round_num)}],
        description=f"评估 Round {round_num} 分数，决定迭代或收敛",
        stage="score_evaluate",
    )


def build_final_synthesis_action(
    orchestrator: Any,
    ws: str,
) -> Action:
    """Final synthesis: polish, word limit enforcement, formatting."""
    rc = orchestrator.rebuttal_config
    return Action(
        action_type="skill",
        skills=[{"name": "sibyl-rebuttal-synthesizer",
                 "args": pack_skill_args(ws, "final", rc.word_limit)}],
        description=f"最终综合：打磨 rebuttal，强制字数限制 ({rc.word_limit or 'unlimited'})",
        stage="final_synthesis",
    )
