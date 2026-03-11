"""Helpers for parsing writing-stage artifact metadata."""

from __future__ import annotations

import re


_FIGURES_BLOCK_RE = re.compile(
    r"<!--\s*FIGURES\s*(.*?)-->",
    re.IGNORECASE | re.DOTALL,
)
_FIGURE_ARTIFACT_RE = re.compile(
    r"[\w./-]+\.(?:pdf|png|svg|py|md)",
    re.IGNORECASE,
)


def extract_section_figure_artifacts(section_markdown: str) -> tuple[list[str], bool]:
    """Extract figure-related artifact paths from a section's FIGURES block."""
    match = _FIGURES_BLOCK_RE.search(section_markdown)
    if match is None:
        return ([], False)

    artifacts: list[str] = []
    seen: set[str] = set()

    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        if line.lower() in {"- none", "- no figures", "- no figure"}:
            continue

        artifact_part = line
        if ":" in artifact_part:
            artifact_part = artifact_part.split(":", 1)[1]
        artifact_part = re.split(r"\s+—\s+|\s+-\s+", artifact_part, maxsplit=1)[0]

        for artifact in _FIGURE_ARTIFACT_RE.findall(artifact_part):
            rel_path = artifact if "/" in artifact else f"writing/figures/{artifact}"
            if rel_path not in seen:
                seen.add(rel_path)
                artifacts.append(rel_path)

    return (artifacts, True)
