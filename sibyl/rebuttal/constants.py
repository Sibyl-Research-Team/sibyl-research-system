"""Rebuttal subsystem constants."""

REBUTTAL_STAGES = [
    "init",
    "parse_reviews",        # Decompose reviews into atomic concerns
    "strategy",             # Strategist prioritizes concerns + plans approach
    "rebuttal_draft",       # Team action: 8 roles draft responses
    "simulated_review",     # N simulated reviewers attack the rebuttal
    "codex_review",         # Optional: Codex independent review
    "score_evaluate",       # Evaluate scores, decide iterate or finalize
    # score_evaluate loops back to rebuttal_draft if needed
    "final_synthesis",      # Final polish with word limit enforcement
    "done",
]

REBUTTAL_CHECKPOINT_DIRS = {
    "rebuttal_draft": "rounds/current/team",
    "simulated_review": "rounds/current/sim_review",
}

REBUTTAL_TEAM_ROLES = [
    "rebuttal_strategist",
    "rebuttal_scholar",
    "rebuttal_theorist",
    "rebuttal_experimentalist",
    "rebuttal_writer",
    "rebuttal_advocate",
    "rebuttal_diplomat",
    "rebuttal_checker",
]

REBUTTAL_AGENT_TIERS = {
    # Heavy: deep reasoning for synthesis, strategy
    "rebuttal_synthesizer": "heavy",
    "rebuttal_strategist": "heavy",
    # Standard: substantive reasoning
    "rebuttal_scholar": "standard",
    "rebuttal_theorist": "standard",
    "rebuttal_experimentalist": "standard",
    "rebuttal_writer": "standard",
    "simulated_reviewer": "standard",
    # Light: supporting roles
    "rebuttal_advocate": "light",
    "rebuttal_diplomat": "light",
    "rebuttal_checker": "light",
}
