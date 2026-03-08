"""Auto-evolution system for Sibyl v4.

Learns from cross-project experience to improve prompts and workflows.
"""
import json
import math
import os
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
    EFFICIENCY = "efficiency"   # resource waste, GPU idle, slow iteration, scheduling

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
        efficiency_keywords = [
            "idle", "utilization", "waste", "underutiliz", "slow",
            "throughput", "scheduling", "dispatch", "queue", "bottleneck",
            "parallel", "batch size", "gpu idle", "waiting", "stall",
            "iteration speed", "turnaround", "resource efficien",
        ]
        # Check in specificity order (most specific first)
        # Efficiency before system: "gpu idle" is efficiency, not system error
        if any(kw in desc for kw in efficiency_keywords):
            return IssueCategory.EFFICIENCY
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
    "efficiency": ["planner", "experimenter", "server_experimenter", "reflection"],
}

# Suggestion templates per category — much more specific than a generic "consider prompt enhancement"
CATEGORY_SUGGESTIONS: dict[str, str] = {
    "system": "检查 SSH 连接/GPU 资源/超时设置。实验前先验证环境可用性。",
    "experiment": "加强实验设计：在公认 benchmark 上评估、确保有 baseline 对比、做 ablation study。",
    "writing": "改进论文写作：注意章节间一致性、notation 统一、避免冗余。",
    "analysis": "深化分析：不要 cherry-pick 结果、补充 ablation 和 baseline 对比、讨论局限性。",
    "planning": "细化实验计划：明确资源需求、拆分子任务、预估 GPU 时间。",
    "pipeline": "优化流程：检查阶段顺序、减少冗余步骤。",
    "ideation": "提升想法质量：强调创新性、与 related work 区分、明确贡献。",
    "efficiency": "优化资源利用：减少 GPU 空闲时间、合理安排任务并行度、优化 batch size、加速迭代周期。",
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
    effectiveness: str = "unverified"  # effective / ineffective / unverified
    effectiveness_delta: float = 0.0  # score change after lesson was introduced


@dataclass
class OutcomeRecord:
    project: str
    stage: str
    issues: list[str]
    score: float
    notes: str
    timestamp: str = ""
    classified_issues: list[dict] = field(default_factory=list)
    success_patterns: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.classified_issues and self.issues:
            self.classified_issues = [
                {"description": issue, "category": IssueCategory.classify(issue).value}
                for issue in self.issues
            ]


# Keywords per category for matching success patterns to digest entries
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "system": ["ssh", "gpu", "timeout", "connection", "server"],
    "experiment": ["experiment", "baseline", "benchmark", "ablation", "training"],
    "writing": ["writing", "paper", "section", "clarity", "notation"],
    "analysis": ["analysis", "comparison", "result", "evidence"],
    "planning": ["plan", "scope", "resource", "timeline"],
    "pipeline": ["stage", "pipeline", "workflow", "step"],
    "ideation": ["idea", "novel", "contribution", "innovation"],
}


