"""Auto-evolution system for Sibyl v4.

Learns from cross-project experience to improve prompts and workflows.
"""
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path

from sibyl._paths import SYSTEM_EVOLUTION_DIR, get_system_evolution_dir


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


_VALID_ISSUE_CATEGORIES = {member.value for member in IssueCategory}
_CATEGORY_ALIASES = {
    "research": "analysis",
    "results": "analysis",
    "evaluation": "analysis",
    "method": "experiment",
    "methods": "experiment",
    "methodology": "experiment",
    "execution": "pipeline",
    "workflow": "pipeline",
    "orchestration": "pipeline",
    "compute": "efficiency",
    "resource": "efficiency",
    "resources": "efficiency",
    "paper": "writing",
    "presentation": "writing",
}
_SEVERITY_ALIASES = {
    "critical": "high",
    "blocker": "high",
    "severe": "high",
    "urgent": "high",
    "moderate": "medium",
    "normal": "medium",
    "minor": "low",
    "trivial": "low",
    "nit": "low",
}
_STATUS_ALIASES = {
    "open": "new",
    "ongoing": "recurring",
    "persistent": "recurring",
    "repeat": "recurring",
    "repeated": "recurring",
    "resolved": "fixed",
    "done": "fixed",
    "closed": "fixed",
}
_QUALITY_TRAJECTORY_ALIASES = {
    "divergent": "stagnant",
    "mixed": "stagnant",
    "volatile": "stagnant",
    "oscillating": "stagnant",
    "worsening": "declining",
    "improve": "improving",
}


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_text(value)
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def normalize_issue_category(
    category: object,
    description: str = "",
    suggestion: str = "",
) -> str:
    raw = (
        _normalize_text(category)
        .lower()
        .replace("/", " ")
        .replace("_", " ")
    )
    if raw in _VALID_ISSUE_CATEGORIES:
        return raw
    if raw in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[raw]
    for token in raw.split():
        if token in _VALID_ISSUE_CATEGORIES:
            return token
        if token in _CATEGORY_ALIASES:
            return _CATEGORY_ALIASES[token]
    fallback = " ".join(part for part in (description, suggestion, raw) if part)
    return IssueCategory.classify(fallback).value


def normalize_issue_severity(severity: object) -> str:
    raw = _normalize_text(severity).lower()
    if raw in {"high", "medium", "low"}:
        return raw
    if raw in _SEVERITY_ALIASES:
        return _SEVERITY_ALIASES[raw]
    return "medium"


def normalize_issue_status(status: object) -> str:
    raw = _normalize_text(status).lower()
    if raw in {"new", "recurring", "fixed"}:
        return raw
    if raw in _STATUS_ALIASES:
        return _STATUS_ALIASES[raw]
    return "new"


def normalize_quality_trajectory(trajectory: object) -> str:
    raw = _normalize_text(trajectory).lower()
    if raw in {"improving", "declining", "stagnant"}:
        return raw
    if raw in _QUALITY_TRAJECTORY_ALIASES:
        return _QUALITY_TRAJECTORY_ALIASES[raw]
    return "stagnant"


