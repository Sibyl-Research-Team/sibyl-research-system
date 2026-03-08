"""Auto-evolution system for Sibyl v4.

Learns from cross-project experience to improve prompts and workflows.
"""
import json
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path


class IssueCategory(str, Enum):
    SYSTEM = "system"       # SSH failure, timeout, format error, OOM
    RESEARCH = "research"   # weak experiment design, poor writing, insufficient analysis
    PIPELINE = "pipeline"   # stage ordering, missing steps, redundant steps

    @staticmethod
    def classify(description: str) -> "IssueCategory":
        """Classify an issue description into a category via keyword matching."""
        desc = description.lower()
        system_keywords = [
            "ssh", "timeout", "oom", "out of memory", "connection",
            "format error", "json", "parse", "encoding", "disk",
            "gpu", "cuda", "permission", "file not found", "crash",
            "killed", "segfault", "broken pipe",
        ]
        pipeline_keywords = [
            "stage", "order", "skip", "missing step", "redundant",
            "pipeline", "orchestrat", "workflow", "sequence",
            "duplicate", "state machine", "transition",
        ]
        if any(kw in desc for kw in system_keywords):
            return IssueCategory.SYSTEM
        if any(kw in desc for kw in pipeline_keywords):
            return IssueCategory.PIPELINE
        return IssueCategory.RESEARCH


@dataclass
class EvolutionInsight:
    pattern: str  # what was observed
    frequency: int  # how many times
    severity: str  # low, medium, high
    suggestion: str  # proposed fix
    affected_stages: list[str] = field(default_factory=list)
    category: str = ""  # IssueCategory value


@dataclass
class OutcomeRecord:
    project: str
    stage: str
    issues: list[str]
    score: float
    notes: str
    timestamp: str = ""
    classified_issues: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.classified_issues and self.issues:
            self.classified_issues = [
                {"description": issue, "category": IssueCategory.classify(issue).value}
                for issue in self.issues
            ]


class EvolutionEngine:
    """Cross-project experience learning and prompt improvement."""

    EVOLUTION_DIR = Path.home() / ".claude" / "sibyl_evolution"

    def __init__(self):
        self.EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)
        self.outcomes_path = self.EVOLUTION_DIR / "outcomes.jsonl"
        self.insights_path = self.EVOLUTION_DIR / "insights.json"


    def record_outcome(self, project: str, stage: str,
                       issues: list[str], score: float, notes: str = ""):
        """Record the outcome of a pipeline stage."""
        record = OutcomeRecord(
            project=project, stage=stage, issues=issues,
            score=score, notes=notes
        )
        with open(self.outcomes_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def analyze_patterns(self) -> list[EvolutionInsight]:
        """Analyze recorded outcomes for recurring patterns, grouped by category."""
        outcomes = self._load_outcomes()
        if not outcomes:
            return []

        # Count issue frequencies with category tracking
        issue_counts: dict[str, dict] = {}
        for outcome in outcomes:
            classified = outcome.get("classified_issues", [])
            if not classified:
                # Fallback for legacy records without classification
                classified = [
                    {"description": issue, "category": IssueCategory.classify(issue).value}
                    for issue in outcome.get("issues", [])
                ]
            for ci in classified:
                key = ci["description"].lower().strip()
                if key not in issue_counts:
                    issue_counts[key] = {
                        "count": 0, "stages": set(), "scores": [],
                        "category": ci.get("category", "research"),
                    }
                issue_counts[key]["count"] += 1
                issue_counts[key]["stages"].add(outcome["stage"])
                issue_counts[key]["scores"].append(outcome["score"])

        # Generate insights for frequent issues
        insights = []
        for issue, data in issue_counts.items():
            if data["count"] >= 2:  # appears 2+ times
                severity = "high" if data["count"] >= 3 else "medium"
                insights.append(EvolutionInsight(
                    pattern=issue,
                    frequency=data["count"],
                    severity=severity,
                    suggestion=f"Recurring issue ({data['count']}x): consider prompt enhancement",
                    affected_stages=list(data["stages"]),
                    category=data["category"],
                ))

        # Save insights
        self._save_insights(insights)
        return insights

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
        for line in self.outcomes_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # skip corrupted lines
        return records

    def generate_lessons_overlay(self, project: str | None = None) -> dict[str, str]:
        """Generate per-agent overlay files from accumulated insights.

        Returns dict mapping agent_name -> overlay content written.
        """
        insights = self.analyze_patterns()
        if not insights:
            return {}

        # Group insights by affected stage (= agent name)
        stage_insights: dict[str, list[EvolutionInsight]] = {}
        for insight in insights:
            for stage in insight.affected_stages:
                stage_insights.setdefault(stage, []).append(insight)

        lessons_dir = self.EVOLUTION_DIR / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)

        written = {}
        for agent_name, agent_insights in stage_insights.items():
            # Sort by severity then frequency
            agent_insights.sort(
                key=lambda i: (0 if i.severity == "high" else 1, -i.frequency)
            )
            lines = ["# 经验教训 (自动生成)\n"]
            for ins in agent_insights:
                sev = ins.severity.upper()
                cat = ins.category.upper() if ins.category else "RESEARCH"
                lines.append(
                    f"- [{sev}][{cat}] {ins.pattern} (出现 {ins.frequency} 次)"
                )
            content = "\n".join(lines) + "\n"
            overlay_path = lessons_dir / f"{agent_name}.md"
            overlay_path.write_text(content, encoding="utf-8")
            written[agent_name] = content

        return written

    def run_cross_project_evolution(self) -> dict[str, str]:
        """Analyze all project outcomes and regenerate global lessons overlay.

        Called when a pipeline completes (quality_gate returns done).
        """
        # Regenerate overlays from all accumulated data
        written = self.generate_lessons_overlay()

        # Write global summary
        insights = self.analyze_patterns()
        if insights:
            summary_lines = ["# 西比拉全局经验总结 (自动生成)\n"]
            by_cat: dict[str, list[EvolutionInsight]] = {}
            for ins in insights:
                by_cat.setdefault(ins.category or "research", []).append(ins)

            for cat, cat_insights in sorted(by_cat.items()):
                summary_lines.append(f"\n## {cat.upper()} 类问题\n")
                for ins in sorted(cat_insights, key=lambda i: -i.frequency):
                    summary_lines.append(
                        f"- [{ins.severity.upper()}] {ins.pattern} "
                        f"(出现 {ins.frequency} 次, 影响阶段: {', '.join(ins.affected_stages)})"
                    )

            global_path = self.EVOLUTION_DIR / "global_lessons.md"
            global_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

        return written

    def get_overlay_content(self) -> dict[str, str]:
        """Get all current overlay file contents. For CLI display."""
        lessons_dir = self.EVOLUTION_DIR / "lessons"
        if not lessons_dir.exists():
            return {}
        result = {}
        for f in sorted(lessons_dir.glob("*.md")):
            result[f.stem] = f.read_text(encoding="utf-8")
        return result

    def reset_overlays(self):
        """Remove all overlay files. Prompts revert to base."""
        lessons_dir = self.EVOLUTION_DIR / "lessons"
        if lessons_dir.exists():
            for f in lessons_dir.glob("*.md"):
                f.unlink()
        global_path = self.EVOLUTION_DIR / "global_lessons.md"
        if global_path.exists():
            global_path.unlink()

    def _save_insights(self, insights: list[EvolutionInsight]):
        data = [asdict(i) for i in insights]
        self.insights_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