@dataclass
class DigestEntry:
    """Aggregated summary of a recurring pattern across all outcomes."""
    category: str
    pattern_summary: str
    total_occurrences: int
    weighted_frequency: float
    avg_score_when_seen: float
    affected_agents: list[str] = field(default_factory=list)
    effectiveness: str = "unverified"
    effectiveness_delta: float = 0.0
    success_patterns: list[str] = field(default_factory=list)
    last_updated: str = ""


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
        self.digest_path = self.EVOLUTION_DIR / "digest.json"


    def record_outcome(self, project: str, stage: str,
                       issues: list[str], score: float, notes: str = "",
                       classified_issues: list[dict] | None = None,
                       success_patterns: list[str] | None = None):
        """Record the outcome of a pipeline stage.

        If classified_issues is provided (from reflection agent's action_plan.json),
        use it directly. Otherwise auto-classify from issue descriptions.
        """
        record = OutcomeRecord(
            project=project, stage=stage, issues=issues,
            score=score, notes=notes,
            classified_issues=classified_issues or [],
            success_patterns=success_patterns or [],
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

    def build_digest(self) -> list[DigestEntry]:
        """Build aggregated digest from raw outcomes. Cached via file mtime."""
        outcomes = self._load_outcomes()
        if not outcomes:
            return []

        # Check cache freshness
        if self.digest_path.exists() and self.outcomes_path.exists():
            if os.path.getmtime(self.digest_path) >= os.path.getmtime(self.outcomes_path):
                try:
                    data = json.loads(self.digest_path.read_text(encoding="utf-8"))
                    return [DigestEntry(**d) for d in data]
                except (json.JSONDecodeError, TypeError):
                    pass

        # Aggregate by (category, pattern)
        groups: dict[str, dict] = {}
        all_success: list[str] = []
        for outcome in outcomes:
            weight = _time_weight(outcome.get("timestamp", ""))
            all_success.extend(outcome.get("success_patterns", []))
            classified = outcome.get("classified_issues", [])
            if not classified:
                classified = [
                    {"description": i, "category": IssueCategory.classify(i).value}
                    for i in outcome.get("issues", [])
                ]
            for ci in classified:
                key = ci["description"].lower().strip()
                if not key:
                    continue
                if key not in groups:
                    groups[key] = {
                        "category": ci.get("category", "analysis"),
                        "count": 0, "weighted": 0.0,
                        "scores": [], "timestamps": [],
                    }
                groups[key]["count"] += 1
                groups[key]["weighted"] += weight
                groups[key]["scores"].append(outcome["score"])
                groups[key]["timestamps"].append(outcome.get("timestamp", ""))

        # Build digest entries with effectiveness tracking
        entries = []
        for pattern, data in groups.items():
            category = data["category"]
            agents = CATEGORY_TO_AGENTS.get(category, ["reflection"])

            # Effectiveness: compare early vs late scores (need >= 4 occurrences)
            effectiveness = "unverified"
            eff_delta = 0.0
            scores = data["scores"]
            if len(scores) >= 4:
                mid = len(scores) // 2
                early_avg = sum(scores[:mid]) / mid
                late_avg = sum(scores[mid:]) / (len(scores) - mid)
                eff_delta = round(late_avg - early_avg, 2)
                if eff_delta > 0.5:
                    effectiveness = "effective"
                elif eff_delta < -0.5:
                    effectiveness = "ineffective"

            entries.append(DigestEntry(
                category=category,
                pattern_summary=pattern,
                total_occurrences=data["count"],
                weighted_frequency=round(data["weighted"], 2),
                avg_score_when_seen=round(sum(scores) / len(scores), 2),
                affected_agents=agents,
                effectiveness=effectiveness,
                effectiveness_delta=eff_delta,
                last_updated=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ))

        # Aggregate success patterns (deduplicate, count)
        success_counts: dict[str, int] = {}
        for sp in all_success:
            key = sp.strip()
            if key:
                success_counts[key] = success_counts.get(key, 0) + 1
        # Attach top success patterns to relevant digest entries by category
        for entry in entries:
            cat_successes = [
                s for s in success_counts
                if any(kw in s.lower() for kw in _CATEGORY_KEYWORDS.get(entry.category, []))
            ]
            entry.success_patterns = sorted(
                cat_successes, key=lambda s: -success_counts[s]
            )[:3]

        # Save digest
        self.digest_path.write_text(
            json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return entries

    def analyze_patterns(self) -> list[EvolutionInsight]:
        """Analyze recorded outcomes for recurring patterns with time decay and effectiveness."""
        digest = self.build_digest()
        if not digest:
            return []

        insights = []
        for entry in digest:
            # Require raw count >= 2 AND weighted frequency >= 1.0
            if entry.total_occurrences >= 2 and entry.weighted_frequency >= 1.0:
                severity = "high" if entry.weighted_frequency >= 2.5 else "medium"
                suggestion = CATEGORY_SUGGESTIONS.get(entry.category, "检查并改进相关环节。")

                # Deprioritize ineffective lessons
                adjusted_weight = entry.weighted_frequency
                if entry.effectiveness == "ineffective":
                    adjusted_weight *= 0.3

                insights.append(EvolutionInsight(
                    pattern=entry.pattern_summary,
                    frequency=entry.total_occurrences,
                    severity=severity,
                    suggestion=suggestion,
                    affected_agents=entry.affected_agents,
                    category=entry.category,
                    weighted_frequency=round(adjusted_weight, 2),
                    effectiveness=entry.effectiveness,
                    effectiveness_delta=entry.effectiveness_delta,
                ))

        self._save_insights(insights)
        return insights

    def filter_relevant_lessons(self, agent_name: str, topic: str = "",
                                stage: str = "", recent_issues: list[str] | None = None,
                                max_lessons: int = 8) -> str:
        """Generate a filtered, relevance-ranked overlay for a specific agent and context.

        Returns formatted markdown string ready for prompt injection.
        """
        digest = self.build_digest()
        if not digest:
            return ""

        # Filter to entries relevant to this agent
        relevant = [e for e in digest if agent_name in e.affected_agents]
        if not relevant:
            return ""

        # Stage → typical categories mapping
        stage_categories = {
            "experiment": ["experiment", "system"],
            "writing": ["writing"],
            "review": ["analysis", "writing"],
            "reflection": ["analysis", "pipeline"],
            "idea_debate": ["ideation"],
            "plan": ["planning", "experiment"],
        }
        topic_lower = topic.lower()
        recent_lower = [i.lower() for i in (recent_issues or [])]

        def relevance_score(entry: DigestEntry) -> float:
            score = 0.0
            # Category matches stage
            if stage in stage_categories:
                if entry.category in stage_categories[stage]:
                    score += 3.0
            # Keyword overlap with topic
            if topic_lower:
                words = entry.pattern_summary.lower().split()
                overlap = sum(1 for w in words if w in topic_lower)
                score += min(overlap, 2)
            # Overlap with recent issues
            for ri in recent_lower:
                if entry.pattern_summary.lower() in ri or ri in entry.pattern_summary.lower():
                    score += 3.0
            # Effectiveness bonus/penalty
            if entry.effectiveness == "effective":
                score += 1.0
            elif entry.effectiveness == "ineffective":
                score -= 2.0
            # Weighted frequency bonus
            score += min(entry.weighted_frequency / 3.0, 2.0)
            return score

        # Sort by relevance, take top N
        relevant.sort(key=lambda e: -relevance_score(e))
        top = relevant[:max_lessons]

        if not top:
            return ""

        # Format: issues section + success section
        lines = [
            "# 经验教训 (上下文过滤)",
            "",
            "## 需要注意",
        ]
        for entry in top:
            eff_tag = f"[{entry.effectiveness}]" if entry.effectiveness != "unverified" else ""
            lines.append(
                f"- [{entry.category.upper()}]{eff_tag} {entry.pattern_summary} "
                f"(出现 {entry.total_occurrences} 次, 权重 {entry.weighted_frequency})"
            )
            lines.append(f"  建议: {CATEGORY_SUGGESTIONS.get(entry.category, '检查并改进。')}")

        # Collect success patterns from these entries
        all_successes = []
        for entry in top:
            all_successes.extend(entry.success_patterns)
        # Also collect from all outcomes for this agent's categories
        outcomes = self._load_outcomes()
        for o in outcomes:
            for sp in o.get("success_patterns", []):
                if sp not in all_successes:
                    all_successes.append(sp)
        unique_successes = list(dict.fromkeys(all_successes))[:5]

        if unique_successes:
            lines.append("")
            lines.append("## 继续保持")
            for sp in unique_successes:
                lines.append(f"- {sp}")

        return "\n".join(lines) + "\n"

    def generate_lessons_overlay(self) -> dict[str, str]:
        """Generate per-agent overlay files from accumulated insights.

        Routes lessons to actual agent prompt names via CATEGORY_TO_AGENTS mapping.
        Includes effectiveness labels and success patterns.
        Returns dict mapping agent_name -> overlay content written.
        """
        insights = self.analyze_patterns()
        if not insights:
            return {}

        # Collect success patterns from all outcomes
        outcomes = self._load_outcomes()
        all_success: dict[str, int] = {}
        for o in outcomes:
            for sp in o.get("success_patterns", []):
                key = sp.strip()
                if key:
                    all_success[key] = all_success.get(key, 0) + 1

        # Group insights by affected agent
        agent_insights: dict[str, list[EvolutionInsight]] = {}
        for insight in insights:
            for agent in insight.affected_agents:
                agent_insights.setdefault(agent, []).append(insight)

        lessons_dir = self.EVOLUTION_DIR / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)

        written = {}
        for agent_name, insights_list in agent_insights.items():
            # Sort: effective first, then by severity, then by weighted frequency
            # Ineffective lessons go to the bottom
            insights_list.sort(
                key=lambda i: (
                    2 if i.effectiveness == "ineffective" else (0 if i.effectiveness == "effective" else 1),
                    0 if i.severity == "high" else 1,
                    -i.weighted_frequency,
                )
            )
            lines = [
                "# 经验教训 (自动生成)",
                "",
                "以下是从历史项目中自动提炼的经验教训。请在执行任务时注意避免这些问题。",
                "",
                "## 需要注意",
            ]
            for ins in insights_list[:10]:  # cap at 10 lessons per agent
                sev = ins.severity.upper()
                cat = ins.category.upper() if ins.category else "ANALYSIS"
                eff = f"[{ins.effectiveness}]" if ins.effectiveness != "unverified" else ""
                lines.append(
                    f"- [{sev}][{cat}]{eff} {ins.pattern} "
                    f"(出现 {ins.frequency} 次, 权重 {ins.weighted_frequency})"
                )
                lines.append(f"  建议: {ins.suggestion}")

            # Add success patterns section
            # Find successes relevant to this agent's categories
            agent_cats = set()
            for ins in insights_list:
                if ins.category:
                    agent_cats.add(ins.category)
            relevant_successes = sorted(
                all_success.keys(),
                key=lambda s: -all_success[s]
            )[:5]
            if relevant_successes:
                lines.append("")
                lines.append("## 继续保持")
                for sp in relevant_successes:
                    lines.append(f"- {sp} (出现 {all_success[sp]} 次)")

            content = "\n".join(lines) + "\n"
            overlay_path = lessons_dir / f"{agent_name}.md"
            overlay_path.write_text(content, encoding="utf-8")
            written[agent_name] = content

        return written

    def get_self_check_diagnostics(self, project: str) -> dict | None:
        """Auto-evaluate system health after each iteration.

        Checks for: declining quality trend, recurring system errors,
        ineffective lessons that keep appearing.
        Returns diagnostic dict if issues found, None if all clear.
        """
        outcomes = self._load_outcomes()
        project_outcomes = [o for o in outcomes if o["project"] == project]

        if len(project_outcomes) < 2:
            return None

        diagnostics: dict = {}

        # 1. Declining quality trend (last 3 scores all declining)
        recent_scores = [o["score"] for o in project_outcomes[-3:]]
        if len(recent_scores) >= 3:
            if recent_scores[0] > recent_scores[1] > recent_scores[2]:
                diagnostics["declining_trend"] = True
                diagnostics["recent_scores"] = recent_scores

        # 2. Recurring system errors (same issue 3+ times in last 5 outcomes)
        last_5 = project_outcomes[-5:]
        system_issues: dict[str, int] = {}
        for o in last_5:
            for ci in o.get("classified_issues", []):
                if ci.get("category") == "system":
                    key = ci["description"].lower().strip()
                    system_issues[key] = system_issues.get(key, 0) + 1
        recurring = {k: v for k, v in system_issues.items() if v >= 3}
        if recurring:
            diagnostics["recurring_errors"] = list(recurring.keys())

        # 3. Ineffective lessons (from digest)
        digest = self.build_digest()
        ineffective = [
            d.pattern_summary for d in digest
            if d.effectiveness == "ineffective" and d.total_occurrences >= 4
        ]
        if ineffective:
            diagnostics["ineffective_lessons"] = ineffective

        if not diagnostics:
            return None

        # Generate recommendation
        parts = []
        if diagnostics.get("declining_trend"):
            parts.append("质量持续下降，建议检查实验设计和写作策略")
        if diagnostics.get("recurring_errors"):
            parts.append(f"系统错误反复出现: {', '.join(diagnostics['recurring_errors'][:3])}")
        if diagnostics.get("ineffective_lessons"):
            parts.append(f"以下教训未见效果，考虑调整策略: {', '.join(diagnostics['ineffective_lessons'][:3])}")
        diagnostics["recommendation"] = "；".join(parts)

        return diagnostics

    def run_cross_project_evolution(self) -> dict[str, str]:
        """Analyze all project outcomes and regenerate global lessons overlay.

        Triggered manually via `sibyl evolve --apply` or `/sibyl-research:evolve`.
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
                    eff_tag = f" [{ins.effectiveness}]" if ins.effectiveness != "unverified" else ""
                    summary_lines.append(
                        f"- [{ins.severity.upper()}]{eff_tag} {ins.pattern} "
                        f"(出现 {ins.frequency} 次, 权重 {ins.weighted_frequency})"
                    )
                    summary_lines.append(f"  建议: {ins.suggestion}")

            # Add global success patterns
            outcomes = self._load_outcomes()
            all_success: dict[str, int] = {}
            for o in outcomes:
                for sp in o.get("success_patterns", []):
                    key = sp.strip()
                    if key:
                        all_success[key] = all_success.get(key, 0) + 1
            if all_success:
                summary_lines.append("\n## 成功模式 (继续保持)\n")
                for sp, count in sorted(all_success.items(), key=lambda x: -x[1])[:10]:
                    summary_lines.append(f"- {sp} (出现 {count} 次)")

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
