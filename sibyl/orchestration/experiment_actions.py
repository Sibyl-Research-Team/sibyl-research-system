"""Experiment action builders extracted from the legacy orchestrator."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .common_utils import build_repo_python_cli_command, pack_skill_args
from .workspace_paths import project_marker_file


def _remote_project_dir(orchestrator: Any) -> str:
    return f"{orchestrator.config.remote_base}/projects/{orchestrator.ws.name}"


def _default_wake_check_interval_sec(poll_interval_sec: int) -> int:
    """Return the default main-loop wake inbox cadence during experiment waits."""
    return min(90, poll_interval_sec)


def _sync_completed_tasks(exp_state: Any, task_ids: list[str], completed_set: set[str]) -> bool:
    changed = False
    for task_id in task_ids:
        task = exp_state.tasks.get(task_id)
        if task is None or task_id not in completed_set:
            continue
        task["status"] = "completed"
        task["completed_at"] = dt.datetime.now().isoformat()
        changed = True
    return changed


def build_experiment_skill_dict(
    orchestrator: Any,
    mode: str,
    ws: str,
    gpu_ids: list[int],
    task_ids: str = "",
) -> dict:
    """Build a single experimenter skill dict."""
    gpu_ids_str = ",".join(str(gpu_id) for gpu_id in gpu_ids)
    env_cmd = orchestrator.config.get_remote_env_cmd(orchestrator.ws.name)

    if orchestrator.config.experiment_mode in ("server_codex", "server_claude"):
        arg_parts = [
            ws,
            mode,
            orchestrator.config.ssh_server,
            orchestrator.config.remote_base,
            env_cmd,
            gpu_ids_str,
            orchestrator.config.experiment_mode,
            orchestrator.config.server_codex_path,
            orchestrator.config.server_claude_path,
        ]
        if task_ids:
            arg_parts.append(f"--tasks={task_ids}")
        return {
            "name": "sibyl-server-experimenter",
            "args": pack_skill_args(*arg_parts),
        }

    arg_parts = [
        ws,
        mode,
        orchestrator.config.ssh_server,
        orchestrator.config.remote_base,
        env_cmd,
        gpu_ids_str,
    ]
    if task_ids:
        arg_parts.append(f"--tasks={task_ids}")
    return {
        "name": "sibyl-experimenter",
        "args": pack_skill_args(*arg_parts),
    }


def _build_experiment_supervisor_skill(
    orchestrator: Any,
    mode: str,
    ws: str,
    *,
    task_ids: list[str],
    poll_interval_sec: int,
) -> dict:
    """Build the always-on background experiment supervisor skill."""
    env_cmd = orchestrator.config.get_remote_env_cmd(orchestrator.ws.name)
    task_ids_csv = ",".join(task_ids)
    return {
        "name": "sibyl-experiment-supervisor",
        "args": pack_skill_args(
            ws,
            mode,
            orchestrator.config.ssh_server,
            orchestrator.config.remote_base,
            env_cmd,
            task_ids_csv,
            poll_interval_sec,
            orchestrator.config.gpu_poll_interval_sec,
            orchestrator.config.gpu_free_threshold_mb,
            orchestrator.config.max_gpus,
            str(orchestrator.config.gpu_aggressive_mode).lower(),
            orchestrator.config.gpu_aggressive_threshold_pct,
        ),
    }


def build_experiment_skill_action(
    orchestrator: Any,
    mode: str,
    ws: str,
    gpu_ids: list[int],
    stage: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Single-agent experiment action (fallback when no task_plan)."""
    skill = build_experiment_skill_dict(
        orchestrator,
        mode,
        ws,
        gpu_ids,
    )
    is_server = orchestrator.config.experiment_mode in ("server_codex", "server_claude")
    poll_sec = 120 if mode == "PILOT" else 300
    return action_cls(
        action_type="skill",
        skills=[skill],
        description=(
            f"Run {mode.lower()} experiments"
            + (
                f" on server ({orchestrator.config.experiment_mode})"
                if is_server else ""
            )
        ),
        stage=stage,
        experiment_monitor={
            "poll_interval_sec": poll_sec,
            "wake_check_interval_sec": _default_wake_check_interval_sec(poll_sec),
            "wake_cmd": build_repo_python_cli_command(
                "experiment-supervisor-drain-wake",
                orchestrator.workspace_path,
            ),
            "background_agent": _build_experiment_supervisor_skill(
                orchestrator,
                mode,
                ws,
                task_ids=[],
                poll_interval_sec=poll_sec,
            ),
        },
    )


