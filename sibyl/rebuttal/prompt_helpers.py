"""Rebuttal-specific prompt rendering helpers."""

from __future__ import annotations

import json
from pathlib import Path

from sibyl.orchestration.prompt_loader import (
    PROMPTS_DIR,
    PromptSection,
    _build_shared_runtime_sections,
    _load_prompt_body,
    _render_prompt_sections,
)


def render_rebuttal_skill_prompt(
    agent_name: str,
    workspace_path: str | Path | None = None,
    mode: str = "",
    round_num: int = 1,
) -> str:
    """Compile prompt for a rebuttal agent, injecting round context."""
    role_prompt = _load_prompt_body(agent_name)
    if not role_prompt:
        return ""

    sections = _build_shared_runtime_sections(
        workspace_path=workspace_path,
        agent_name=agent_name,
    )

    # Inject round context
    if workspace_path:
        ws = Path(workspace_path)
        round_ctx = _build_round_context(ws, round_num)
        if round_ctx:
            sections.append(PromptSection("Round Context", round_ctx))

        if mode:
            sections.append(PromptSection("Execution Mode", f"Mode: {mode}"))

    sections.append(PromptSection("Role Protocol", role_prompt))

    return _render_prompt_sections(
        sections,
        heading=f"# Compiled Sibyl Rebuttal Prompt: {agent_name}",
    )


def render_reviewer_persona_prompt(
    workspace_path: str,
    reviewer_id: str,
    round_num: int = 1,
) -> str:
    """Build a simulated reviewer prompt from real review text + persona."""
    ws = Path(workspace_path)

    # Load base template
    base_prompt = _load_prompt_body("simulated_reviewer")
    if not base_prompt:
        return ""

    # Load original review
    original_review = _find_and_read_review(ws, reviewer_id)

    # Load reviewer profile
    profile = _load_reviewer_profile(ws, reviewer_id)

    # Load current rebuttal draft
    rebuttal_draft = _load_current_rebuttal(ws, round_num, reviewer_id)

    # Load previous round sim review (if round > 1)
    prev_review = ""
    if round_num > 1:
        prev_review = _load_prev_sim_review(ws, round_num - 1, reviewer_id)

    sections = _build_shared_runtime_sections(
        workspace_path=workspace_path,
        agent_name="simulated_reviewer",
    )

    sections.append(PromptSection("Role Protocol", base_prompt))

    sections.append(PromptSection(
        "Reviewer Identity",
        f"You are Reviewer **{reviewer_id}**. "
        f"You must evaluate the rebuttal from YOUR original perspective.\n\n"
        f"## Your Original Review\n{original_review}"
    ))

    if profile:
        sections.append(PromptSection("Reviewer Profile", profile))

    if rebuttal_draft:
        sections.append(PromptSection(
            "Rebuttal to Evaluate",
            f"The authors have submitted the following rebuttal for Round {round_num}:\n\n"
            f"{rebuttal_draft}"
        ))

    if prev_review:
        sections.append(PromptSection(
            "Your Previous Round Feedback",
            f"Your feedback from Round {round_num - 1}:\n\n{prev_review}"
        ))

    return _render_prompt_sections(
        sections,
        heading=f"# Compiled Simulated Reviewer Prompt: {reviewer_id}",
    )


def _build_round_context(ws: Path, round_num: int) -> str:
    """Build context string for the current round."""
    parts = [f"**Current Round**: {round_num}"]

    # Concerns
    concerns_file = ws / "parsed/concerns.json"
    if concerns_file.exists():
        try:
            data = json.loads(concerns_file.read_text(encoding="utf-8"))
            total = sum(len(v) if isinstance(v, list) else 0 for v in data.values())
            parts.append(f"**Total Concerns**: {total}")
        except (json.JSONDecodeError, OSError):
            pass

    # Previous round scores
    if round_num > 1:
        prev_scores_file = ws / f"rounds/round_{round_num - 1:03d}/scores.json"
        if prev_scores_file.exists():
            try:
                scores = json.loads(prev_scores_file.read_text(encoding="utf-8"))
                parts.append(f"**Previous Round Avg Score**: {scores.get('avg_score', 'N/A')}")
            except (json.JSONDecodeError, OSError):
                pass

    # Strategy
    strategy_file = ws / "parsed/priority_matrix.json"
    if strategy_file.exists():
        parts.append(f"**Strategy**: Read {strategy_file}")

    return "\n".join(parts)


def _find_and_read_review(ws: Path, reviewer_id: str) -> str:
    """Find and read the original review file for a reviewer."""
    reviews_dir = ws / "input/reviews"
    for ext in (".md", ".txt", ".json", ".pdf"):
        candidate = reviews_dir / f"{reviewer_id}{ext}"
        if candidate.exists():
            if ext == ".json":
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    return json.dumps(data, indent=2, ensure_ascii=False)
                except (json.JSONDecodeError, OSError):
                    pass
            else:
                try:
                    return candidate.read_text(encoding="utf-8")
                except OSError:
                    pass
    # Fallback: try partial match
    if reviews_dir.exists():
        for f in reviews_dir.iterdir():
            if reviewer_id in f.stem:
                try:
                    return f.read_text(encoding="utf-8")
                except OSError:
                    pass
    return f"[Original review for {reviewer_id} not found]"


def _load_reviewer_profile(ws: Path, reviewer_id: str) -> str:
    """Load inferred reviewer personality/focus profile."""
    profiles_file = ws / "parsed/reviewer_profiles.json"
    if not profiles_file.exists():
        return ""
    try:
        profiles = json.loads(profiles_file.read_text(encoding="utf-8"))
        profile = profiles.get(reviewer_id, {})
        if profile:
            return json.dumps(profile, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, OSError):
        pass
    return ""


def _load_current_rebuttal(ws: Path, round_num: int, reviewer_id: str) -> str:
    """Load the current round's rebuttal draft for a specific reviewer."""
    # Try per-reviewer response first
    per_reviewer = ws / f"rounds/round_{round_num:03d}/synthesis/per_reviewer/{reviewer_id}.md"
    if per_reviewer.exists():
        try:
            return per_reviewer.read_text(encoding="utf-8")
        except OSError:
            pass
    # Fallback to unified draft
    unified = ws / f"rounds/round_{round_num:03d}/synthesis/rebuttal_draft.md"
    if unified.exists():
        try:
            return unified.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""


def _load_prev_sim_review(ws: Path, prev_round: int, reviewer_id: str) -> str:
    """Load previous round's simulated review for continuity."""
    prev_file = ws / f"rounds/round_{prev_round:03d}/sim_review/{reviewer_id}.md"
    if prev_file.exists():
        try:
            return prev_file.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""
