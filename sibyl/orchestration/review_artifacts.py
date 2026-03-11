"""Helpers for structured review artifacts produced by critique/review agents."""

from __future__ import annotations

import json
import re
from typing import Any


def _read_json_artifact(ws: Any, relative_path: str) -> dict | None:
    content = ws.read_file(relative_path)
    if not content:
        return None
    try:
        data = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_supervisor_review(ws: Any) -> dict | None:
    """Load the canonical supervisor review payload when present."""
    review = _read_json_artifact(ws, "supervisor/review.json")
    return review if review else None


def load_critic_findings(ws: Any) -> dict | None:
    """Load the canonical critic findings payload when present."""
    findings = _read_json_artifact(ws, "critic/findings.json")
    return findings if findings else None


def extract_supervisor_score(ws: Any) -> tuple[dict | None, float]:
    """Return the structured review payload and the effective quality score."""
    review = load_supervisor_review(ws)
    if review is not None:
        value = review.get("score")
        if isinstance(value, (int, float)):
            return review, min(max(float(value), 0.0), 10.0)

    review_md = ws.read_file("supervisor/review_writing.md") or ""
    match = re.search(
        r"(?:score|rating|quality)[:\s]*(\d+(?:\.\d+)?)(?!\w)",
        review_md,
        re.IGNORECASE,
    )
    score = min(max(float(match.group(1)), 0.0), 10.0) if match else 5.0
    return review, score


def extract_supervisor_issues(ws: Any) -> list[dict]:
    """Load issue entries from the canonical review payload or legacy file."""
    review = load_supervisor_review(ws)
    if review is not None:
        issues = review.get("issues")
        if isinstance(issues, list):
            return [issue for issue in issues if isinstance(issue, dict)]

    raw_issues = ws.read_file("supervisor/issues.json")
    if not raw_issues:
        return []
    try:
        data = json.loads(raw_issues)
    except (TypeError, json.JSONDecodeError):
        return []
    return [issue for issue in data if isinstance(issue, dict)] if isinstance(data, list) else []


def summarize_supervisor_review(ws: Any) -> str:
    """Return a short human-readable supervisor summary."""
    review = load_supervisor_review(ws)
    if review is not None:
        verdict = str(review.get("verdict", "")).strip()
        rationale = str(review.get("summary", "")).strip()
        summary = " ".join(part for part in (verdict, rationale) if part).strip()
        if summary:
            return summary
    return ws.read_file("supervisor/review_writing.md") or ""


def summarize_critic_findings(ws: Any) -> str:
    """Return a short human-readable critic summary."""
    findings = load_critic_findings(ws)
    if findings is not None:
        summary = str(findings.get("summary", "")).strip()
        if summary:
            return summary
        items = findings.get("findings")
        if isinstance(items, list):
            snippets = [
                str(item.get("description", "")).strip()
                for item in items
                if isinstance(item, dict) and item.get("description")
            ]
            if snippets:
                return "\n".join(f"- {snippet}" for snippet in snippets[:5])
    return ws.read_file("critic/critique_writing.md") or ""
