"""Rebuttal CLI entry points — independent from the research pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from .orchestrator import RebuttalOrchestrator
from .workspace_setup import init_workspace


def cli_rebuttal_init(
    paper_path: str,
    reviews_dir: str,
    workspace_dir: str | None = None,
    project_name: str | None = None,
    word_limit: int = 0,
    source_repo: str | None = None,
    codex_enabled: bool = False,
    language: str = "en",
) -> str:
    """Initialize a rebuttal workspace with paper and reviews.

    Returns JSON string with workspace info.
    """
    paper = Path(paper_path).expanduser().resolve()

    if project_name is None:
        project_name = f"rebuttal-{paper.stem}"

    if workspace_dir is None:
        workspace_dir = str(Path.cwd() / "rebuttals" / project_name)

    ws_dir = Path(workspace_dir).expanduser().resolve()

    info = init_workspace(
        ws_dir,
        paper_path,
        reviews_dir,
        source_repo=source_repo,
        word_limit=word_limit,
        codex_enabled=codex_enabled,
        language=language,
    )

    # Auto-advance past transient init stage so cli_rebuttal_next
    # returns parse_reviews immediately without requiring a manual record("init").
    orchestrator = RebuttalOrchestrator(str(ws_dir))
    orchestrator.record_result("init")

    result = json.dumps(info, indent=2, ensure_ascii=False)
    print(result)
    return result


def cli_rebuttal_next(workspace_path: str) -> str:
    """Get the next rebuttal action.

    Returns JSON action dict.
    """
    orchestrator = RebuttalOrchestrator(workspace_path)
    action = orchestrator.get_next_action()
    result = json.dumps(action, indent=2, ensure_ascii=False)
    print(result)
    return result


def cli_rebuttal_record(
    workspace_path: str,
    stage: str,
    result: str = "",
    score: float | None = None,
) -> str:
    """Record rebuttal stage completion and advance state.

    Returns JSON with new stage info.
    """
    orchestrator = RebuttalOrchestrator(workspace_path)
    record_result = orchestrator.record_result(stage, result, score)
    output = json.dumps(record_result, indent=2, ensure_ascii=False)
    print(output)
    return output


def cli_rebuttal_status(workspace_path: str) -> str:
    """Get rebuttal project status with score trajectory.

    Returns JSON status dict.
    """
    orchestrator = RebuttalOrchestrator(workspace_path)
    status = orchestrator.get_status()
    result = json.dumps(status, indent=2, ensure_ascii=False)
    print(result)
    return result
