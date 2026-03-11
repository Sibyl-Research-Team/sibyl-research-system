"""Prompt-loading helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sibyl.orchestra_skills import get_registry as _get_skill_registry
from sibyl.runtime_assets import (
    detect_workspace_root,
    load_project_memory,
    load_project_prompt_overlay,
)
from sibyl.workspace import Workspace

from .workspace_paths import (
    resolve_active_workspace_path,
    resolve_workspace_root,
    workspace_scope_id,
)


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_ROLE_PROMPTS_WITH_PAPER_OUTPUT = {
    "codex_reviewer",
    "codex_writer",
    "editor",
    "final_critic",
    "latex_writer",
    "outline_writer",
    "section_critic",
    "section_writer",
    "sequential_writer",
}
_ROLE_PROMPTS_WITH_EXPERIMENT_PROTOCOL = {
    "experimenter",
    "planner",
    "server_experimenter",
}
_ROLE_PROMPTS_WITH_STRUCTURED_REVIEW = {
    "critic",
    "reflection",
    "supervisor",
}


@dataclass(frozen=True)
class PromptSection:
    """Named prompt fragment used by compiled prompt renderers."""

    title: str
    content: str


def _normalize_prompt_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _render_prompt_sections(
    sections: Iterable[PromptSection],
    *,
    heading: str,
) -> str:
    rendered: list[str] = [heading]
    seen: set[str] = set()
    for section in sections:
        content = _normalize_prompt_text(section.content)
        if not content:
            continue
        dedupe_key = f"{section.title}\n{content}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rendered.append(f"## {section.title}\n{content}")
    return "\n\n".join(rendered).strip() + "\n"


def _control_plane_language(lang: str) -> str:
    return "Chinese" if lang == "zh" else "English"


def _build_shared_runtime_sections(
    *,
    workspace_path: str | Path | None,
    agent_name: str | None = None,
) -> list[PromptSection]:
    lang = os.environ.get("SIBYL_LANGUAGE", "zh")
    language_contract = textwrap.dedent(
        f"""
        Control-plane messages, logs, and non-paper artifacts must use {_control_plane_language(lang)}.
        Paper outlines, section drafts, integrated manuscripts, writing critiques, LaTeX, figure captions,
        code comments, JSON keys, and bibliography entries must remain in English.
        """
    ).strip()
    workspace_contract = textwrap.dedent(
        """
        Treat every path as relative to the active workspace root unless an absolute path is explicitly provided.
        Prefer machine-readable JSON artifacts whenever a contract exists, and keep markdown companions concise.
        Save representative samples or evidence snippets instead of reporting aggregate metrics alone.
        """
    ).strip()
    quality_contract = textwrap.dedent(
        """
        Back every claim with evidence from the workspace or the latest experiment outputs.
        Flag suspicious improvements (>30% on a simple baseline) as potentially degenerate until validated.
        Report negative results and unresolved risks explicitly; do not smooth them over.
        """
    ).strip()
    sections = [
        PromptSection("Locale Contract", language_contract),
        PromptSection("Workspace Contract", workspace_contract),
        PromptSection("Evidence Contract", quality_contract),
    ]

    if agent_name in _ROLE_PROMPTS_WITH_EXPERIMENT_PROTOCOL:
        sections.append(
            PromptSection(
                "Experiment Protocol",
                textwrap.dedent(
                    """
                    Pilot tasks should stay small, fast, and falsifiable. Prefer public benchmarks, include at least
                    one baseline, and keep outputs resumable and machine-readable. Record runtime assumptions when GPU,
                    timeout, or batch-size choices materially affect the result.
                    """
                ).strip(),
            )
        )
    if agent_name in _ROLE_PROMPTS_WITH_PAPER_OUTPUT:
        sections.append(
            PromptSection(
                "Paper Output Contract",
                textwrap.dedent(
                    """
                    All paper-facing drafts must stay in English and keep terminology consistent with earlier sections.
                    Mention figures or tables before they appear, and preserve any explicit artifact markers required by
                    the downstream writing pipeline.
                    """
                ).strip(),
            )
        )
    if agent_name in _ROLE_PROMPTS_WITH_STRUCTURED_REVIEW:
        sections.append(
            PromptSection(
                "Structured Artifact Contract",
                textwrap.dedent(
                    """
                    When a canonical JSON artifact is requested, write it first and make the markdown file a concise
                    human-readable companion. Downstream automation consumes the JSON, not prose scraped with regex.
                    """
                ).strip(),
            )
        )
    project_memory = load_project_memory(workspace_path)
    if project_memory:
        sections.append(PromptSection("Project Constraints", project_memory))
    return sections


def _load_prompt_body(agent_name: str) -> str:
    path = PROMPTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _build_orchestra_skills_section(
    *,
    agent_name: str | None = None,
    workspace_path: str | Path | None = None,
) -> str:
    """Build the orchestra external skills index for prompt injection.

    Reads config from the workspace (if available) to check whether the
    feature is enabled, then uses the topic to filter relevant skills.
    """
    from sibyl.orchestration.config_helpers import load_effective_config

    try:
        ws_root = detect_workspace_root(workspace_path)
        if ws_root is not None:
            ws_root = resolve_workspace_root(ws_root)
        config = load_effective_config(ws_root)
    except Exception:
        config = None

    if config is not None and not getattr(config, "orchestra_skills_enabled", True):
        return ""

    skills_dir = getattr(config, "orchestra_skills_dir", None) or "~/.orchestra/skills"
    max_skills = getattr(config, "orchestra_skills_max", 15)

    registry = _get_skill_registry(skills_dir)
    if not registry.entries:
        return ""

    # Read topic for filtering
    topic = ""
    if workspace_path:
        active_root = resolve_active_workspace_path(
            resolve_workspace_root(Path(workspace_path).expanduser())
            if ws_root is None else ws_root
        )
        for topic_path in (active_root / "topic.txt", ws_root / "topic.txt") if ws_root else ():
            if topic_path.exists():
                try:
                    topic = topic_path.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
                if topic:
                    break

    return registry.render_index(
        agent_name=agent_name,
        topic=topic,
        max_results=max_skills,
    )


def render_skill_prompt(
    agent_name: str,
    workspace_path: str | Path | None = None,
    runtime_args: dict | None = None,
) -> str:
    """Compile the effective prompt for a skill-facing agent."""
    role_prompt = _load_prompt_body(agent_name)
    if not role_prompt:
        return ""

    runtime_json = ""
    if runtime_args:
        runtime_json = json.dumps(runtime_args, indent=2, ensure_ascii=False)

    sections = _build_shared_runtime_sections(
        workspace_path=workspace_path,
        agent_name=agent_name,
    )
    if runtime_json:
        sections.append(PromptSection("Runtime Arguments", runtime_json))
    sections.append(PromptSection("Role Protocol", role_prompt))

    evolution_overlay = _load_evolution_overlay(agent_name, workspace_path)
    if evolution_overlay:
        sections.append(PromptSection("Evolution Lessons", evolution_overlay))
    project_overlay = load_project_prompt_overlay(agent_name, workspace_path)
    if project_overlay:
        sections.append(PromptSection("Project Overrides", project_overlay))

    orchestra_index = _build_orchestra_skills_section(
        agent_name=agent_name,
        workspace_path=workspace_path,
    )
    if orchestra_index:
        sections.append(PromptSection("Available Technical Skills", orchestra_index))

    return _render_prompt_sections(
        sections,
        heading=f"# Compiled Sibyl Skill Prompt: {agent_name}",
    )


def render_team_prompt(
    title: str,
    instructions: str,
    *,
    workspace_path: str | Path,
    language: str = "zh",
    paper_output: bool = False,
) -> str:
    """Compile a consistent team prompt for dynamic multi-agent discussions."""
    output_contract = (
        "All paper drafts, critiques, and figure/table references must remain in English."
        if paper_output
        else f"All non-paper outputs must use {_control_plane_language(language)}."
    )
    sections = [
        PromptSection("Objective", title),
        PromptSection("Workspace", f"Workspace: {workspace_path}"),
        PromptSection("Output Contract", output_contract),
        PromptSection("Execution", instructions),
    ]
    return _render_prompt_sections(
        sections,
        heading="# Compiled Sibyl Team Prompt",
    )


def _render_control_plane_loop(workspace_path: str | Path | None = None) -> str:
    workspace = str(workspace_path or "WORKSPACE_PATH")
    sections = [
        PromptSection(
            "Mission",
            textwrap.dedent(
                f"""
                You are the Sibyl control plane. The system must keep iterating toward stronger research artifacts and
                should never enter a manual pause state unless the user explicitly requested `/sibyl-research:stop`.
                The active workspace is `{workspace}`.
                """
            ).strip(),
        ),
        PromptSection(
            "Approved CLI APIs",
            textwrap.dedent(
                """
                Use only these repo-local CLIs for orchestration:
                - `cli_next(workspace)` -> next action payload
                - `cli_record(workspace, stage)` -> persist stage completion
                - `cli_resume(workspace)` -> clear manual stop / legacy pause markers and return recovery hints
                - `cli_status(workspace)` -> inspect current stage and iteration
                - `cli_dispatch_tasks(workspace)` -> start queued experiment tasks when GPUs free up
                - `cli_experiment_status(workspace)` -> render the experiment progress panel
                - `cli_sentinel_session(workspace, session_id, tmux_pane)` / `cli_sentinel_config(workspace)` -> Sentinel helpers
                """
            ).strip(),
        ),
        PromptSection(
            "Progress Tracking",
            textwrap.dedent(
                f"""
                Before entering the loop:
                1. Call `cli_status('{workspace}')` to get the current stage and iteration.
                2. For each remaining stage from current through `done`, create a Task:
                   - subject: `[project] #iteration - stage_name`
                   - Chain each Task with `addBlockedBy` pointing to the previous Task ID.
                3. Track the current stage Task ID for updates inside the loop.

                After each successful `cli_record`:
                - `TaskUpdate(taskId=current_stage_task, status="completed")`
                - Advance tracked Task ID to the next stage.

                On new iteration (after `quality_gate` triggers a new cycle):
                - Mark all remaining old-iteration Tasks as `completed`.
                - Create a fresh dependency chain for the new iteration stages.
                """
            ).strip(),
        ),
        PromptSection(
            "Loop",
            textwrap.dedent(
                f"""
                1. Call `cli_next('{workspace}')`.
                2. Export `SIBYL_LANGUAGE=<action.language>` every loop before dispatching any skill.
                3. Dispatch by `action_type`:
                   - `skill`: invoke the listed Sibyl skill directly.
                   - `skills_parallel`: start all listed skills in parallel and wait for all of them.
                   - `team`: create the requested agent team, assign teammates explicitly, then run post-steps in order.
                   - `bash`: execute `bash_command`.
                   - `gpu_poll`: keep polling until GPUs free up; never pause on timeout.
                   - `experiment_wait`: keep polling running experiments until all tasks finish; render the status panel each poll.
                   - `done`: emit `SIBYL_PIPELINE_COMPLETE`.
                   - `stopped`: run `cli_resume('{workspace}')` only when the user asked to continue or resume.
                     If the resume payload reports pending hooks or background agents, restart them before restarting the loop.
                4. After successful execution, call `cli_record('{workspace}', action.stage)`.
                5. If `cli_record` returns `sync_requested: true`, start the background lark sync flow (`run_in_background`)
                   without blocking the main loop.
                """
            ).strip(),
        ),
        PromptSection(
            "Experiment Monitoring",
            textwrap.dedent(
                f"""
                For `skill`, `skills_parallel`, or `experiment_wait` actions carrying `experiment_monitor`:
                - immediately start `experiment_monitor.background_agent` with `run_in_background=true`; do not wait
                - treat that background supervisor as the long-lived owner for GPU refresh, queue dispatch, and runtime-drift intervention
                - treat `experiment_monitor.wake_cmd` as a high-priority inbox from the background supervisor
                - never sleep for the full poll interval in one chunk; break waiting into `experiment_monitor.wake_check_interval_sec` chunks
                  and call `experiment_monitor.wake_cmd` after each chunk
                - if the wake payload reports `wake_requested=true`, immediately inspect the returned events before continuing
                - if any event says `requires_main_system=true` or `kind=needs_main_system`, stop waiting and collaborate now
                - check remote completion markers via SSH MCP
                - call `cli_experiment_status('{workspace}')` every poll and show its `display` text directly to the user
                - when work completes and GPUs free up, call `cli_dispatch_tasks('{workspace}')` and launch any returned skills
                - before exiting an experiment wait loop, synchronize experiment recovery state so stage transitions see completed work
                - adaptive cadence remains: remaining <=30min -> 2min, 30-120min -> 5min, >120min -> 10min
                """
            ).strip(),
        ),
        PromptSection(
            "Failure Handling",
            textwrap.dedent(
                f"""
                Retry transient SSH/network/rate-limit failures with backoff. Fix import/name errors by consulting the approved CLI list.
                Do not call `cli_pause`. If a legacy pause marker is present, use `cli_resume('{workspace}')` or re-run `cli_next`,
                then continue automatically.
                """
            ).strip(),
        ),
    ]
    return _render_prompt_sections(
        sections,
        heading="# Sibyl Control-Plane Loop",
    )


def render_control_plane_prompt(
    kind: str,
    *,
    workspace_path: str | Path | None = None,
    project_name: str | None = None,
) -> str:
    """Compile the runtime control-plane prompt for plugin commands and Ralph loop."""
    workspace = str(workspace_path or "WORKSPACE_PATH")
    if kind in {"loop", "orchestration_loop"}:
        return _render_control_plane_loop(workspace)
    if kind in {"ralph", "ralph_loop"}:
        project = project_name or Path(workspace).name or "PROJECT_NAME"
        sections = [
            PromptSection(
                "Project",
                f"Project: `{project}`\nWorkspace: `{workspace}`",
            ),
            PromptSection(
                "Bootstrap",
                textwrap.dedent(
                    f"""
                    1. Read `{workspace}/breadcrumb.json` to recover the last known stage and loop state.
                    2. If `{workspace}/lark_sync/pending_sync.jsonl` still has pending entries, immediately restart
                       `sibyl-lark-sync` in the background and do not wait for it.
                    3. Read `{workspace}/logs/research_diary.md` for iteration history and context.
                    4. On the first `cli_next('{workspace}')` after a resume/continue, treat the returned action as
                       authoritative recovery state: if it carries `experiment_monitor.background_agent`, restart that
                       background agent before continuing the main loop.
                    5. Follow the compiled control-plane loop below for every iteration.
                    """
                ).strip(),
            ),
            PromptSection(
                "Control-Plane Loop",
                _render_control_plane_loop(workspace),
            ),
        ]
        return _render_prompt_sections(
            sections,
            heading="# Sibyl Ralph Loop Runtime",
        )
    raise ValueError(f"Unknown control-plane prompt kind: {kind}")


def _load_workspace_action_plan(
    ws: Workspace,
    rel_path: str = "reflection/action_plan.json",
    *,
    persist_normalized: bool = False,
) -> dict | None:
    """Load and normalize a reflection action plan if present."""
    from sibyl.evolution import normalize_action_plan

    raw = ws.read_file(rel_path)
    if not raw:
        return None
    try:
        action_plan = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    normalized = normalize_action_plan(action_plan)
    if persist_normalized and normalized != action_plan:
        ws.write_file(
            rel_path,
            json.dumps(normalized, indent=2, ensure_ascii=False),
        )
    return normalized


def _load_prompt_evolution_context(
    workspace_path: str | Path | None,
) -> tuple[str, str, list[str]]:
    """Collect workspace context for lesson filtering."""
    from sibyl.evolution import normalize_action_plan

    workspace_root = detect_workspace_root(workspace_path)
    if workspace_root is None:
        return "", "", []

    workspace_root = resolve_workspace_root(workspace_root)
    active_root = resolve_active_workspace_path(workspace_root)
    stage = ""
    topic = ""
    recent_issues: list[str] = []
    seen_issues: set[str] = set()

    status_path = workspace_root / "status.json"
    if status_path.exists():
        try:
            status_data = json.loads(status_path.read_text(encoding="utf-8"))
            stage = str(status_data.get("stage", "") or "")
        except (json.JSONDecodeError, OSError, TypeError):
            stage = ""

    for topic_path in (active_root / "topic.txt", workspace_root / "topic.txt"):
        if topic_path.exists():
            try:
                topic = topic_path.read_text(encoding="utf-8").strip()
            except OSError:
                topic = ""
            if topic:
                break

    plan_candidates = [
        active_root / "reflection" / "action_plan.json",
        active_root / "reflection" / "prev_action_plan.json",
        workspace_root / "reflection" / "action_plan.json",
        workspace_root / "reflection" / "prev_action_plan.json",
    ]
    for plan_path in plan_candidates:
        if not plan_path.exists():
            continue
        try:
            action_plan = normalize_action_plan(
                json.loads(plan_path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        for issue in action_plan.get("issues_classified", []):
            if issue.get("status") == "fixed":
                continue
            description = str(issue.get("description", "")).strip()
            if description and description not in seen_issues:
                seen_issues.add(description)
                recent_issues.append(description)
        if recent_issues:
            break

    return topic, stage, recent_issues


def _load_evolution_overlay(
    agent_name: str,
    workspace_path: str | Path | None = None,
) -> str:
    """Load contextual lessons first, then fall back to the global overlay."""
    from sibyl.evolution import (
        EvolutionEngine,
        ensure_workspace_snapshot,
    )

    topic, stage, recent_issues = _load_prompt_evolution_context(workspace_path)
    workspace_root = detect_workspace_root(workspace_path)
    if workspace_root is not None:
        workspace_root = resolve_workspace_root(workspace_root)
        snapshot_dir = ensure_workspace_snapshot(workspace_root)
        engine = EvolutionEngine(snapshot_dir)
        if topic or stage or recent_issues:
            contextual = engine.filter_relevant_lessons(
                agent_name=agent_name,
                topic=topic,
                stage=stage,
                recent_issues=recent_issues,
            )
            if contextual:
                return contextual

        overlay_path = snapshot_dir / "lessons" / f"{agent_name}.md"
        if overlay_path.exists():
            return overlay_path.read_text(encoding="utf-8")
        return ""

    engine = EvolutionEngine()
    if topic or stage or recent_issues:
        contextual = engine.filter_relevant_lessons(
            agent_name=agent_name,
            topic=topic,
            stage=stage,
            recent_issues=recent_issues,
        )
        if contextual:
            return contextual

    overlay_path = engine.EVOLUTION_DIR / "lessons" / f"{agent_name}.md"
    if overlay_path.exists():
        return overlay_path.read_text(encoding="utf-8")
    return ""


def _append_prompt_layer(base: str, content: str) -> str:
    if content.strip():
        return f"{base}\n\n---\n\n{content}"
    return base


def load_prompt(
    agent_name: str,
    overlay_content: str | None = None,
    workspace_path: str | Path | None = None,
) -> str:
    """Load an agent prompt from the prompts directory with overlay injection."""
    path = PROMPTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return ""
    base = path.read_text(encoding="utf-8")

    if overlay_content is not None:
        base = _append_prompt_layer(base, overlay_content)
    else:
        overlay = _load_evolution_overlay(agent_name, workspace_path)
        if overlay:
            base = _append_prompt_layer(base, overlay)

    project_overlay = load_project_prompt_overlay(agent_name, workspace_path)
    if project_overlay:
        base = _append_prompt_layer(base, project_overlay)

    return base


def load_common_prompt(workspace_path: str | Path | None = None) -> str:
    """Load the common instructions prompt in the configured language."""
    lang = os.environ.get("SIBYL_LANGUAGE", "zh")
    filename = "_common_zh" if lang == "zh" else "_common"
    prompt = load_prompt(filename, workspace_path=workspace_path)
    project_memory = load_project_memory(workspace_path)
    if project_memory:
        prompt = _append_prompt_layer(prompt, project_memory)
    return prompt


def cli_write_ralph_prompt(
    workspace_path: str,
    project_name: str | None = None,
    output_path: str | None = None,
) -> None:
    """Compile the Ralph loop runtime prompt and write it to disk."""
    from sibyl.evolution import sync_workspace_snapshot

    workspace_root = resolve_workspace_root(Path(workspace_path).expanduser())
    if project_name is None:
        project_name = workspace_root.name
    sync_workspace_snapshot(workspace_root)

    output_file = (workspace_root / ".claude" / "ralph-prompt.txt").resolve()
    mirror_output: Path | None = None
    if output_path:
        mirror_output = Path(output_path).expanduser()
        if not mirror_output.is_absolute():
            mirror_output = workspace_root / mirror_output
        mirror_output = mirror_output.resolve()

    content = render_control_plane_prompt(
        "ralph_loop",
        workspace_path=workspace_root,
        project_name=project_name,
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8")
    if mirror_output is not None and mirror_output != output_file:
        mirror_output.parent.mkdir(parents=True, exist_ok=True)
        mirror_output.write_text(content, encoding="utf-8")
    state_path = workspace_root / ".sibyl" / "project" / "ralph_loop_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "workspace_path": str(workspace_root),
                "workspace_scope": workspace_scope_id(workspace_root),
                "project_name": project_name,
                "output_path": str(output_file),
                "mirror_output_path": str(mirror_output) if mirror_output else "",
                "compiled_at": os.path.getmtime(output_file),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "ok",
        "workspace_path": str(workspace_root),
        "workspace_scope": workspace_scope_id(workspace_root),
        "output_path": str(output_file),
        "mirror_output_path": str(mirror_output) if mirror_output else "",
        "state_path": str(state_path.resolve()),
        "project_name": project_name,
        "chars": len(content),
    }))
