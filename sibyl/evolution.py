"""Auto-evolution system for Sibyl v4.

Learns from cross-project experience to improve prompts and workflows.
"""
import json
import math
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path


class IssueCategory(str, Enum):
    SYSTEM = "system"           # SSH, timeout, OOM, GPU, format errors
    EXPERIMENT = "experiment"   # experiment design, baseline, reproducibility
    WRITING = "writing"         # paper quality, clarity, structure, consistency
    ANALYSIS = "analysis"       # weak analysis, missing comparison, statistics
    PLANNING = "planning"       # bad plan, scope, resource estimation
    PIPELINE = "pipeline"       # stage ordering, missing steps, orchestration
    IDEATION = "ideation"       # weak ideas, lack of novelty, poor motivation

    @staticmethod
    def classify(description: str) -> "IssueCategory":
        """Classify an issue description into a category via keyword matching."""
        desc = description.lower()
        system_keywords = [
            "ssh", "timeout", "oom", "out of memory", "connection",
            "format error", "json", "parse", "encoding", "disk",
            "gpu", "cuda", "permission", "file not found", "crash",
            "killed", "segfault", "broken pipe", "rate limit",
        ]
        experiment_keywords = [
            "experiment", "baseline", "reproduc", "seed", "hyperparameter",
            "training", "convergence", "loss", "accuracy", "metric",
            "ablation", "control", "variance", "overfitting",
        ]
        writing_keywords = [
            "writing", "paper", "clarity", "readab", "grammar",
            "structure", "section", "paragraph", "notation", "consistency",
            "word count", "too long", "too short", "redundant text",
            "citation", "reference", "figure", "table", "caption",
        ]
        analysis_keywords = [
            "analysis", "comparison", "statistic", "significance",
            "interpret", "discuss", "evidence", "insufficient",
            "cherry-pick", "selective", "bias", "confound",
        ]
        planning_keywords = [
            "plan", "scope", "resource", "estimate", "timeline",
            "feasib", "complexity", "ambiguous", "underspecif",
        ]
        pipeline_keywords = [
            "stage", "order", "skip", "missing step", "redundant",
            "pipeline", "orchestrat", "workflow", "sequence",
            "duplicate", "state machine", "transition",
        ]
        ideation_keywords = [
            "idea", "novel", "originality", "motivation", "innovation",
            "incremental", "trivial", "contribution", "related work",
        ]
        # Check in specificity order (most specific first)
        if any(kw in desc for kw in system_keywords):
            return IssueCategory.SYSTEM
        if any(kw in desc for kw in experiment_keywords):
            return IssueCategory.EXPERIMENT
        if any(kw in desc for kw in writing_keywords):
            return IssueCategory.WRITING
        if any(kw in desc for kw in analysis_keywords):
            return IssueCategory.ANALYSIS
        if any(kw in desc for kw in planning_keywords):
            return IssueCategory.PLANNING
        if any(kw in desc for kw in pipeline_keywords):
            return IssueCategory.PIPELINE
        if any(kw in desc for kw in ideation_keywords):
            return IssueCategory.IDEATION
        return IssueCategory.ANALYSIS  # default to analysis (most common research issue)


# Map issue categories to the agent prompt names that should receive the lesson.
# These names must match filenames in sibyl/prompts/ (without .md).
CATEGORY_TO_AGENTS: dict[str, list[str]] = {
    "system": ["experimenter", "server_experimenter"],
    "experiment": ["experimenter", "server_experimenter", "planner"],
    "writing": ["sequential_writer", "section_writer", "editor", "codex_writer"],
    "analysis": ["supervisor", "critic", "skeptic", "reflection"],
    "planning": ["planner", "synthesizer"],
    "pipeline": ["reflection"],
    "ideation": ["innovator", "pragmatist", "theoretical", "synthesizer"],
}

# Suggestion templates per category — much more specific than a generic "consider prompt enhancement"
CATEGORY_SUGGESTIONS: dict[str, str] = {
    "system": "检查 SSH 连接/GPU 资源/超时设置。实验前先验证环境可用性。",
    "experiment": "加强实验设计：确保有 baseline 对比、固定 seed、做 ablation study。",
    "writing": "改进论文写作：注意章节间一致性、notation 统一、避免冗余。",
    "analysis": "深化分析：不要 cherry-pick 结果、补充统计显著性检验、讨论局限性。",
    "planning": "细化实验计划：明确资源需求、拆分子任务、预估时间。",
    "pipeline": "优化流程：检查阶段顺序、减少冗余步骤。",
    "ideation": "提升想法质量：强调创新性、与 related work 区分、明确贡献。",
}


@dataclass
class EvolutionInsight:
    pattern: str  # what was observed
    frequency: int  # how many times
    severity: str  # low, medium, high
    suggestion: str  # proposed fix
    affected_agents: list[str] = field(default_factory=list)
    category: str = ""  # IssueCategory value
    weighted_frequency: float = 0.0  # time-decayed frequency


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


# Half-life for lesson decay: 30 days. After 30 days, a lesson's weight halves.
_DECAY_HALF_LIFE_DAYS = 30.0


