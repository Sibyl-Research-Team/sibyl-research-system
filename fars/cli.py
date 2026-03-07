"""CLI entry point for FARS pipeline (Claude Code native mode).

Provides auxiliary commands for status, evolution, and sync.
The primary workflow runs through Claude Code's /fars-start skill.
"""
import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from fars.config import Config

console = Console()


def main():
    parser = argparse.ArgumentParser(
        description="FARS - Fully Automated Research System (Claude Code Native)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Primary usage: Use /fars-start in Claude Code to run the pipeline.

Auxiliary commands:
  fars status              Show all projects
  fars status <project>    Show detailed project status
  fars evolve              Trigger evolution analysis
  fars evolve --apply      Apply evolution patches
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- status ---
    status_p = sub.add_parser("status", help="Project status dashboard")
    status_p.add_argument("project", nargs="?", help="Project name (shows all if omitted)")
    status_p.add_argument("--config", help="Path to config YAML")

    # --- evolve ---
    evolve_p = sub.add_parser("evolve", help="Trigger evolution analysis")
    evolve_p.add_argument("--apply", action="store_true", help="Apply patches (default: dry run)")

    args = parser.parse_args()
    config = Config()
    if hasattr(args, "config") and args.config:
        config = Config.from_yaml(args.config)

    if args.command == "status":
        _status_dashboard(config, getattr(args, "project", None))

    elif args.command == "evolve":
        _evolve(apply=args.apply)


def _status_dashboard(config: Config, project: str | None = None):
    """Enhanced project status dashboard."""
    from rich.table import Table
    from rich.panel import Panel
    from fars.workspace import Workspace

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
            ws = Workspace(config.workspaces_dir, d.name)
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
        console.print(Panel(panel_content, title=f"FARS Project: {m['name']}", border_style="cyan"))
    else:
        table = Table(title="FARS Projects Dashboard")
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


def _evolve(apply: bool = False):
    """Trigger evolution analysis."""
    from fars.evolution import EvolutionEngine

    engine = EvolutionEngine()
    insights = engine.analyze_patterns()

    if not insights:
        console.print("[yellow]No patterns found yet. Run more experiments first.[/yellow]")
        return

    console.print(f"[bold]Found {len(insights)} pattern(s):[/bold]\n")
    for i in insights:
        color = "red" if i.severity == "high" else "yellow"
        console.print(f"  [{color}]{i.severity.upper()}[/{color}] {i.pattern}")
        console.print(f"    Frequency: {i.frequency}x | Stages: {', '.join(i.affected_stages)}")
        console.print(f"    Suggestion: {i.suggestion}\n")

    patches = engine.generate_prompt_patches()
    if patches:
        console.print(f"[bold]Generated {len(patches)} prompt patch(es):[/bold]")
        results = engine.apply_evolution(patches, dry_run=not apply)
        for key, val in results.items():
            console.print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
