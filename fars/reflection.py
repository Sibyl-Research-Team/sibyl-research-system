"""Reflection and iteration logging for the FARS pipeline.

Handles:
- Post-stage reflection
- Iteration logging
- Experience consolidation
- Style learning from reference papers
"""
import json
import time
from pathlib import Path


class IterationLogger:
    """Logs each iteration of the pipeline with improvements and issues."""

    def __init__(self, workspace_root: Path):
        self.log_dir = workspace_root / "logs" / "iterations"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_iteration(self, iteration: int, stage: str, changes: list[str],
                      issues_found: list[str], issues_fixed: list[str],
                      quality_score: float, notes: str = ""):
        entry = {
            "iteration": iteration,
            "stage": stage,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "changes": changes,
            "issues_found": issues_found,
            "issues_fixed": issues_fixed,
            "quality_score": quality_score,
            "notes": notes,
        }

        log_file = self.log_dir / f"iter_{iteration:03d}_{stage}.json"
        log_file.write_text(json.dumps(entry, indent=2, ensure_ascii=False))

        # Append to master log
        master_log = self.log_dir / "master_log.jsonl"
        with open(master_log, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    def get_history(self) -> list[dict]:
        master_log = self.log_dir / "master_log.jsonl"
        if not master_log.exists():
            return []
        entries = []
        for line in master_log.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def get_latest_score(self, stage: str) -> float | None:
        history = self.get_history()
        for entry in reversed(history):
            if entry["stage"] == stage:
                return entry["quality_score"]
        return None


class ReflectionEngine:
    """Generates reflection prompts and consolidates learnings."""

    @staticmethod
    def build_reflection_prompt(stage: str, output_summary: str,
                                 supervisor_review: str, critic_feedback: str,
                                 previous_iterations: list[dict]) -> str:
        history_summary = ""
        if previous_iterations:
            history_summary = "\n\nPrevious iteration history:\n"
            for entry in previous_iterations[-3:]:  # last 3 iterations
                history_summary += (
                    f"- Iter {entry['iteration']} ({entry['stage']}): "
                    f"Score={entry['quality_score']}, "
                    f"Fixed: {', '.join(entry['issues_fixed'][:3])}\n"
                )

        return f"""Reflect on the {stage} stage output and reviews:

## Stage Output Summary
{output_summary}

## Supervisor Review
{supervisor_review}

## Critic Feedback
{critic_feedback}
{history_summary}

Based on the above, provide:
1. **Key Issues to Fix**: Prioritized list of problems to address
2. **What Went Well**: Practices to keep and consolidate
3. **Action Plan**: Specific steps for the next iteration
4. **Process Improvements**: Suggestions for improving the pipeline itself
5. **Quality Trajectory**: Is quality improving? What's the trend?

Write your reflection to:
- reflection/reflection_{stage}.md
- reflection/action_plan_{stage}.json
"""

    @staticmethod
    def build_style_learning_prompt(reference_papers: list[str]) -> str:
        papers_text = "\n\n---\n\n".join(reference_papers[:3])
        return f"""Analyze the writing style, structure, and logic of these reference papers:

{papers_text}

Extract and summarize:
1. **Document Structure**: How sections are organized, what's included/excluded
2. **Writing Style**: Sentence patterns, vocabulary level, formality, hedging language
3. **Argument Flow**: How claims are built up, evidence presentation order
4. **Experiment Design Patterns**: How experiments are structured and presented
5. **Figure/Table Conventions**: How results are visualized
6. **Citation Patterns**: How related work is discussed and cited

Write a style guide to: writing/style_guide.md
This guide will be used by the writing agent to match the quality and style of top papers."""