def build_experiment_batch_action(
    orchestrator: Any,
    ws: str,
    mode: str,
    stage: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build experiment action with GPU-aware batch scheduling."""
    from sibyl.gpu_scheduler import (
        _load_progress,
        claim_next_batch,
        get_running_gpu_ids,
        read_poll_result,
        validate_task_plan,
    )
    from sibyl.experiment_recovery import (
        get_running_tasks,
        load_experiment_state,
        migrate_from_gpu_progress,
        register_dispatched_tasks,
        save_experiment_state,
    )

    exp_state = load_experiment_state(orchestrator.ws.active_root)
    running_tasks = get_running_tasks(exp_state)
    running_gpus = get_running_gpu_ids(orchestrator.ws.active_root)

    if running_tasks or running_gpus:
        completed_set, _, _, _ = _load_progress(orchestrator.ws.active_root)
        if _sync_completed_tasks(exp_state, running_tasks, completed_set):
            save_experiment_state(orchestrator.ws.active_root, exp_state)
            running_tasks = get_running_tasks(exp_state)
            running_gpus = get_running_gpu_ids(orchestrator.ws.active_root)

    if orchestrator.config.gpu_poll_enabled:
        polled_free_gpus = read_poll_result(project_marker_file(orchestrator.ws.root, "gpu_free"))
        if polled_free_gpus:
            effective_gpu_ids = polled_free_gpus[:orchestrator.config.max_gpus]
        else:
            if running_tasks or running_gpus:
                return build_experiment_wait_action(
                    orchestrator,
                    stage,
                    running_tasks,
                    running_gpus,
                    action_cls=action_cls,
                )
            return build_gpu_poll_action(
                orchestrator,
                stage,
                action_cls=action_cls,
            )
    else:
        effective_gpu_ids = list(range(orchestrator.config.max_gpus))

    exp_state = load_experiment_state(orchestrator.ws.active_root)
    if not exp_state.tasks:
        _, recovered_running_ids, _, _ = _load_progress(orchestrator.ws.active_root)
        if recovered_running_ids:
            exp_state = migrate_from_gpu_progress(orchestrator.ws.active_root)
            save_experiment_state(orchestrator.ws.active_root, exp_state)

    running_tasks = get_running_tasks(exp_state)
    if running_tasks:
        completed_set, _, _, _ = _load_progress(orchestrator.ws.active_root)
        if _sync_completed_tasks(exp_state, running_tasks, completed_set):
            save_experiment_state(orchestrator.ws.active_root, exp_state)

    task_plan_path = orchestrator.ws.active_path("plan/task_plan.json")
    if task_plan_path.exists():
        try:
            plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
            tasks = plan.get("tasks", [])
            if tasks:
                incomplete = validate_task_plan(tasks)
                if incomplete:
                    ids_str = ", ".join(incomplete[:5])
                    remaining = len(incomplete) - 5
                    suffix = f" 等 {len(incomplete)} 个任务" if remaining > 0 else ""
                    return action_cls(
                        action_type="skill",
                        skills=[{
                            "name": "sibyl-planner",
                            "args": pack_skill_args(ws, "fix-gpu"),
                        }],
                        description=(
                            f"task_plan.json 中 {ids_str}{suffix} 缺少 gpu_count/estimated_minutes，"
                            f"需要 planner 补全后才能调度实验"
                        ),
                        stage=stage,
                    )
        except (json.JSONDecodeError, OSError):
            pass

    occupied = set(get_running_gpu_ids(orchestrator.ws.active_root))
    candidate_gpu_ids = [gpu_id for gpu_id in effective_gpu_ids if gpu_id not in occupied]
    if not candidate_gpu_ids:
        return build_experiment_wait_action(
            orchestrator,
            stage,
            running_tasks,
            running_gpus,
            action_cls=action_cls,
        )

    info = claim_next_batch(
        orchestrator.ws.active_root,
        candidate_gpu_ids,
        mode,
        gpus_per_task=orchestrator.config.gpus_per_task,
        max_parallel_tasks=orchestrator.config.max_parallel_tasks,
    )
    if info is None:
        return build_experiment_skill_action(
            orchestrator,
            mode,
            ws,
            candidate_gpu_ids,
            stage,
            action_cls=action_cls,
        )

    batch = info["batch"]
    if len(batch) == 0:
        if running_tasks or running_gpus:
            return build_experiment_wait_action(
                orchestrator,
                stage,
                running_tasks,
                running_gpus,
                action_cls=action_cls,
            )
        return action_cls(
            action_type="bash",
            bash_command='echo "All experiment tasks blocked by dependencies"',
            description="实验任务被依赖阻塞",
            stage=stage,
        )

    est_min = info["estimated_minutes"]
    remaining = info["remaining_count"]
    total = info["total_count"]

    skills = []
    for assignment in batch:
        task_ids = ",".join(assignment["task_ids"])
        gpu_ids = assignment["gpu_ids"]
        skills.append(
            build_experiment_skill_dict(
                orchestrator,
                mode,
                ws,
                gpu_ids,
                task_ids,
            )
        )

    progress_str = f"[{total - remaining}/{total}]"
    gpu_summary = ", ".join(
        f"{assignment['task_ids'][0]}→GPU{assignment['gpu_ids']}"
        for assignment in batch
    )
    calibrated = info.get("calibrated", False)
    ratio = info.get("calibration_ratio", 1.0)
    cal_hint = f" (校准×{ratio})" if calibrated else ""
    desc = (
        f"{progress_str} 并行 {len(skills)} 任务 ({mode}), "
        f"预计 {est_min}min{cal_hint}: {gpu_summary}"
    )

    task_gpu_map: dict[str, list[int]] = {}
    all_task_ids: list[str] = []
    for assignment in batch:
        for task_id in assignment["task_ids"]:
            task_gpu_map[task_id] = assignment["gpu_ids"]
            all_task_ids.append(task_id)
    register_dispatched_tasks(
        orchestrator.ws.active_root,
        task_gpu_map,
        _remote_project_dir(orchestrator),
    )

    monitor = build_experiment_monitor(
        orchestrator,
        mode,
        all_task_ids,
        est_min,
    )

    action_type = "skills_parallel" if len(skills) > 1 else "skill"
    return action_cls(
        action_type=action_type,
        skills=skills,
        description=desc,
        stage=stage,
        estimated_minutes=est_min,
        experiment_monitor=monitor,
    )


def build_experiment_monitor(
    orchestrator: Any,
    mode: str,
    task_ids: list[str],
    estimated_minutes: int,
) -> dict:
    """Build experiment monitor config for background progress tracking."""
    from sibyl.gpu_scheduler import experiment_monitor_script

    remote_dir = _remote_project_dir(orchestrator)
    timeout_min = max(30, estimated_minutes * 2) if estimated_minutes > 0 else 0
    timeout_min = max(timeout_min, max(1, orchestrator.config.experiment_timeout // 60))
    poll_sec = 120 if estimated_minutes <= 15 else 300
    marker = project_marker_file(orchestrator.ws.root, "exp_monitor")
    background_agent = _build_experiment_supervisor_skill(
        orchestrator,
        mode,
        str(orchestrator.ws.active_root),
        task_ids=task_ids,
        poll_interval_sec=poll_sec,
    )

    script = experiment_monitor_script(
        ssh_server=orchestrator.config.ssh_server,
        remote_project_dir=remote_dir,
        task_ids=task_ids,
        poll_interval_sec=poll_sec,
        timeout_minutes=timeout_min,
        marker_file=marker,
    )

    done_checks = " && ".join(
        f'test -f {remote_dir}/exp/results/{task_id}_DONE && echo "{task_id}:DONE" || echo "{task_id}:PENDING"'
        for task_id in task_ids
    )

    return {
        "script": script,
        "marker_file": marker,
        "task_ids": task_ids,
        "timeout_minutes": timeout_min,
        "poll_interval_sec": poll_sec,
        "wake_check_interval_sec": _default_wake_check_interval_sec(poll_sec),
        "ssh_connection": orchestrator.config.ssh_server,
        "check_cmd": done_checks,
        "remote_dir": remote_dir,
        "dynamic_dispatch": True,
        "wake_cmd": build_repo_python_cli_command(
            "experiment-supervisor-drain-wake",
            orchestrator.workspace_path,
        ),
        "dispatch_cmd": build_repo_python_cli_command(
            "dispatch",
            orchestrator.workspace_path,
        ),
        "background_agent": background_agent,
    }


def build_gpu_poll_action(
    orchestrator: Any,
    stage: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Return a gpu_poll action for the main session to execute."""
    from sibyl.gpu_scheduler import gpu_poll_wait_script, nvidia_smi_query_cmd

    aggressive = orchestrator.config.gpu_aggressive_mode
    interval_min = orchestrator.config.gpu_poll_interval_sec // 60
    marker_file = project_marker_file(orchestrator.ws.root, "gpu_free")
    mode_desc = (
        f"（流氓模式：<{orchestrator.config.gpu_aggressive_threshold_pct}% 显存占用也抢）"
        if aggressive
        else ""
    )
    return action_cls(
        action_type="gpu_poll",
        gpu_poll={
            "ssh_connection": orchestrator.config.ssh_server,
            "query_cmd": nvidia_smi_query_cmd(include_total=aggressive),
            "script": gpu_poll_wait_script(
                ssh_server=orchestrator.config.ssh_server,
                candidate_gpu_ids=list(range(orchestrator.config.max_gpus)),
                threshold_mb=orchestrator.config.gpu_free_threshold_mb,
                poll_interval_sec=orchestrator.config.gpu_poll_interval_sec,
                max_polls=orchestrator.config.gpu_poll_max_attempts,
                marker_file=marker_file,
                aggressive_mode=aggressive,
                aggressive_threshold_pct=orchestrator.config.gpu_aggressive_threshold_pct,
            ),
            "max_gpus": orchestrator.config.max_gpus,
            "threshold_mb": orchestrator.config.gpu_free_threshold_mb,
            "interval_sec": orchestrator.config.gpu_poll_interval_sec,
            "marker_file": marker_file,
            "aggressive_mode": aggressive,
            "aggressive_threshold_pct": orchestrator.config.gpu_aggressive_threshold_pct,
            "max_attempts": orchestrator.config.gpu_poll_max_attempts,
        },
        description=(
            f"轮询等待空闲 GPU（最多 {orchestrator.config.max_gpus} 张，"
            f"每 {interval_min}min 通过 SSH MCP 检查，"
            f"{'无限等待' if orchestrator.config.gpu_poll_max_attempts == 0 else f'最多 {orchestrator.config.gpu_poll_max_attempts} 次'}）"
            f"{mode_desc}"
        ),
        stage=stage,
    )


def build_experiment_wait_action(
    orchestrator: Any,
    stage: str,
    running_tasks: list[str],
    running_gpus: list[int],
    *,
    action_cls: type[Any],
) -> Any:
    """Return an experiment_wait action when experiments are running."""
    _ = running_gpus
    from sibyl.gpu_scheduler import _load_progress
    from sibyl.experiment_recovery import load_experiment_state

    exp_state = load_experiment_state(orchestrator.ws.active_root)
    _, _, running_map, _ = _load_progress(orchestrator.ws.active_root)

    all_running = running_tasks if running_tasks else list(running_map.keys())
    if not all_running:
        return action_cls(
            action_type="bash",
            bash_command='echo "experiment_wait: no running tasks detected, ready to advance"',
            description="实验已完成，可以推进",
            stage=stage,
        )

    task_plan_path = orchestrator.ws.active_path("plan/task_plan.json")
    task_estimates: dict[str, int] = {}
    if task_plan_path.exists():
        try:
            plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
            for task in plan.get("tasks", []):
                task_estimates[task["id"]] = task.get("estimated_minutes", 0)
        except (json.JSONDecodeError, OSError):
            pass

    max_remaining_min = 0
    task_status_lines = []
    for task_id in all_running:
        estimate = task_estimates.get(task_id, 0)
        started = ""
        gpu_ids: list[int] = []
        if task_id in running_map:
            started = running_map[task_id].get("started_at", "")
            gpu_ids = running_map[task_id].get("gpu_ids", [])
        elif task_id in exp_state.tasks:
            started = exp_state.tasks[task_id].get("started_at", "")
            gpu_ids = exp_state.tasks[task_id].get("gpu_ids", [])

        elapsed_min = 0
        if started:
            try:
                start_dt = dt.datetime.fromisoformat(started)
                elapsed_min = int((dt.datetime.now() - start_dt).total_seconds() / 60)
            except (ValueError, TypeError):
                pass

        remaining = max(0, estimate - elapsed_min) if estimate > 0 else 60
        max_remaining_min = max(max_remaining_min, remaining)
        gpu_str = ",".join(str(gpu_id) for gpu_id in gpu_ids) if gpu_ids else "?"
        task_status_lines.append(
            f"{task_id} -> GPU[{gpu_str}] (elapsed {elapsed_min}min"
            + (f", ~{remaining}min left" if estimate > 0 else "")
            + ")"
        )

    if max_remaining_min <= 30:
        poll_interval_sec = 120
    elif max_remaining_min <= 120:
        poll_interval_sec = 300
    else:
        poll_interval_sec = 600

    remote_dir = _remote_project_dir(orchestrator)
    done_checks = " && ".join(
        f'test -f {remote_dir}/exp/results/{task_id}_DONE && echo "{task_id}:DONE" || echo "{task_id}:PENDING"'
        for task_id in all_running
    )
    pid_checks = " && ".join(
        f'pid=$(cat {remote_dir}/exp/results/{task_id}.pid 2>/dev/null) && '
        f'(ps -p $pid > /dev/null 2>&1 && echo "{task_id}:ALIVE:$pid" || echo "{task_id}:DEAD:$pid") || '
        f'echo "{task_id}:NO_PID"'
        for task_id in all_running
    )
    progress_checks = " && ".join(
        f'cat {remote_dir}/exp/results/{task_id}_PROGRESS.json 2>/dev/null || echo "null"'
        for task_id in all_running
    )

    task_detail = "; ".join(task_status_lines[:5])
    desc = (
        f"实验运行中（{len(all_running)} 个任务），"
        f"预计剩余 ~{max_remaining_min}min，"
        f"每 {poll_interval_sec // 60}min 轮询一次\n"
        f"  {task_detail}"
    )

    return action_cls(
        action_type="experiment_wait",
        description=desc,
        stage=stage,
        estimated_minutes=max_remaining_min,
        experiment_monitor={
            "ssh_connection": orchestrator.config.ssh_server,
            "check_cmd": done_checks,
            "pid_check_cmd": pid_checks,
            "progress_check_cmd": progress_checks,
            "remote_dir": remote_dir,
            "task_ids": all_running,
            "poll_interval_sec": poll_interval_sec,
            "wake_check_interval_sec": _default_wake_check_interval_sec(poll_interval_sec),
            "max_remaining_min": max_remaining_min,
            "task_status": task_status_lines,
            "dynamic_dispatch": True,
            "wake_cmd": build_repo_python_cli_command(
                "experiment-supervisor-drain-wake",
                orchestrator.workspace_path,
            ),
            "dispatch_cmd": build_repo_python_cli_command(
                "dispatch",
                orchestrator.workspace_path,
            ),
            "status_cmd": build_repo_python_cli_command(
                "experiment_status",
                orchestrator.workspace_path,
            ),
            "background_agent": _build_experiment_supervisor_skill(
                orchestrator,
                "PILOT" if stage == "pilot_experiments" else "FULL",
                str(orchestrator.ws.active_root),
                task_ids=all_running,
                poll_interval_sec=poll_interval_sec,
            ),
        },
    )