def _time_weight(timestamp_str: str) -> float:
    """Compute exponential decay weight based on age. Recent = 1.0, old → 0."""
    try:
        t = time.mktime(time.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        return 0.5  # unknown age → moderate weight
    age_days = (time.time() - t) / 86400.0
    if age_days < 0:
        age_days = 0
    return math.pow(0.5, age_days / _DECAY_HALF_LIFE_DAYS)


class EvolutionEngine:
    """Cross-project experience learning and prompt improvement."""

    EVOLUTION_DIR = Path.home() / ".claude" / "sibyl_evolution"

    def __init__(self):
        self.EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)
        self.outcomes_path = self.EVOLUTION_DIR / "outcomes.jsonl"
        self.insights_path = self.EVOLUTION_DIR / "insights.json"


    def record_outcome(self, project: str, stage: str,
                       issues: list[str], score: float, notes: str = "",
                       classified_issues: list[dict] | None = None):
        """Record the outcome of a pipeline stage.

        If classified_issues is provided (from reflection agent's action_plan.json),
        use it directly. Otherwise auto-classify from issue descriptions.
        """
        record = OutcomeRecord(
            project=project, stage=stage, issues=issues,
            score=score, notes=notes,
            classified_issues=classified_issues or [],
        )
        with open(self.outcomes_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def analyze_patterns(self) -> list[EvolutionInsight]:
        """Analyze recorded outcomes for recurring patterns with time decay."""
        outcomes = self._load_outcomes()
        if not outcomes:
            return []

        # Count issue frequencies with category tracking and time decay
        issue_counts: dict[str, dict] = {}
        for outcome in outcomes:
            weight = _time_weight(outcome.get("timestamp", ""))
            classified = outcome.get("classified_issues", [])
            if not classified:
                classified = [
                    {"description": issue, "category": IssueCategory.classify(issue).value}
                    for issue in outcome.get("issues", [])
                ]
            for ci in classified:
                key = ci["description"].lower().strip()
                if not key:
                    continue
                if key not in issue_counts:
                    issue_counts[key] = {
                        "count": 0, "weighted": 0.0,
                        "category": ci.get("category", "analysis"),
                        "scores": [],
                    }
                issue_counts[key]["count"] += 1
                issue_counts[key]["weighted"] += weight
                issue_counts[key]["scores"].append(outcome["score"])

        # Generate insights for issues with significant weighted frequency
        insights = []
        for issue, data in issue_counts.items():
            # Require raw count >= 2 AND weighted frequency >= 1.0
            if data["count"] >= 2 and data["weighted"] >= 1.0:
                severity = "high" if data["weighted"] >= 2.5 else "medium"
                category = data["category"]
                agents = CATEGORY_TO_AGENTS.get(category, ["reflection"])
                suggestion = CATEGORY_SUGGESTIONS.get(category, "检查并改进相关环节。")
                insights.append(EvolutionInsight(
                    pattern=issue,
                    frequency=data["count"],
                    severity=severity,
                    suggestion=suggestion,
                    affected_agents=agents,
                    category=category,
                    weighted_frequency=round(data["weighted"], 2),
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
                    continue
        return records

    def generate_lessons_overlay(self, project: str | None = None) -> dict[str, str]:
        """Generate per-agent overlay files from accumulated insights.

        Routes lessons to actual agent prompt names via CATEGORY_TO_AGENTS mapping.
        Returns dict mapping agent_name -> overlay content written.
        """
        insights = self.analyze_patterns()
        if not insights:
            return {}

        # Group insights by affected agent (not stage!)
        agent_insights: dict[str, list[EvolutionInsight]] = {}
        for insight in insights:
            for agent in insight.affected_agents:
                agent_insights.setdefault(agent, []).append(insight)

        lessons_dir = self.EVOLUTION_DIR / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)

        written = {}
        for agent_name, insights_list in agent_insights.items():
            # Sort by severity then weighted frequency
            insights_list.sort(
                key=lambda i: (0 if i.severity == "high" else 1, -i.weighted_frequency)
            )
            lines = [
                "# 经验教训 (自动生成)",
                "",
                "以下是从历史项目中自动提炼的经验教训。请在执行任务时注意避免这些问题。",
                "",
            ]
            for ins in insights_list[:15]:  # cap at 15 lessons per agent
                sev = ins.severity.upper()
                cat = ins.category.upper() if ins.category else "ANALYSIS"
                lines.append(
                    f"- [{sev}][{cat}] {ins.pattern} "
                    f"(出现 {ins.frequency} 次, 权重 {ins.weighted_frequency})"
                )
                lines.append(f"  建议: {ins.suggestion}")
            content = "\n".join(lines) + "\n"
            overlay_path = lessons_dir / f"{agent_name}.md"
            overlay_path.write_text(content, encoding="utf-8")
            written[agent_name] = content

        return written

    def run_cross_project_evolution(self) -> dict[str, str]:
        """Analyze all project outcomes and regenerate global lessons overlay.

        Called when a pipeline completes (quality_gate returns done).
        """
        written = self.generate_lessons_overlay()

        insights = self.analyze_patterns()
        if insights:
            summary_lines = ["# 西比拉全局经验总结 (自动生成)\n"]
            by_cat: dict[str, list[EvolutionInsight]] = {}
            for ins in insights:
                by_cat.setdefault(ins.category or "analysis", []).append(ins)

            for cat, cat_insights in sorted(by_cat.items()):
                summary_lines.append(f"\n## {cat.upper()} 类问题\n")
                agents_str = ", ".join(CATEGORY_TO_AGENTS.get(cat, []))
                if agents_str:
                    summary_lines.append(f"影响 agent: {agents_str}\n")
                for ins in sorted(cat_insights, key=lambda i: -i.weighted_frequency):
                    summary_lines.append(
                        f"- [{ins.severity.upper()}] {ins.pattern} "
                        f"(出现 {ins.frequency} 次, 权重 {ins.weighted_frequency})"
                    )
                    summary_lines.append(f"  建议: {ins.suggestion}")

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
