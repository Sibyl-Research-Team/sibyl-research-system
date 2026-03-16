"""Shared orchestration data structures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentTask:
    """A task to be executed by a Claude Code Agent."""

    agent_name: str
    prompt: str
    description: str
    workspace_path: str


@dataclass
class Action:
    """An action for the main Claude Code session to execute."""

    action_type: str
    agents: list[dict] | None = None
    skills: list[dict] | None = None
    team: dict | None = None
    bash_command: str | None = None
    gpu_poll: dict | None = None
    description: str = ""
    stage: str = ""
    iteration: int = 0
    estimated_minutes: int = 0
    checkpoint_info: dict | None = None
    experiment_monitor: dict | None = None
    execution_script: str = ""
