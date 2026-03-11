"""Operational CLI helpers for self-heal and event logging."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from sibyl.event_logger import EventLogger
from sibyl.workspace import Workspace

from .common_utils import build_repo_python_cli_command, self_heal_status_file


def cli_self_heal_scan(workspace_path: str = "") -> None:
    """Scan for errors and generate repair tasks."""
    from sibyl.error_collector import ErrorCollector
    from sibyl.self_heal import SelfHealRouter

    if workspace_path:
        errors_file = Path(workspace_path) / "logs" / "errors.jsonl"
        state_file = Path(workspace_path) / "logs" / "self_heal_state.json"
    else:
        errors_file = Path("logs") / "errors.jsonl"
        state_file = Path("logs") / "self_heal_state.json"

    collector = ErrorCollector(errors_file)
    router = SelfHealRouter(state_file)

    errors = collector.read_errors(unprocessed_only=True)
    errors = router.deduplicate(errors)
    errors = router.filter_actionable(errors)
    errors = router.prioritize(errors)
    tasks = [router.generate_repair_task(error) for error in errors]

    print(json.dumps({
        "total_unprocessed": len(collector.read_errors(unprocessed_only=True)),
        "actionable": len(tasks),
        "tasks": tasks,
        "self_heal_status": router.get_status(),
    }, indent=2))


def cli_self_heal_record(
    error_id: str,
    success: bool,
    commit_hash: str = "",
    workspace_path: str = "",
) -> None:
    """Record a self-heal fix attempt result."""
    from sibyl.error_collector import ErrorCollector
    from sibyl.self_heal import SelfHealRouter

    if workspace_path:
        errors_file = Path(workspace_path) / "logs" / "errors.jsonl"
        state_file = Path(workspace_path) / "logs" / "self_heal_state.json"
    else:
        errors_file = Path("logs") / "errors.jsonl"
        state_file = Path("logs") / "self_heal_state.json"

    collector = ErrorCollector(errors_file)
    router = SelfHealRouter(state_file)
    router.record_fix_attempt(error_id, success, commit_hash or None)
    if success:
        collector.mark_processed(error_id)

    print(json.dumps({
        "error_id": error_id,
        "success": success,
        "commit": commit_hash,
        "status": router.get_status(),
    }, indent=2))


def cli_self_heal_status(workspace_path: str = "") -> None:
    """Show self-heal system status."""
    from sibyl.self_heal import SelfHealRouter

    state_file = (
        Path(workspace_path) / "logs" / "self_heal_state.json"
        if workspace_path
        else Path("logs") / "self_heal_state.json"
    )
    router = SelfHealRouter(state_file)
    status = router.get_status()

    print(json.dumps({
        "self_heal": status,
        "summary": {
            "fixed_count": len(status["fixed"]),
            "circuit_broken_count": len(status["circuit_broken"]),
            "in_progress_count": len(status["in_progress"]),
        },
    }, indent=2))


def self_heal_monitor_script(
    workspace_path: str,
    *,
    interval_sec: int = 300,
) -> str:
    """Generate a background monitor script for self-healing."""
    status_file = self_heal_status_file(workspace_path)
    scan_cmd = build_repo_python_cli_command("self-heal-scan", workspace_path)
    actionable_cmd = shlex.join([
        sys.executable,
        "-c",
        "import json, sys; data = json.load(sys.stdin); print(data.get('actionable', 0))",
    ])
    return f'''#!/usr/bin/env bash
# Sibyl Self-Heal Monitor — auto-generated
WORKSPACE={shlex.quote(workspace_path)}
ERRORS_FILE="$WORKSPACE/logs/errors.jsonl"
STATUS_FILE={shlex.quote(status_file)}
INTERVAL={interval_sec}

while true; do
    if [ -f "$ERRORS_FILE" ]; then
        RESULT=$({scan_cmd} 2>/dev/null)
        printf '%s\n' "$RESULT" > "$STATUS_FILE"

        # Check if there are actionable tasks
        ACTIONABLE=$({actionable_cmd} <<< "$RESULT" 2>/dev/null || echo "0")

        if [ "$ACTIONABLE" -gt 0 ]; then
            printf '{{"needs_repair": true, "actionable": %s, "timestamp": %s}}\n' "$ACTIONABLE" "$(date +%s)" > "$STATUS_FILE.trigger"
        fi
    fi
    sleep "$INTERVAL"
done
'''


def cli_log_agent(
    workspace_path: str,
    stage: str,
    agent_name: str,
    *,
    event: str = "start",
    model_tier: str = "",
    status: str = "ok",
    duration_sec: float | None = None,
    output_files: str = "",
    output_summary: str = "",
    prompt_summary: str = "",
) -> None:
    """Log an agent invocation event (start or end)."""
    ws_path = Path(workspace_path)
    ws = Workspace(ws_path.parent, ws_path.name)
    ws_status = ws.get_status()
    if not stage:
        stage = ws_status.stage
    event_logger = EventLogger(ws.root)

    if event == "start":
        result = event_logger.agent_start(
            stage=stage,
            agent_name=agent_name,
            model_tier=model_tier,
            iteration=ws_status.iteration,
            prompt_summary=prompt_summary,
        )
    else:
        files = [item.strip() for item in output_files.split(",") if item.strip()] if output_files else []
        result = event_logger.agent_end(
            stage=stage,
            agent_name=agent_name,
            status=status,
            duration_sec=duration_sec,
            output_files=files,
            output_summary=output_summary,
            iteration=ws_status.iteration,
        )

    print(json.dumps(result, ensure_ascii=False))
