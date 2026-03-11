"""Shared agent/model selection helpers for orchestration."""

from __future__ import annotations

from .common_utils import pack_skill_args


def resolve_model_tier(config: object, agent_name: str) -> tuple[str, str]:
    """Return the configured model tier and model id for an agent name."""
    tier_key = agent_name
    if agent_name.startswith("writer_"):
        tier_key = "section_writer"
    elif agent_name.startswith("critic_") and agent_name != "critic":
        tier_key = "section_critic"
    elif "_critiques_" in agent_name:
        tier_key = "idea_critique"

    tier = config.agent_tier_map.get(tier_key, "standard")
    model = config.model_tiers.get(tier, config.model_tiers["standard"])
    return tier, model


def codex_reviewer_args(config: object, mode: str, ws: str) -> str:
    """Build reviewer args with an optional model override."""
    if config.codex_model:
        return pack_skill_args(ws, mode, config.codex_model)
    return pack_skill_args(ws, mode)


def codex_writer_args(config: object, ws: str) -> str:
    """Build Codex writer args with an optional model override."""
    model = config.codex_writing_model or config.codex_model
    if model:
        return pack_skill_args(ws, model)
    return pack_skill_args(ws)
