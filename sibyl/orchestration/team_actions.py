"""Team-oriented action builders extracted from the legacy orchestrator."""

from __future__ import annotations

from typing import Any

from .agent_helpers import codex_reviewer_args, codex_writer_args
from .checkpointing import get_or_create_checkpoint
from .common_utils import (
    non_paper_output_requirement,
    pack_skill_args,
    paper_writing_requirement,
)
from .constants import PAPER_SECTIONS
from .prompt_loader import render_team_prompt


def _candidate_hint_for_focus(focus: int) -> str:
    """Return the candidate pool instruction adjusted for research_focus level."""
    if focus <= 1:
        return (
            "Maintain a broad candidate pool: keep 3-4 serious ideas alive. Prioritize "
            "diversity of approaches over depth. Do not converge prematurely.\n\n"
        )
    if focus == 2:
        return (
            "Maintain a candidate pool: keep 2-3 serious ideas alive. Be willing to "
            "explore alternatives rather than over-investing in one direction.\n\n"
        )
    if focus == 4:
        return (
            "Maintain a focused candidate pool: keep 1-2 serious ideas alive. Concentrate "
            "effort on the strongest idea. Only keep a backup if it is fundamentally different.\n\n"
        )
    if focus >= 5:
        return (
            "Focus on 1 front-runner candidate. Invest all effort in deepening this idea. "
            "Keep at most 1 backup only if truly orthogonal to the main direction.\n\n"
        )
    # focus == 3 (balanced, default)
    return (
        "Maintain a small candidate pool: keep 2-3 serious ideas alive until pilot evidence "
        "separates them. Do not collapse to a single idea too early unless the evidence is overwhelming.\n\n"
    )


def _completed_checkpoint_action(
    *,
    action_cls: type[Any],
    bash_command: str,
    description: str,
    stage: str,
    checkpoint_info: dict,
) -> Any:
    return action_cls(
        action_type="bash",
        bash_command=bash_command,
        description=description,
        stage=stage,
        checkpoint_info=checkpoint_info,
    )


