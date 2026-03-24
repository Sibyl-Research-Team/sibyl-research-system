"""Rebuttal workspace initialization and input processing."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path


def init_workspace(
    workspace_dir: Path,
    paper_path: str,
    reviews_dir: str,
    *,
    source_repo: str | None = None,
    word_limit: int = 0,
    codex_enabled: bool = False,
    language: str = "en",
) -> dict:
    """Create and populate a rebuttal workspace.

    Returns workspace info dict with paths and reviewer IDs.
    """
    paper = Path(paper_path).expanduser().resolve()
    reviews = Path(reviews_dir).expanduser().resolve()

    if not paper.exists():
        raise FileNotFoundError(f"Paper not found: {paper}")
    if not reviews.exists() or not reviews.is_dir():
        raise FileNotFoundError(f"Reviews directory not found: {reviews}")

    # Create workspace structure
    workspace_dir = workspace_dir.resolve()
    for subdir in [
        "input/reviews",
        "parsed",
        "rounds/round_001/team",
        "rounds/round_001/synthesis",
        "rounds/round_001/sim_review",
        "output/per_reviewer",
        "codex",
        "context",
        "logs",
    ]:
        (workspace_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Set up current symlink
    current_link = workspace_dir / "rounds/current"
    if not current_link.exists():
        current_link.symlink_to("round_001")

    # Copy paper
    paper_dest = workspace_dir / "input" / paper.name
    shutil.copy2(paper, paper_dest)

    # Copy reviews and detect reviewer IDs
    reviewer_ids = []
    for review_file in sorted(reviews.iterdir()):
        if review_file.is_file() and review_file.suffix in (".md", ".txt", ".json", ".pdf"):
            dest = workspace_dir / "input/reviews" / review_file.name
            shutil.copy2(review_file, dest)
            # Derive reviewer ID from filename
            rid = review_file.stem
            rid = re.sub(r"[^\w-]", "_", rid)
            reviewer_ids.append(rid)

    if not reviewer_ids:
        raise ValueError(f"No review files found in {reviews}")

    # Copy source repo reference
    if source_repo:
        repo_path = Path(source_repo).expanduser().resolve()
        if repo_path.exists():
            repo_link = workspace_dir / "input/source_repo"
            if not repo_link.exists():
                repo_link.symlink_to(repo_path)

    # Write rebuttal config
    from .config import RebuttalConfig
    rc = RebuttalConfig(
        word_limit=word_limit,
        codex_enabled=codex_enabled,
        language=language,
        reviewer_count=len(reviewer_ids),
        reviewer_ids=reviewer_ids,
    )
    (workspace_dir / "rebuttal_config.yaml").write_text(rc.to_yaml(), encoding="utf-8")

    # Write initial status
    status = {
        "stage": "init",
        "round": 1,
        "started_at": time.time(),
        "updated_at": time.time(),
    }
    (workspace_dir / "status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8",
    )

    return {
        "workspace_path": str(workspace_dir),
        "paper": str(paper_dest),
        "reviewer_ids": reviewer_ids,
        "reviewer_count": len(reviewer_ids),
        "word_limit": word_limit,
        "codex_enabled": codex_enabled,
    }