def build_issue_key(description: str, category: str = "") -> str:
    category_value = normalize_issue_category(category, description=description)
    normalized = _normalize_text(description).lower()
    normalized = re.sub(r"\biter(?:ation)?\s*\d+\b", " ", normalized)
    normalized = re.sub(r"\b[ntmk]\s*=\s*\d+(?:\.\d+)?\b", " ", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?(?:pp|%|x|h|min|hours?)?\b", " ", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    preview = "-".join(normalized.split()[:8])[:72] or "issue"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12] if normalized else "empty"
    return f"{category_value}:{preview}:{digest}"


def normalize_issue_entry(issue: dict | str) -> dict | None:
    if isinstance(issue, str):
        issue = {"description": issue}
    if not isinstance(issue, dict):
        return None

    description = _normalize_text(issue.get("description"))
    if not description:
        return None

    suggestion = _normalize_text(issue.get("suggestion"))
    category = normalize_issue_category(
        issue.get("category"),
        description=description,
        suggestion=suggestion,
    )
    normalized = dict(issue)
    normalized["description"] = description
    normalized["category"] = category
    normalized["severity"] = normalize_issue_severity(issue.get("severity"))
    normalized["status"] = normalize_issue_status(issue.get("status"))
    normalized["suggestion"] = suggestion
    normalized["issue_key"] = (
        _normalize_text(issue.get("issue_key")) or build_issue_key(description, category)
    )
    if "requires_system_change" in issue:
        normalized["requires_system_change"] = bool(issue.get("requires_system_change"))
    return normalized


def normalize_action_plan(action_plan: dict | None) -> dict:
    if not isinstance(action_plan, dict):
        return {}

    normalized = dict(action_plan)
    issues: list[dict] = []
    for issue in action_plan.get("issues_classified", []):
        normalized_issue = normalize_issue_entry(issue)
        if normalized_issue is not None:
            issues.append(normalized_issue)
    normalized["issues_classified"] = issues
    normalized["issues_fixed"] = _normalize_string_list(action_plan.get("issues_fixed", []))
    normalized["success_patterns"] = _normalize_string_list(action_plan.get("success_patterns", []))
    normalized["systemic_patterns"] = _normalize_string_list(action_plan.get("systemic_patterns", []))
    normalized["recommended_focus"] = _normalize_string_list(action_plan.get("recommended_focus", []))
    normalized["quality_trajectory"] = normalize_quality_trajectory(
        action_plan.get("quality_trajectory")
    )

    efficiency = action_plan.get("efficiency_analysis")
    if isinstance(efficiency, dict):
        normalized_efficiency = dict(efficiency)
        utilization = efficiency.get("gpu_utilization_pct")
        if isinstance(utilization, (int, float)):
            normalized_efficiency["gpu_utilization_pct"] = max(0, min(int(utilization), 100))
        idle_minutes = efficiency.get("total_gpu_idle_minutes")
        if isinstance(idle_minutes, (int, float)):
            normalized_efficiency["total_gpu_idle_minutes"] = max(float(idle_minutes), 0.0)
        normalized_efficiency["bottleneck_stages"] = _normalize_string_list(
            efficiency.get("bottleneck_stages", [])
        )
        normalized_efficiency["suggestions"] = _normalize_string_list(
            efficiency.get("suggestions", [])
        )
        normalized["efficiency_analysis"] = normalized_efficiency

    return normalized


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
        normalized_issues: list[dict] = []
        for issue in self.classified_issues:
            normalized_issue = normalize_issue_entry(issue)
            if normalized_issue is not None and normalized_issue.get("status") != "fixed":
                normalized_issues.append(normalized_issue)
        self.classified_issues = normalized_issues
        self.success_patterns = _normalize_string_list(self.success_patterns)


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


def _is_synthetic_test_record(record: dict) -> bool:
    """Ignore legacy empty test records in the shared evolution ledger."""
    return (
        record.get("project") == "test-proj"
        and not record.get("issues")
        and not record.get("classified_issues")
        and not record.get("success_patterns")
    )


class EvolutionEngine:
    """Cross-project experience learning and prompt improvement."""

    EVOLUTION_DIR = SYSTEM_EVOLUTION_DIR

    def __init__(self):
        evolution_dir = get_system_evolution_dir()
        if type(self).EVOLUTION_DIR != SYSTEM_EVOLUTION_DIR:
            evolution_dir = Path(type(self).EVOLUTION_DIR)
        self.EVOLUTION_DIR = evolution_dir
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
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if self.EVOLUTION_DIR == SYSTEM_EVOLUTION_DIR and _is_synthetic_test_record(record):
                    continue
                normalized_issues: list[dict] = []
                for issue in record.get("classified_issues", []):
                    normalized_issue = normalize_issue_entry(issue)
                    if normalized_issue is not None and normalized_issue.get("status") != "fixed":
                        normalized_issues.append(normalized_issue)
                record["classified_issues"] = normalized_issues
                if not record["classified_issues"] and record.get("issues"):
                    record["classified_issues"] = []
                    for issue in record.get("issues", []):
                        normalized_issue = normalize_issue_entry(
                            {
                                "description": issue,
                                "category": IssueCategory.classify(issue).value,
                            }
                        )
                        if normalized_issue is not None:
                            record["classified_issues"].append(normalized_issue)
                record["success_patterns"] = _normalize_string_list(
                    record.get("success_patterns", [])
                )
                records.append(record)
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

        # Aggregate by normalized issue key to reduce fragmentation when
        # descriptions drift slightly across iterations.
        groups: dict[str, dict] = {}
        all_success: list[str] = []
        for outcome in outcomes:
            weight = _time_weight(outcome.get("timestamp", ""))
            all_success.extend(outcome.get("success_patterns", []))
            classified = outcome.get("classified_issues", [])
            if not classified:
                classified = [
                    normalize_issue_entry(
                        {"description": i, "category": IssueCategory.classify(i).value}
                    )
                    for i in outcome.get("issues", [])
                ]
            for ci in classified:
                if ci is None or ci.get("status") == "fixed":
                    continue
                key = ci.get("issue_key") or build_issue_key(
                    ci.get("description", ""),
                    ci.get("category", ""),
                )
                if not key:
                    continue
                if key not in groups:
                    groups[key] = {
                        "category": ci.get("category", "analysis"),
                        "pattern_summary": ci.get("description", ""),
                        "count": 0, "weighted": 0.0,
                        "scores": [], "timestamps": [],
                    }
                elif ci.get("description") and (
                    not groups[key]["pattern_summary"]
                    or len(ci["description"]) < len(groups[key]["pattern_summary"])
                ):
                    groups[key]["pattern_summary"] = ci["description"]
                groups[key]["count"] += 1
                groups[key]["weighted"] += weight
                groups[key]["scores"].append(outcome["score"])
                groups[key]["timestamps"].append(outcome.get("timestamp", ""))

        # Keep effectiveness conservative until we have explicit causal signals.
        entries = []
        for _, data in groups.items():
            category = data["category"]
            agents = CATEGORY_TO_AGENTS.get(category, ["reflection"])
            scores = data["scores"]

            entries.append(DigestEntry(
                category=category,
                pattern_summary=data["pattern_summary"] or "issue",
                total_occurrences=data["count"],
                weighted_frequency=round(data["weighted"], 2),
                avg_score_when_seen=round(sum(scores) / len(scores), 2),
                affected_agents=agents,
                effectiveness="unverified",
                effectiveness_delta=0.0,
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
        stage_lower = stage.lower()
        if stage_lower in stage_categories:
            stage_targets = stage_categories[stage_lower]
        elif stage_lower.startswith("writing"):
            stage_targets = ["writing"]
        elif "experiment" in stage_lower:
            stage_targets = ["experiment", "system", "efficiency"]
        elif stage_lower.startswith("review"):
            stage_targets = ["analysis", "writing"]
        elif stage_lower in {"planning", "quality_gate"}:
            stage_targets = ["planning", "analysis", "efficiency"]
        elif "idea" in stage_lower:
            stage_targets = ["ideation", "analysis"]
        else:
            stage_targets = []
        topic_lower = topic.lower()
        recent_lower = [i.lower() for i in (recent_issues or [])]

        def relevance_score(entry: DigestEntry) -> float:
            score = 0.0
            # Category matches stage
            if stage_targets and entry.category in stage_targets:
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
            self.reset_overlays()
            return {}

        digest = self.build_digest()
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
        desired_agents = set(agent_insights)
        for stale_path in lessons_dir.glob("*.md"):
            if stale_path.stem not in desired_agents:
                stale_path.unlink()

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

            # Add success patterns section filtered to the agent's categories.
            agent_cats = set()
            for ins in insights_list:
                if ins.category:
                    agent_cats.add(ins.category)
            relevant_successes: set[str] = set()
            for entry in digest:
                if entry.category not in agent_cats:
                    continue
                for success_pattern in entry.success_patterns:
                    relevant_successes.add(success_pattern)
            relevant_success_counts: dict[str, int] = {
                success_pattern: all_success.get(success_pattern, 1)
                for success_pattern in relevant_successes
            }
            if not relevant_success_counts and agent_cats:
                agent_keywords = {
                    keyword
                    for category in agent_cats
                    for keyword in _CATEGORY_KEYWORDS.get(category, [])
                }
                for success_pattern, count in all_success.items():
                    success_lower = success_pattern.lower()
                    if any(keyword in success_lower for keyword in agent_keywords):
                        relevant_success_counts[success_pattern] = count
            relevant_successes = sorted(
                relevant_success_counts.keys(),
                key=lambda s: (-relevant_success_counts[s], s),
            )[:5]
            if relevant_successes:
                lines.append("")
                lines.append("## 继续保持")
                for sp in relevant_successes:
                    lines.append(f"- {sp} (出现 {relevant_success_counts[sp]} 次)")

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
        recurring_labels: dict[str, str] = {}
        for o in last_5:
            for ci in o.get("classified_issues", []):
                if ci.get("category") == "system":
                    key = ci.get("issue_key") or build_issue_key(
                        ci.get("description", ""),
                        "system",
                    )
                    system_issues[key] = system_issues.get(key, 0) + 1
                    recurring_labels.setdefault(key, ci.get("description", ""))
        recurring = {k: v for k, v in system_issues.items() if v >= 3}
        if recurring:
            diagnostics["recurring_errors"] = [
                recurring_labels.get(key, key)
                for key in recurring
            ]

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
