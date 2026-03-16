"""Pre-compile action dicts into structured LLM execution scripts.

The execution_script is a deterministic, human-readable instruction block that
tells the main Claude Code session exactly which tools to call — eliminating
the need for the LLM to parse and interpret raw action JSON each loop iteration.

Saves ~50K tokens/cycle by removing action_type dispatch reasoning.
"""

from __future__ import annotations

import shlex
from typing import Any


def render_execution_script(action: dict) -> str:
    """Convert an action dict into a pre-compiled LLM execution script.

    Returns a structured instruction string that the LLM can mechanically
    follow. Returns empty string for unknown action types (fallback to
    manual interpretation).
    """
    action_type = action.get("action_type", "")
    dispatchers = {
        "skill": _script_skill,
        "skills_parallel": _script_skills_parallel,
        "team": _script_team,
        "bash": _script_bash,
        "gpu_poll": _script_gpu_poll,
        "experiment_wait": _script_experiment_wait,
        "agents_parallel": _script_agents_parallel,
        "done": _script_done,
        "stopped": _script_stopped,
    }
    handler = dispatchers.get(action_type)
    if handler is None:
        return ""
    try:
        return handler(action)
    except Exception:
        return ""


def _script_skill(action: dict) -> str:
    """Single skill invocation."""
    skills = action.get("skills") or []
    if not skills:
        return ""
    skill = skills[0]
    name = skill.get("name", "")
    args = skill.get("args", "")

    lines = [
        "## EXECUTION: skill",
        f"1. Skill tool: name={name!r}, args={args!r}",
    ]
    _append_experiment_monitor(lines, action, step=2)
    _append_record(lines, action)
    _append_fallback(lines, action)
    return "\n".join(lines)


def _script_skills_parallel(action: dict) -> str:
    """Parallel skill invocations via Agent tool."""
    skills = action.get("skills") or []
    if not skills:
        return ""

    lines = [
        "## EXECUTION: skills_parallel",
        f"Launch {len(skills)} Agent(s) in parallel:",
    ]
    for i, skill in enumerate(skills, 1):
        name = skill.get("name", "")
        args = skill.get("args", "")
        lines.append(f"  {i}. Agent → Skill: name={name!r}, args={args!r}")

    lines.append(f"{len(skills) + 1}. Wait for all agents to complete.")
    _append_experiment_monitor(lines, action, step=len(skills) + 2)
    _append_record(lines, action)
    _append_fallback(lines, action)
    return "\n".join(lines)


def _script_team(action: dict) -> str:
    """Team-based multi-agent collaboration."""
    team = action.get("team") or {}
    team_name = team.get("team_name", "sibyl-team")
    teammates = team.get("teammates", [])
    post_steps = team.get("post_steps", [])

    lines = [
        "## EXECUTION: team",
        f"1. TeamCreate(team_name={team_name!r})",
        "2. Create tasks for each teammate:",
    ]
    for i, tm in enumerate(teammates):
        name = tm.get("name", f"teammate_{i}")
        skill = tm.get("skill", "")
        args = tm.get("args", "")
        lines.append(
            f"   TaskCreate(subject={name!r}, "
            f"description='Skill /{skill} {args}')"
        )

    lines.append(f"3. Launch {len(teammates)} Agent(s) in parallel:")
    for i, tm in enumerate(teammates):
        name = tm.get("name", f"teammate_{i}")
        lines.append(f"   Agent(team_name={team_name!r}, name={name!r})")

    lines.append("4. Assign tasks via TaskUpdate(owner=teammate.name)")
    lines.append("5. Wait for all teammates to idle")
    lines.append("6. SendMessage(shutdown_request) to each teammate")

    if post_steps:
        lines.append(f"7. Execute {len(post_steps)} post_step(s) sequentially:")
        for j, step in enumerate(post_steps):
            step_type = step.get("type", "skill")
            step_name = step.get("name", step.get("skill", ""))
            step_args = step.get("args", "")
            lines.append(f"   {j + 1}. {step_type}: {step_name} {step_args}")

    _append_record(lines, action)
    _append_fallback(lines, action)
    return "\n".join(lines)


def _script_bash(action: dict) -> str:
    """Direct bash command execution, with optional skill fallback."""
    cmd = action.get("bash_command", "")
    lines = [
        "## EXECUTION: bash",
        f"1. Bash: {cmd}",
    ]

    # Check for fallback skills (e.g., LaTeX compile → skill agent on failure)
    fallback_skills = action.get("skills") or []
    if fallback_skills:
        lines.append("2. If Bash returns status=error/needs_agent=true:")
        for skill in fallback_skills:
            name = skill.get("name", "")
            args = skill.get("args", "")
            lines.append(f"   Fallback → Skill: name={name!r}, args={args!r}")

    _append_record(lines, action)
    return "\n".join(lines)


