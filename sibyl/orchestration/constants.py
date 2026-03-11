"""Shared orchestration constants."""

RUNTIME_GITIGNORE_LINES = (
    "*.pyc",
    "__pycache__/",
    ".DS_Store",
    ".venv/",
    "CLAUDE.md",
    ".claude/agents",
    ".claude/skills",
    ".claude/settings.local.json",
    ".sibyl/system.json",
)

PAPER_SECTIONS = [
    ("intro", "Introduction"),
    ("related_work", "Related Work"),
    ("method", "Method"),
    ("experiments", "Experiments"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
]

CHECKPOINT_DIRS = {
    "idea_debate": "idea",
    "result_debate": "idea/result_debate",
    "writing_sections": "writing/sections",
    "writing_critique": "writing/critique",
}

PIPELINE_STAGES = [
    "init",
    "literature_search",
    "idea_debate",
    "planning",
    "pilot_experiments",
    "idea_validation_decision",
    "experiment_cycle",
    "result_debate",
    "experiment_decision",
    "writing_outline",
    "writing_sections",
    "writing_critique",
    "writing_integrate",
    "writing_final_review",
    "writing_latex",
    "review",
    "reflection",
    "quality_gate",
    "done",
]
