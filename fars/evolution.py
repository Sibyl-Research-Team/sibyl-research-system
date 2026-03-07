"""Auto-evolution system for FARS v4.

Learns from cross-project experience to improve prompts and workflows.
"""
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class EvolutionInsight:
    pattern: str  # what was observed
    frequency: int  # how many times
    severity: str  # low, medium, high
    suggestion: str  # proposed fix
    affected_stages: list[str] = field(default_factory=list)


@dataclass
class OutcomeRecord:
    project: str
    stage: str
    issues: list[str]
    score: float
    notes: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class EvolutionEngine:
    """Cross-project experience learning and prompt improvement."""

    EVOLUTION_DIR = Path.home() / ".claude" / "fars_evolution"

    def __init__(self):
        self.EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)
        self.outcomes_path = self.EVOLUTION_DIR / "outcomes.jsonl"
        self.insights_path = self.EVOLUTION_DIR / "insights.json"
        self.patches_path = self.EVOLUTION_DIR / "prompt_patches.json"

    def record_outcome(self, project: str, stage: str,
                       issues: list[str], score: float, notes: str = ""):
        """Record the outcome of a pipeline stage."""
        record = OutcomeRecord(
            project=project, stage=stage, issues=issues,
            score=score, notes=notes
        )
        with open(self.outcomes_path, "a") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def analyze_patterns(self) -> list[EvolutionInsight]:
        """Analyze recorded outcomes for recurring patterns."""
        outcomes = self._load_outcomes()
        if not outcomes:
            return []

        # Count issue frequencies
        issue_counts: dict[str, dict] = {}
        for outcome in outcomes:
            for issue in outcome.get("issues", []):
                key = issue.lower().strip()
                if key not in issue_counts:
                    issue_counts[key] = {
                        "count": 0, "stages": set(), "scores": []
                    }
                issue_counts[key]["count"] += 1
                issue_counts[key]["stages"].add(outcome["stage"])
                issue_counts[key]["scores"].append(outcome["score"])

        # Generate insights for frequent issues
        insights = []
        for issue, data in issue_counts.items():
            if data["count"] >= 2:  # appears 2+ times
                avg_score = sum(data["scores"]) / len(data["scores"])
                severity = "high" if data["count"] >= 3 else "medium"
                insights.append(EvolutionInsight(
                    pattern=issue,
                    frequency=data["count"],
                    severity=severity,
                    suggestion=f"Recurring issue ({data['count']}x): consider prompt enhancement",
                    affected_stages=list(data["stages"]),
                ))

        # Save insights
        self._save_insights(insights)
        return insights

    def generate_prompt_patches(self) -> dict[str, str]:
        """Generate suggested prompt improvements based on insights."""
        insights = self.analyze_patterns()
        patches = {}

        for insight in insights:
            if insight.severity == "high":
                for stage in insight.affected_stages:
                    key = f"{stage}_enhancement"
                    patches[key] = (
                        f"LEARNED FROM EXPERIENCE: {insight.pattern} "
                        f"(seen {insight.frequency}x). "
                        f"Suggestion: {insight.suggestion}"
                    )

        # Save patches
        if patches:
            self.patches_path.write_text(
                json.dumps(patches, indent=2, ensure_ascii=False)
            )

        return patches

    def apply_evolution(self, patches: dict[str, str],
                        dry_run: bool = True) -> dict[str, str]:
        """Apply prompt patches. Returns applied patches."""
        if dry_run:
            return {k: f"[DRY RUN] Would apply: {v}" for k, v in patches.items()}

        # In production, this would modify PromptTemplates
        applied = {}
        for key, patch in patches.items():
            applied[key] = patch

        return applied

    def get_quality_trend(self, project: str | None = None) -> list[dict]:
        """Get quality score trend over time."""
        outcomes = self._load_outcomes()
        if project:
            outcomes = [o for o in outcomes if o["project"] == project]
        return [
            {"timestamp": o["timestamp"], "stage": o["stage"], "score": o["score"]}
            for o in outcomes
        ]

    def _load_outcomes(self) -> list[dict]:
        if not self.outcomes_path.exists():
            return []
        records = []
        for line in self.outcomes_path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def _save_insights(self, insights: list[EvolutionInsight]):
        data = [asdict(i) for i in insights]
        self.insights_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