def build_idea_debate_action(
    orchestrator: Any,
    topic: str,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the idea-debate team action with checkpoint-aware context prep."""
    idea_roles = [
        "innovator",
        "pragmatist",
        "theoretical",
        "contrarian",
        "interdisciplinary",
        "empiricist",
    ]
    steps = {role: f"idea/perspectives/{role}.md" for role in idea_roles}
    cp_info = get_or_create_checkpoint(orchestrator, "idea_debate", steps)

    if cp_info and cp_info["all_complete"]:
        return _completed_checkpoint_action(
            action_cls=action_cls,
            bash_command="echo 'All idea perspectives already written (checkpoint valid)'",
            description="所有视角提案已完成（checkpoint 校验通过），可直接 record",
            stage="idea_debate",
            checkpoint_info=cp_info,
        )

    spec = orchestrator.ws.read_file("spec.md") or ""
    initial_ideas = orchestrator.ws.read_file("idea/initial_ideas.md") or ""
    seed_refs = orchestrator.ws.read_file("idea/references_seed.md") or ""
    literature = orchestrator.ws.read_file("context/literature.md") or ""
    prior_proposal = orchestrator.ws.read_file("idea/proposal.md") or ""
    prior_hypotheses = orchestrator.ws.read_file("idea/hypotheses.md") or ""
    pilot_summary = orchestrator.ws.read_file("exp/results/pilot_summary.md") or ""
    pilot_summary_json = orchestrator.ws.read_file("exp/results/pilot_summary.json") or ""
    candidate_ideas = orchestrator.ws.read_file("idea/candidates.json") or ""
    validation_feedback = orchestrator.ws.read_file("supervisor/idea_validation_decision.md") or ""
    validation_feedback_json = (
        orchestrator.ws.read_file("supervisor/idea_validation_decision.json") or ""
    )
    validation_round = orchestrator._get_current_validation_round()

    extra_context = ""
    if spec:
        extra_context += f"\n\n## Project Spec\n{spec}"
    if initial_ideas:
        extra_context += f"\n\n## User's Initial Ideas\n{initial_ideas}"
    if seed_refs:
        extra_context += f"\n\n## Seed References (from user)\n{seed_refs}"
    if literature:
        extra_context += f"\n\n## 文献调研报告（请仔细阅读，避免重复已有工作）\n{literature}"
    if prior_proposal:
        extra_context += (
            "\n\n## 当前综合提案（如已有，请在此基础上迭代，而不是从零开始）\n"
            f"{prior_proposal}"
        )
    if prior_hypotheses:
        extra_context += f"\n\n## 当前可检验假设\n{prior_hypotheses}"
    if pilot_summary:
        extra_context += (
            "\n\n## 小型实验真实反馈（必须基于这些证据修正 idea，不能忽略负结果）\n"
            f"{pilot_summary}"
        )
    if pilot_summary_json:
        extra_context += (
            "\n\n## 小型实验结构化信号（供你提炼 go/no-go / confidence / hypothesis status）\n"
            f"{pilot_summary_json}"
        )
    if candidate_ideas:
        extra_context += (
            "\n\n## 当前候选 idea 池（保留 2-3 个候选，必要时淘汰或替换）\n"
            f"{candidate_ideas}"
        )
    if validation_feedback:
        extra_context += f"\n\n## 上一轮 validation 决策意见\n{validation_feedback}"
    if validation_feedback_json:
        extra_context += (
            "\n\n## 上一轮 validation 结构化决策\n"
            f"{validation_feedback_json}"
        )

    # Novelty and Codex feedback from prior rounds (drives refinement)
    novelty_report = orchestrator.ws.read_file("idea/novelty_report.md") or ""
    codex_feedback = orchestrator.ws.read_file("codex/idea_debate_review.md") or ""
    if novelty_report:
        extra_context += (
            "\n\n## 上一轮新颖性检查报告（必须针对发现的撞车问题进行修正）\n"
            f"{novelty_report}"
        )
    if codex_feedback:
        extra_context += (
            "\n\n## Codex 独立评审反馈（必须针对其指出的问题进行修正）\n"
            f"{codex_feedback}"
        )

    if extra_context:
        orchestrator.ws.write_file("context/idea_context.md", extra_context)

    remaining = set(cp_info["remaining_steps"]) if cp_info else set(idea_roles)

    refinement_hint = ""
    if pilot_summary:
        refinement_hint = (
            "This is an evidence-driven refinement round. Read the pilot summary carefully, "
            "update or discard hypotheses that the data weakened, preserve the parts that "
            "show early promise, and make the next proposal easier to falsify.\n\n"
        )
        if validation_round > 0:
            refinement_hint = (
                f"This is evidence-driven refinement round {validation_round + 1}. "
                + refinement_hint
            )
    candidate_hint = _candidate_hint_for_focus(orchestrator.config.research_focus)

    team_instructions = (
        f"Generate and debate research ideas for: {topic}\n\n"
        f"{refinement_hint}"
        f"{candidate_hint}"
        f"Spawn teammates for remaining perspectives:\n"
        + "\n".join(f"- {role}" for role in idea_roles if role in remaining)
        + "\n\n"
        f"Each reads {ws}/context/idea_context.md for background and writes to "
        f"{ws}/idea/perspectives/<role>.md\n\n"
        f"After generating ideas, have teammates critique each other's work (score 1-10). "
        f"Write critiques to {ws}/idea/debate/CRITIC_on_AUTHOR.md\n\n"
        f"Finally, synthesize all ideas and critiques into a final proposal at "
        f"{ws}/idea/proposal.md. Pick the strongest idea, incorporating feedback.\n\n"
        f"Run exactly {orchestrator.config.debate_rounds} critique rounds before final synthesis.\n"
        f"{non_paper_output_requirement(orchestrator.config.language)} Use Sonnet for teammates."
    )
    team_prompt = render_team_prompt(
        f"Idea debate for {topic}",
        team_instructions,
        workspace_path=ws,
        language=orchestrator.config.language,
    )

    all_teammates = [
        {"name": "innovator", "skill": "sibyl-innovator", "args": pack_skill_args(ws, topic)},
        {"name": "pragmatist", "skill": "sibyl-pragmatist", "args": pack_skill_args(ws, topic)},
        {"name": "theoretical", "skill": "sibyl-theoretical", "args": pack_skill_args(ws, topic)},
        {"name": "contrarian", "skill": "sibyl-contrarian", "args": pack_skill_args(ws, topic)},
        {
            "name": "interdisciplinary",
            "skill": "sibyl-interdisciplinary",
            "args": pack_skill_args(ws, topic),
        },
        {"name": "empiricist", "skill": "sibyl-empiricist", "args": pack_skill_args(ws, topic)},
    ]
    teammates = [teammate for teammate in all_teammates if teammate["name"] in remaining]

    post_steps = [
        {"type": "skill", "skill": "sibyl-synthesizer", "args": ws},
        {"type": "skill", "skill": "sibyl-novelty-checker", "args": ws},
    ]
    if orchestrator.config.codex_enabled:
        post_steps.append({
            "type": "codex",
            "skill": "sibyl-codex-reviewer",
            "args": codex_reviewer_args(orchestrator.config, "idea_debate", ws),
        })

    return action_cls(
        action_type="team",
        team={
            "team_name": "sibyl-idea-debate",
            "teammates": teammates,
            "post_steps": post_steps,
            "prompt": team_prompt,
        },
        description=f"Agent Team: {len(teammates)}人辩论生成研究提案"
        + (
            f"（恢复：已完成 {len(cp_info['completed_steps'])}/6）"
            if cp_info and cp_info["resuming"]
            else "（创新者+实用主义者+理论家+反对者+跨学科者+实验主义者）"
        )
        + (" + Codex 独立审查" if orchestrator.config.codex_enabled else ""),
        stage="idea_debate",
        checkpoint_info=cp_info,
    )


def build_result_debate_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the result-debate team action."""
    result_roles = [
        "optimist",
        "skeptic",
        "strategist",
        "methodologist",
        "comparativist",
        "revisionist",
    ]
    steps = {role: f"idea/result_debate/{role}.md" for role in result_roles}
    cp_info = get_or_create_checkpoint(orchestrator, "result_debate", steps)

    if cp_info and cp_info["all_complete"]:
        return _completed_checkpoint_action(
            action_cls=action_cls,
            bash_command="echo 'All result analyses already written (checkpoint valid)'",
            description="所有结果分析已完成（checkpoint 校验通过），可直接 record",
            stage="result_debate",
            checkpoint_info=cp_info,
        )

    remaining = set(cp_info["remaining_steps"]) if cp_info else set(result_roles)
    team_instructions = (
        f"Read experiment results from {ws}/exp/results/ and debate what they mean.\n\n"
        f"Spawn teammates for remaining perspectives:\n"
        + "\n".join(f"- {role}" for role in result_roles if role in remaining)
        + "\n\n"
        f"Have them debate each other's positions. The skeptic and methodologist "
        f"should challenge the optimist's claims. The comparativist grounds the "
        f"discussion in external context. The revisionist updates our mental model. "
        f"The strategist synthesizes into actionable next steps.\n\n"
        f"Each teammate writes analysis to {ws}/idea/result_debate/ROLE.md\n"
        f"Run exactly {orchestrator.config.debate_rounds} debate rounds before the strategist synthesizes the final view.\n"
        f"{non_paper_output_requirement(orchestrator.config.language)}"
    )
    team_prompt = render_team_prompt(
        "Result debate",
        team_instructions,
        workspace_path=ws,
        language=orchestrator.config.language,
    )

    all_teammates = [
        {"name": "optimist", "skill": "sibyl-optimist", "args": ws},
        {"name": "skeptic", "skill": "sibyl-skeptic", "args": ws},
        {"name": "strategist", "skill": "sibyl-strategist", "args": ws},
        {"name": "methodologist", "skill": "sibyl-methodologist", "args": ws},
        {"name": "comparativist", "skill": "sibyl-comparativist", "args": ws},
        {"name": "revisionist", "skill": "sibyl-revisionist", "args": ws},
    ]
    teammates = [teammate for teammate in all_teammates if teammate["name"] in remaining]

    post_steps = [
        {"type": "skill", "skill": "sibyl-result-synthesizer", "args": ws},
    ]
    if orchestrator.config.codex_enabled:
        post_steps.append({
            "type": "codex",
            "skill": "sibyl-codex-reviewer",
            "args": codex_reviewer_args(orchestrator.config, "result_debate", ws),
        })

    return action_cls(
        action_type="team",
        team={
            "team_name": "sibyl-result-debate",
            "teammates": teammates,
            "post_steps": post_steps,
            "prompt": team_prompt,
        },
        description=f"Agent Team: {len(teammates)}人辩论实验结果"
        + (
            f"（恢复：已完成 {len(cp_info['completed_steps'])}/6）"
            if cp_info and cp_info["resuming"]
            else "（乐观者+怀疑论者+战略家+方法论者+比较分析者+修正主义者）"
        )
        + " → 综合裁决"
        + (" + Codex 独立审查" if orchestrator.config.codex_enabled else ""),
        stage="result_debate",
        checkpoint_info=cp_info,
    )


def build_writing_sections_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the writing-sections action across sequential/codex/team modes."""
    mode = orchestrator.config.writing_mode
    codex_fallback = mode == "codex" and not orchestrator.config.codex_enabled
    if codex_fallback:
        mode = "parallel"

    steps = {sid: f"writing/sections/{sid}.md" for sid, _ in PAPER_SECTIONS}
    cp_info = get_or_create_checkpoint(orchestrator, "writing_sections", steps)

    if cp_info and cp_info["all_complete"]:
        return _completed_checkpoint_action(
            action_cls=action_cls,
            bash_command="echo 'All sections already written (checkpoint valid)'",
            description="所有章节已完成（checkpoint 校验通过），可直接 record",
            stage="writing_sections",
            checkpoint_info=cp_info,
        )

    if mode == "sequential":
        return action_cls(
            action_type="skill",
            skills=[{"name": "sibyl-sequential-writer", "args": ws}],
            description="顺序撰写论文各章节（确保行文一致性）",
            stage="writing_sections",
            checkpoint_info=cp_info,
        )
    if mode == "codex":
        return action_cls(
            action_type="skill",
            skills=[{"name": "sibyl-codex-writer", "args": codex_writer_args(orchestrator.config, ws)}],
            description="使用 Codex (GPT-5) 撰写论文各章节",
            stage="writing_sections",
            checkpoint_info=cp_info,
        )

    remaining = set(cp_info["remaining_steps"]) if cp_info else None
    sections_info = "\n".join(
        f"- {name} (section id: {sid}): write to {ws}/writing/sections/{sid}.md"
        for sid, name in PAPER_SECTIONS
        if remaining is None or sid in remaining
    )
    team_instructions = (
        f"Read outline from {ws}/writing/outline.md and experiment results from {ws}/exp/results/.\n\n"
        f"Spawn teammates for remaining sections:\n{sections_info}\n\n"
        f"Teammates should coordinate for consistency — share key definitions, "
        f"notation, and cross-references between sections.\n"
        f"{paper_writing_requirement()}"
    )
    team_prompt = render_team_prompt(
        "Parallel section drafting",
        team_instructions,
        workspace_path=ws,
        language=orchestrator.config.language,
        paper_output=True,
    )
    teammates = [
        {
            "name": f"writer-{sid}",
            "skill": "sibyl-section-writer",
            "args": pack_skill_args(ws, name, sid),
        }
        for sid, name in PAPER_SECTIONS
        if remaining is None or sid in remaining
    ]

    return action_cls(
        action_type="team",
        team={
            "team_name": "sibyl-writing-sections",
            "teammates": teammates,
            "post_steps": [],
            "prompt": team_prompt,
        },
        description=f"Agent Team: {len(teammates)}人并行撰写论文章节"
        + ("（Codex 未启用，已自动回退）" if codex_fallback else "")
        + (
            f"（恢复：已完成 {len(cp_info['completed_steps'])}/6）"
            if cp_info and cp_info["resuming"]
            else ""
        ),
        stage="writing_sections",
        checkpoint_info=cp_info,
    )


def build_writing_critique_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the writing-critique team action."""
    steps = {sid: f"writing/critique/{sid}_critique.md" for sid, _ in PAPER_SECTIONS}
    cp_info = get_or_create_checkpoint(orchestrator, "writing_critique", steps)

    if cp_info and cp_info["all_complete"]:
        return _completed_checkpoint_action(
            action_cls=action_cls,
            bash_command="echo 'All critiques already written (checkpoint valid)'",
            description="所有批评已完成（checkpoint 校验通过），可直接 record",
            stage="writing_critique",
            checkpoint_info=cp_info,
        )

    remaining = set(cp_info["remaining_steps"]) if cp_info else None
    sections_info = "\n".join(
        f"- Critic for {name}: read {ws}/writing/sections/{sid}.md, "
        f"write critique to {ws}/writing/critique/{sid}_critique.md"
        for sid, name in PAPER_SECTIONS
        if remaining is None or sid in remaining
    )
    team_instructions = (
        f"Spawn teammates for remaining critiques:\n{sections_info}\n\n"
        f"Critics should cross-reference other sections for consistency issues. "
        f"Score each section 1-10 and provide specific improvement suggestions.\n"
        f"{paper_writing_requirement()}"
    )
    team_prompt = render_team_prompt(
        "Parallel section critique",
        team_instructions,
        workspace_path=ws,
        language=orchestrator.config.language,
        paper_output=True,
    )
    teammates = [
        {
            "name": f"critic-{sid}",
            "skill": "sibyl-section-critic",
            "args": pack_skill_args(ws, name, sid),
        }
        for sid, name in PAPER_SECTIONS
        if remaining is None or sid in remaining
    ]

    return action_cls(
        action_type="team",
        team={
            "team_name": "sibyl-writing-critique",
            "teammates": teammates,
            "post_steps": [],
            "prompt": team_prompt,
        },
        description=f"Agent Team: {len(teammates)}人并行批评论文章节"
        + (
            f"（恢复：已完成 {len(cp_info['completed_steps'])}/6）"
            if cp_info and cp_info["resuming"]
            else ""
        ),
        stage="writing_critique",
        checkpoint_info=cp_info,
    )