def _script_gpu_poll(action: dict) -> str:
    """GPU polling wait loop."""
    gpu_poll = action.get("gpu_poll") or {}
    script = gpu_poll.get("script", "")
    marker = gpu_poll.get("marker_file", "")
    interval = gpu_poll.get("interval_sec", 60)
    max_attempts = gpu_poll.get("max_attempts", 0)

    lines = [
        "## EXECUTION: gpu_poll",
        "**Priority: execute gpu_poll.script directly**",
        "1. Write script to /tmp/sibyl_gpu_poll.sh",
        f"2. Bash(run_in_background): bash /tmp/sibyl_gpu_poll.sh",
        f"3. Poll marker_file={marker!r} every {interval}s",
        "4. On exit 0 (GPU found): re-run cli_next() for experiment task",
        f"5. On exit 1 (max {max_attempts} attempts): keep polling (永不放弃)",
    ]
    if not script:
        lines.append("**Fallback: manual SSH polling per CLAUDE.md protocol**")
    return "\n".join(lines)


def _script_experiment_wait(action: dict) -> str:
    """Experiment wait polling loop."""
    monitor = action.get("experiment_monitor") or {}
    task_ids = monitor.get("task_ids", [])
    poll_sec = monitor.get("poll_interval_sec", 300)
    wake_sec = monitor.get("wake_check_interval_sec", 90)
    max_remaining = monitor.get("max_remaining_min", 0)

    lines = [
        "## EXECUTION: experiment_wait",
        f"Monitoring {len(task_ids)} task(s), est. ~{max_remaining}min remaining",
        f"Poll interval: {poll_sec}s, Wake check: {wake_sec}s",
        "",
        "WHILE true:",
        f"  1. Sleep {wake_sec}s segments, check wake_cmd each segment",
        "  2. SSH check_cmd → parse task_id:DONE/PENDING",
        "  3. cli_experiment_status → display status panel",
        "  4. All DONE → sync state (cli_recover_experiments + cli_apply_recovery) → break",
        "  5. IF any task just completed AND pending tasks remain in task_plan.json:",
        "     → call cli_dispatch_tasks to get new assignments",
        "     → for each returned skill, launch a new experimenter Agent",
        "  6. Continue polling",
    ]

    bg_agent = monitor.get("background_agent")
    if bg_agent:
        lines.append("")
        lines.append(
            f"**Background supervisor**: Agent(run_in_background=true) → "
            f"Skill /{bg_agent.get('name', '')} {bg_agent.get('args', '')}"
        )

    _append_record(lines, action)
    return "\n".join(lines)


def _script_agents_parallel(action: dict) -> str:
    """Legacy parallel agents (cross-critique)."""
    agents = action.get("agents") or []
    lines = [
        "## EXECUTION: agents_parallel (legacy)",
        f"Execute {len(agents)} agent(s) sequentially:",
    ]
    for i, agent in enumerate(agents, 1):
        name = agent.get("name", "")
        desc = agent.get("description", "")[:80]
        lines.append(f"  {i}. Agent: {name} — {desc}")

    _append_record(lines, action)
    return "\n".join(lines)


def _script_done(action: dict) -> str:
    """Pipeline completion."""
    desc = action.get("description", "")
    return (
        "## EXECUTION: done\n"
        f"Pipeline complete: {desc}\n"
        "1. Output <promise>SIBYL_PIPELINE_COMPLETE</promise>\n"
        "2. Review quality_gate score\n"
        "3. If not at max quality: cli_next() will start next iteration"
    )


def _script_stopped(action: dict) -> str:
    """Project manually stopped."""
    desc = action.get("description", "")
    return (
        "## EXECUTION: stopped\n"
        f"{desc}\n"
        "If this is a /continue or /resume:\n"
        "1. cli_resume(workspace_path)\n"
        "2. cli_next(workspace_path)"
    )


# ── Helpers ──


def _append_experiment_monitor(lines: list[str], action: dict, step: int) -> None:
    """Add experiment monitor instructions if present."""
    monitor = action.get("experiment_monitor")
    if not monitor:
        return

    bg_agent = monitor.get("background_agent")
    if bg_agent:
        name = bg_agent.get("name", "")
        args = bg_agent.get("args", "")
        lines.append(
            f"{step}. Agent(run_in_background=true) → "
            f"Skill /{name} {args}"
        )
    else:
        lines.append(
            f"{step}. [Hook auto-starts bash monitor daemon — no action needed]"
        )


def _append_record(lines: list[str], action: dict) -> None:
    """Add cli_record instruction."""
    stage = action.get("stage", "")
    if stage and stage not in ("done", "stopped", "init", "quality_gate"):
        lines.append("")
        lines.append(f"**On completion**: cli_record(workspace, {stage!r})")


def _append_fallback(lines: list[str], action: dict) -> None:
    """Add fallback instruction for error cases."""
    lines.append("**On error**: log to errors.jsonl, retry up to 3x, then skip+continue")
