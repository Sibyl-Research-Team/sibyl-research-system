"""CLI entry point for Sibyl pipeline (Claude Code native mode).

Provides auxiliary commands for status, evolution, and sync.
The primary workflow runs through Claude Code's /sibyl-start skill.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from sibyl._paths import REPO_ROOT
from sibyl.config import Config

console = Console()
_REEXEC_ENV_VAR = "SIBYL_REEXEC_WITH_REPO_VENV"


def ensure_repo_venv_python() -> None:
    """Re-exec the CLI under the repo-local virtualenv when needed."""
    repo_venv = REPO_ROOT / ".venv"
    target_python = repo_venv / "bin" / "python"

    if Path(sys.prefix).resolve() == repo_venv.resolve():
        return

    if os.environ.get(_REEXEC_ENV_VAR) == "1":
        raise SystemExit(
            "Sibyl re-exec into the repo virtualenv did not take effect. "
            f"Expected sys.prefix={repo_venv}, got {sys.prefix!r} "
            f"(current executable: {sys.executable})."
        )

    if not target_python.exists():
        raise SystemExit(
            "Sibyl must run from the repo virtualenv, but the interpreter was not found at "
            f"{target_python}. Create it with `python3 -m venv .venv && .venv/bin/pip install -e .`."
        )

    env = os.environ.copy()
    env[_REEXEC_ENV_VAR] = "1"
    os.execve(
        str(target_python),
        [str(target_python), "-m", "sibyl.cli", *sys.argv[1:]],
        env,
    )


def main():
    ensure_repo_venv_python()

    parser = argparse.ArgumentParser(
        description="Sibyl Research System - 西比拉自动化研究系统 (Claude Code Native)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Primary usage: Use /sibyl-start in Claude Code to run the pipeline.

Auxiliary commands:
  sibyl status              Show all projects
  sibyl status <project>    Show detailed project status
  sibyl evolve              Trigger evolution analysis
  sibyl evolve --apply      Apply evolution patches
  sibyl migrate --all       Align existing workspaces to layered runtime
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- status ---
    status_p = sub.add_parser("status", help="Project status dashboard")
    status_p.add_argument("project", nargs="?", help="Project name (shows all if omitted)")
    status_p.add_argument("--config", help="Path to config YAML")

    # --- evolve ---
    evolve_p = sub.add_parser("evolve", help="Trigger evolution analysis")
    evolve_p.add_argument("--apply", action="store_true", help="Generate lessons overlay files")
    evolve_p.add_argument("--reset", action="store_true", help="Remove all overlay files")
    evolve_p.add_argument("--show", action="store_true", help="Show current overlay contents")

    # --- migrate ---
    migrate_p = sub.add_parser("migrate", help="Migrate one or all workspaces to layered runtime")
    migrate_p.add_argument("workspace", nargs="?", default=None, help="Workspace path")
    migrate_p.add_argument("--all", action="store_true", help="Migrate all workspaces")
    migrate_p.add_argument("--workspaces-dir", default=None, help="Override workspaces directory")

    # --- internal control-plane helpers ---
    dispatch_p = sub.add_parser("dispatch", help="Internal dynamic-dispatch helper")
    dispatch_p.add_argument("workspace", help="Workspace path")

    exp_status_p = sub.add_parser("experiment-status", help="Internal experiment status helper")
    exp_status_p.add_argument("workspace", help="Workspace path")

    exp_supervisor_claim_p = sub.add_parser("experiment-supervisor-claim", help="Internal experiment supervisor lease helper")
    exp_supervisor_claim_p.add_argument("workspace", help="Workspace path")
    exp_supervisor_claim_p.add_argument("--owner", required=True, help="Background agent owner id")
    exp_supervisor_claim_p.add_argument("--stale-after", type=int, default=900, help="Heartbeat staleness threshold in seconds")

    exp_supervisor_hb_p = sub.add_parser("experiment-supervisor-heartbeat", help="Internal experiment supervisor heartbeat helper")
    exp_supervisor_hb_p.add_argument("workspace", help="Workspace path")
    exp_supervisor_hb_p.add_argument("--owner", required=True, help="Background agent owner id")
    exp_supervisor_hb_p.add_argument("--summary", default="", help="Latest summary")
    exp_supervisor_hb_p.add_argument("--actions-json", default="[]", help="JSON list of latest actions")
    exp_supervisor_hb_p.add_argument("--recommendations-json", default="[]", help="JSON list of recommendations")

    exp_supervisor_notify_p = sub.add_parser("experiment-supervisor-notify-main", help="Internal experiment supervisor wake helper")
    exp_supervisor_notify_p.add_argument("workspace", help="Workspace path")
    exp_supervisor_notify_p.add_argument("--owner", required=True, help="Background agent owner id")
    exp_supervisor_notify_p.add_argument("--kind", default="resolution", help="Wake event kind")
    exp_supervisor_notify_p.add_argument("--summary", default="", help="Wake summary")
    exp_supervisor_notify_p.add_argument("--details-json", default="{}", help="JSON object with structured details")
    exp_supervisor_notify_p.add_argument("--actions-json", default="[]", help="JSON list of actions already taken")
    exp_supervisor_notify_p.add_argument("--recommendations-json", default="[]", help="JSON list of recommended follow-ups")
    exp_supervisor_notify_p.add_argument("--urgency", default="high", help="Wake urgency level")
    exp_supervisor_notify_p.add_argument("--requires-main-system", action="store_true", help="Mark this wake as requiring immediate main-system collaboration")

    exp_supervisor_release_p = sub.add_parser("experiment-supervisor-release", help="Internal experiment supervisor release helper")
    exp_supervisor_release_p.add_argument("workspace", help="Workspace path")
    exp_supervisor_release_p.add_argument("--owner", required=True, help="Background agent owner id")
    exp_supervisor_release_p.add_argument("--status", default="idle", help="Final supervisor status")
    exp_supervisor_release_p.add_argument("--summary", default="", help="Final summary")

    exp_supervisor_drain_p = sub.add_parser("experiment-supervisor-drain-wake", help="Internal experiment supervisor wake drain helper")
    exp_supervisor_drain_p.add_argument("workspace", help="Workspace path")

    exp_supervisor_snapshot_p = sub.add_parser("experiment-supervisor-snapshot", help="Internal experiment supervisor snapshot helper")
    exp_supervisor_snapshot_p.add_argument("workspace", help="Workspace path")

    record_gpu_poll_p = sub.add_parser("record-gpu-poll", help="Internal GPU polling snapshot helper")
    record_gpu_poll_p.add_argument("workspace", help="Workspace path")
    record_gpu_poll_p.add_argument("--nvidia-smi-output", required=True, help="Raw nvidia-smi CSV output")
    record_gpu_poll_p.add_argument("--source", default="experiment_supervisor", help="Snapshot source label")

    requeue_exp_task_p = sub.add_parser("requeue-experiment-task", help="Internal experiment retry helper")
    requeue_exp_task_p.add_argument("workspace", help="Workspace path")
    requeue_exp_task_p.add_argument("task_id", help="Task id to requeue")
    requeue_exp_task_p.add_argument("--reason", default="", help="Reason for retry")

    sync_exp_p = sub.add_parser("sync-experiment-completions", help="Internal daemon helper: sync completed/failed tasks to experiment_state.json")
    sync_exp_p.add_argument("workspace", help="Workspace path")
    sync_exp_p.add_argument("--completed-json", default="[]", help="JSON array of completed task IDs")
    sync_exp_p.add_argument("--failed-json", default="[]", help="JSON array of failed task IDs")

    self_heal_p = sub.add_parser("self-heal-scan", help="Internal self-heal scan helper")
    self_heal_p.add_argument("workspace", nargs="?", default=None, help="Workspace path")

    self_heal_daemon_p = sub.add_parser("self-heal-daemon-start", help="Launch self-heal background monitor daemon")
    self_heal_daemon_p.add_argument("workspace", nargs="?", default=None, help="Workspace path")

    dashboard_p = sub.add_parser("dashboard", help="Web dashboard or JSON data dump")
    dashboard_p.add_argument("workspace", nargs="?", default=None,
                             help="Workspace path (omit to start web server)")
    dashboard_p.add_argument("--tail", type=int, default=50, help="Number of recent events")
    dashboard_p.add_argument("--port", type=int, default=7654, help="Web server port (default 7654)")
    dashboard_p.add_argument("--host", default="127.0.0.1", help="Web server host")
    dashboard_p.add_argument("--config", help="Path to config YAML")
    dashboard_p.add_argument("--production", action="store_true",
                             help="Use gunicorn production server")

    webui_p = sub.add_parser("webui", help="Web UI API + WebSocket server")
    webui_p.add_argument("--port", type=int, default=7654, help="Server port")
    webui_p.add_argument("--host", default="127.0.0.1", help="Server host")
    webui_p.add_argument("--config", help="Path to config YAML")

    latex_p = sub.add_parser("latex-compile", help="Compile paper.md to PDF via pandoc+latexmk")
    latex_p.add_argument("workspace", help="Workspace path")

    lark_sync_p = sub.add_parser("lark-sync", help="Sync workspace artifacts to Feishu/Lark")
    lark_sync_p.add_argument("workspace", help="Workspace path")

    log_agent_p = sub.add_parser("log-agent", help="Log agent invocation event")
    log_agent_p.add_argument("workspace", help="Workspace path")
    log_agent_p.add_argument("stage", help="Current pipeline stage")
    log_agent_p.add_argument("agent", help="Agent name (e.g. sibyl-innovator)")
    log_agent_p.add_argument("--event", default="start", choices=["start", "end"])
    log_agent_p.add_argument("--model-tier", default="")
    log_agent_p.add_argument("--status", default="ok")
    log_agent_p.add_argument("--duration", type=float, default=None)
    log_agent_p.add_argument("--output-files", default="")
    log_agent_p.add_argument("--output-summary", default="")
    log_agent_p.add_argument("--prompt-summary", default="")

    args = parser.parse_args()

    if args.command == "dispatch":
        from sibyl.orchestrate import cli_dispatch_tasks
        cli_dispatch_tasks(args.workspace)
        return

    if args.command == "experiment-status":
        from sibyl.orchestrate import cli_experiment_status
        cli_experiment_status(args.workspace)
        return

    if args.command == "experiment-supervisor-claim":
        from sibyl.orchestrate import cli_experiment_supervisor_claim
        cli_experiment_supervisor_claim(args.workspace, args.owner, stale_after_sec=args.stale_after)
        return

    if args.command == "experiment-supervisor-heartbeat":
        from sibyl.orchestrate import cli_experiment_supervisor_heartbeat
        cli_experiment_supervisor_heartbeat(
            args.workspace,
            args.owner,
            summary=args.summary,
            actions_json=args.actions_json,
            recommendations_json=args.recommendations_json,
        )
        return

    if args.command == "experiment-supervisor-notify-main":
        from sibyl.orchestrate import cli_experiment_supervisor_notify_main
        cli_experiment_supervisor_notify_main(
            args.workspace,
            args.owner,
            kind=args.kind,
            summary=args.summary,
            details_json=args.details_json,
            actions_json=args.actions_json,
            recommendations_json=args.recommendations_json,
            urgency=args.urgency,
            requires_main_system=args.requires_main_system,
        )
        return

    if args.command == "experiment-supervisor-release":
        from sibyl.orchestrate import cli_experiment_supervisor_release
        cli_experiment_supervisor_release(
            args.workspace,
            args.owner,
            final_status=args.status,
            summary=args.summary,
        )
        return

    if args.command == "experiment-supervisor-drain-wake":
        from sibyl.orchestrate import cli_experiment_supervisor_drain_wake
        cli_experiment_supervisor_drain_wake(args.workspace)
        return

    if args.command == "experiment-supervisor-snapshot":
        from sibyl.orchestrate import cli_experiment_supervisor_snapshot
        cli_experiment_supervisor_snapshot(args.workspace)
        return

    if args.command == "record-gpu-poll":
        from sibyl.orchestrate import cli_record_gpu_poll
        cli_record_gpu_poll(
            args.workspace,
            args.nvidia_smi_output,
            source=args.source,
        )
        return

    if args.command == "requeue-experiment-task":
        from sibyl.orchestrate import cli_requeue_experiment_task
        cli_requeue_experiment_task(args.workspace, args.task_id, reason=args.reason)
        return

    if args.command == "sync-experiment-completions":
        from sibyl.orchestrate import cli_sync_experiment_completions
        cli_sync_experiment_completions(
            args.workspace,
            completed_json=args.completed_json,
            failed_json=args.failed_json,
        )
        return

    if args.command == "self-heal-scan":
        from sibyl.orchestrate import cli_self_heal_scan
        cli_self_heal_scan(args.workspace)
        return

    if args.command == "self-heal-daemon-start":
        from sibyl.orchestrate import cli_self_heal_daemon_start
        cli_self_heal_daemon_start(args.workspace)
        return

    if args.command == "dashboard":
        if args.workspace:
            # JSON dump mode (legacy CLI behavior)
            from sibyl.orchestrate import cli_dashboard_data
            cli_dashboard_data(args.workspace, events_tail=args.tail)
        else:
            # Web server mode
            from sibyl.dashboard.server import run
            from sibyl.orchestration.config_helpers import load_effective_config

            cfg = load_effective_config(config_path=getattr(args, "config", None))
            run(port=args.port, host=args.host, config=cfg,
                production=getattr(args, "production", False))
        return

    if args.command == "webui":
        from sibyl.orchestration.config_helpers import load_effective_config
        from sibyl.webui.app import create_webui_app

        cfg = load_effective_config(config_path=getattr(args, "config", None))
        app = create_webui_app(cfg)
        ws_dir = cfg.workspaces_dir.resolve()
        print(f"\n  Sibyl WebUI API running at http://{args.host}:{args.port}")
        print(f"  Serving workspaces from: {ws_dir}")
        print("  Press Ctrl+C to stop.\n")
        app.run(host=args.host, port=args.port, debug=False)
        return

    if args.command == "log-agent":
        from sibyl.orchestrate import cli_log_agent
        cli_log_agent(
            workspace_path=args.workspace,
            stage=args.stage,
            agent_name=args.agent,
            event=args.event,
            model_tier=args.model_tier,
            status=args.status,
            duration_sec=args.duration,
            output_files=args.output_files,
            output_summary=args.output_summary,
            prompt_summary=args.prompt_summary,
        )
        return

    if args.command == "latex-compile":
        from sibyl.latex_pipeline import compile_full_pipeline
        result = compile_full_pipeline(Path(args.workspace))
        print(json.dumps(result, indent=2))
        return

    if args.command == "lark-sync":
        from sibyl.lark_sync import run_sync
        result = run_sync(args.workspace)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "migrate":
        from sibyl.orchestrate import cli_migrate, cli_migrate_all

        if args.all:
            cli_migrate_all(args.workspaces_dir)
        elif args.workspace:
            cli_migrate(args.workspace)
        else:
            raise SystemExit("Provide a workspace path or pass --all.")
        return

    from sibyl.orchestration.config_helpers import load_effective_config

    config = load_effective_config(config_path=getattr(args, "config", None))

    if args.command == "status":
        _status_dashboard(config, getattr(args, "project", None))

    elif args.command == "evolve":
        _evolve(apply=args.apply, reset=args.reset, show=args.show)


def _status_dashboard(config: Config, project: str | None = None):
    """Enhanced project status dashboard."""
    from rich.table import Table
    from rich.panel import Panel
    from sibyl.workspace import Workspace

    ws_dir = config.workspaces_dir
    if not ws_dir.exists():
        console.print("No workspaces yet.")
        return

    projects = []
    for d in sorted(ws_dir.iterdir()):
        if not d.is_dir():
            continue
        if project and d.name != project:
            continue
        try:
            ws = Workspace.open_existing(config.workspaces_dir, d.name)
            meta = ws.get_project_metadata()
            meta["topic"] = ws.read_file("topic.txt") or ""
            projects.append(meta)
        except Exception:
            continue

    if not projects:
        console.print(f"[yellow]No project found{f': {project}' if project else ''}[/yellow]")
        return

    if project and len(projects) == 1:
        m = projects[0]
        panel_content = (
            f"[bold]Topic:[/bold] {m.get('topic', '?')}\n"
            f"[bold]Stage:[/bold] {m.get('stage', '?')}\n"
            f"[bold]Iteration:[/bold] {m.get('iteration', 0)}\n"
            f"[bold]Files:[/bold] {m.get('total_files', 0)}\n"
            f"[bold]Pilot results:[/bold] {m.get('pilot_results', 0)}\n"
            f"[bold]Full results:[/bold] {m.get('full_results', 0)}\n"
            f"[bold]Paper:[/bold] {'Yes' if m.get('has_paper') else 'No'}\n"
            f"[bold]Errors:[/bold] {m.get('errors', 0)}"
        )
        console.print(Panel(panel_content, title=f"Sibyl Project: {m['name']}", border_style="cyan"))
    else:
        table = Table(title="Sibyl Projects Dashboard")
        table.add_column("Project", style="cyan")
        table.add_column("Topic", max_width=40)
        table.add_column("Stage", style="green")
        table.add_column("Iter", justify="right")
        table.add_column("Paper?")
        table.add_column("Files", justify="right")
        table.add_column("Errors", style="red", justify="right")

        for m in projects:
            table.add_row(
                m["name"],
                (m.get("topic", "")[:37] + "...") if len(m.get("topic", "")) > 40 else m.get("topic", ""),
                m.get("stage", "?"),
                str(m.get("iteration", 0)),
                "Y" if m.get("has_paper") else "N",
                str(m.get("total_files", 0)),
                str(m.get("errors", 0)),
            )
        console.print(table)


def _evolve(apply: bool = False, reset: bool = False, show: bool = False):
    """Trigger evolution analysis and manage overlays."""
    from sibyl.evolution import EvolutionEngine

    engine = EvolutionEngine()

    if reset:
        engine.reset_overlays()
        console.print("[green]All overlay files removed. Prompts reverted to base.[/green]")
        return

    if show:
        overlays = engine.get_overlay_content()
        if not overlays:
            console.print("[yellow]No overlay files found.[/yellow]")
            return
        for agent_name, content in overlays.items():
            console.print(f"\n[bold cyan]── {agent_name} ──[/bold cyan]")
            console.print(content)

        global_path = engine.EVOLUTION_DIR / "global_lessons.md"
        if global_path.exists():
            console.print("\n[bold cyan]── Global Lessons ──[/bold cyan]")
            console.print(global_path.read_text(encoding="utf-8"))
        return

    insights = engine.analyze_patterns()

    if not insights:
        console.print("[yellow]No patterns found yet. Run more experiments first.[/yellow]")
        return

    console.print(f"[bold]Found {len(insights)} pattern(s):[/bold]\n")
    for i in insights:
        color = "red" if i.severity == "high" else "yellow"
        cat = f"[dim]{i.category.upper()}[/dim] " if i.category else ""
        console.print(f"  [{color}]{i.severity.upper()}[/{color}] {cat}{i.pattern}")
        console.print(f"    Frequency: {i.frequency}x | Agents: {', '.join(i.affected_agents)}")
        console.print(f"    Suggestion: {i.suggestion}\n")

    if apply:
        written = engine.generate_lessons_overlay()
        console.print(f"\n[bold green]Generated {len(written)} overlay file(s):[/bold green]")
        for agent_name in written:
            console.print(f"  {engine.EVOLUTION_DIR / 'lessons' / f'{agent_name}.md'}")
    else:
        console.print("[dim]Use --apply to generate overlay files, --show to view, --reset to clear.[/dim]")


if __name__ == "__main__":
    main()
