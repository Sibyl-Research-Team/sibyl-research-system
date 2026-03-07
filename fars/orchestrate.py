"""FARS orchestrator for Claude Code native mode.

This module provides a state-machine orchestrator that returns the next action
for the main Claude Code session to execute. It does NOT call claude-agent-sdk.

Usage (called by Skill via Bash):
    python -c "from fars.orchestrate import FarsOrchestrator; ..."
"""
import json
import re
import time
from pathlib import Path
from dataclasses import dataclass, asdict

from fars.config import Config
from fars.workspace import Workspace
from fars.context_builder import ContextBuilder
from fars.experiment_records import ExperimentDB

PAPER_SECTIONS = [
    ("intro", "Introduction"),
    ("related_work", "Related Work"),
    ("method", "Method"),
    ("experiments", "Experiments"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
]

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(agent_name: str) -> str:
    """Load an agent prompt from the prompts/ directory."""
    path = PROMPTS_DIR / f"{agent_name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_common_prompt() -> str:
    """Load the common instructions prompt."""
    return load_prompt("_common")


@dataclass
class AgentTask:
    """A task to be executed by a Claude Code Agent."""
    agent_name: str
    prompt: str
    description: str
    workspace_path: str


@dataclass
class Action:
    """An action for the main Claude Code session to execute."""
    action_type: str  # "agents_parallel", "agent_single", "bash", "done", "lark_sync"
    agents: list[dict] | None = None  # for agent actions
    bash_command: str | None = None  # for bash actions
    description: str = ""
    stage: str = ""


class FarsOrchestrator:
    """State-machine orchestrator for FARS research pipeline.

    Called by the FARS Skill, returns the next action for Claude Code to execute.
    """

    # Pipeline stages in order
    STAGES = [
        "init",
        "idea_debate_generate",
        "idea_debate_critique",
        "idea_debate_synthesize",
        "planning",
        "pilot_experiments",
        "experiment_cycle",
        "result_debate",
        "experiment_decision",
        "writing_outline",
        "writing_sections",
        "writing_critique",
        "writing_integrate",
        "writing_final_review",
        "critic_review",
        "supervisor_review",
        "reflection",
        "lark_sync",
        "quality_gate",
        "done",
    ]

    def __init__(self, workspace_path: str, config: Config | None = None):
        self.config = config or Config()
        self.ws = Workspace(
            self.config.workspaces_dir,
            Path(workspace_path).name,
        )
        self.workspace_path = str(self.ws.root)

    @classmethod
    def init_project(cls, topic: str, project_name: str | None = None,
                     config_path: str | None = None) -> dict:
        """Initialize a new research project. Returns project info."""
        config = Config.from_yaml(config_path) if config_path else Config()

        if project_name is None:
            project_name = cls._slugify(topic)

        ws = Workspace(config.workspaces_dir, project_name)

        # Save topic to status
        status = ws.get_status()
        ws.write_file("topic.txt", topic)
        ws.update_stage("init")

        return {
            "project_name": project_name,
            "workspace_path": str(ws.root),
            "topic": topic,
            "config": {
                "ssh_server": config.ssh_server,
                "remote_base": config.remote_base,
                "gpu_ids": config.gpu_ids,
                "pilot_samples": config.pilot_samples,
                "pilot_seeds": config.pilot_seeds,
                "full_seeds": config.full_seeds,
                "debate_rounds": config.debate_rounds,
                "idea_exp_cycles": config.idea_exp_cycles,
                "lark_enabled": config.lark_enabled,
            },
        }

    def get_next_action(self) -> dict:
        """Determine and return the next action based on current state."""
        status = self.ws.get_status()
        stage = status.stage
        topic = self.ws.read_file("topic.txt") or ""

        action = self._compute_action(stage, topic, status.iteration)
        return asdict(action)

    def record_result(self, stage: str, result: str = "",
                      score: float | None = None):
        """Record the result of a completed stage and advance state."""
        next_stage = self._get_next_stage(stage, result, score)
        self.ws.update_stage(next_stage)

        if score is not None:
            self.ws.write_file(
                f"logs/stage_{stage}_score.txt",
                f"{score}"
            )

    def get_status(self) -> dict:
        """Get current project status."""
        meta = self.ws.get_project_metadata()
        meta["topic"] = self.ws.read_file("topic.txt") or ""
        return meta

    def _compute_action(self, stage: str, topic: str, iteration: int) -> Action:
        """Compute the next action based on current stage."""
        ws = self.workspace_path
        common = load_common_prompt()

        if stage == "init":
            return self._action_idea_debate_generate(topic, ws, common)

        elif stage == "idea_debate_generate":
            return self._action_idea_debate_critique(ws, common)

        elif stage == "idea_debate_critique":
            return self._action_idea_debate_synthesize(topic, ws, common)

        elif stage == "idea_debate_synthesize":
            return self._action_planning(ws, common)

        elif stage == "planning":
            return self._action_pilot_experiments(ws, common)

        elif stage == "pilot_experiments":
            return self._action_experiment_cycle(ws, common, iteration)

        elif stage == "experiment_cycle":
            return self._action_result_debate(ws, common)

        elif stage == "result_debate":
            return self._action_experiment_decision(ws, common)

        elif stage == "experiment_decision":
            # Check if we should proceed to writing or cycle back
            decision = self.ws.read_file("supervisor/experiment_analysis.md") or ""
            if "DECISION: PIVOT" in decision.upper():
                cycle = self._get_current_cycle()
                if cycle < self.config.idea_exp_cycles:
                    return self._action_idea_debate_generate(topic, ws, common)
            return self._action_writing_outline(ws, common)

        elif stage == "writing_outline":
            return self._action_writing_sections(ws, common)

        elif stage == "writing_sections":
            return self._action_writing_critique(ws, common)

        elif stage == "writing_critique":
            return self._action_writing_integrate(ws, common)

        elif stage == "writing_integrate":
            return self._action_writing_final_review(ws, common)

        elif stage == "writing_final_review":
            review = self.ws.read_file("writing/review.md") or ""
            match = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", review)
            score = float(match.group(1)) if match else 5.0
            if score < 7.0:
                return self._action_writing_integrate(ws, common)
            return self._action_critic_review(ws, common)

        elif stage == "critic_review":
            return self._action_supervisor_review(ws, common)

        elif stage == "supervisor_review":
            return self._action_reflection(ws)

        elif stage == "reflection":
            if self.config.lark_enabled:
                return self._action_lark_sync(ws)
            return self._action_quality_gate()

        elif stage == "lark_sync":
            return self._action_quality_gate()

        elif stage == "quality_gate":
            return Action(action_type="done", description="Pipeline complete", stage="done")

        else:
            return Action(action_type="done", description="Unknown stage", stage="done")

    # ══════════════════════════════════════════════
    # Action builders
    # ══════════════════════════════════════════════

    def _action_idea_debate_generate(self, topic: str, ws: str, common: str) -> Action:
        """3 parallel agents generate ideas independently."""
        agents = []
        for role in ["innovator", "pragmatist", "theoretical"]:
            prompt_template = load_prompt(role)
            prompt = (
                f"{common}\n\n{prompt_template}\n\n"
                f"Topic: {topic}\n\n"
                f"Workspace path: {ws}\n\n"
                f"Write your output to {ws}/idea/perspectives/{role}.md"
            )
            agents.append({
                "name": role,
                "prompt": prompt,
                "description": f"{role} idea generation",
            })

        return Action(
            action_type="agents_parallel",
            agents=agents,
            description="3 parallel agents generating independent research ideas",
            stage="idea_debate_generate",
        )

    def _action_idea_debate_critique(self, ws: str, common: str) -> Action:
        """Cross-critique: each agent reviews others."""
        agents = []
        roles = ["innovator", "pragmatist", "theoretical"]

        for critic in roles:
            for author in roles:
                if critic == author:
                    continue
                prompt = (
                    f"{common}\n\n"
                    f"You are a {critic} researcher critically evaluating another's idea.\n"
                    f"Be constructive but thorough. Score 1-10.\n\n"
                    f"Read the idea from: {ws}/idea/perspectives/{author}.md\n"
                    f"Write your critique to: {ws}/idea/debate/{critic}_on_{author}.md\n\n"
                    f"Evaluate:\n"
                    f"1. Novelty: Is this truly new?\n"
                    f"2. Feasibility: Can this be implemented with limited compute?\n"
                    f"3. Impact: Would positive results be meaningful?\n"
                    f"4. Risks: Main failure modes?\n"
                    f"5. Suggestions: How to improve?"
                )
                agents.append({
                    "name": f"{critic}_critiques_{author}",
                    "prompt": prompt,
                    "description": f"{critic} critiques {author}",
                })

        return Action(
            action_type="agents_parallel",
            agents=agents,
            description="6 parallel cross-critique agents",
            stage="idea_debate_critique",
        )

    def _action_idea_debate_synthesize(self, topic: str, ws: str, common: str) -> Action:
        prompt_template = load_prompt("synthesizer")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Topic: {topic}\n"
            f"Workspace path: {ws}"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "synthesizer",
                "prompt": prompt,
                "description": "synthesize ideas into proposal",
            }],
            description="Synthesize ideas and critiques into final proposal",
            stage="idea_debate_synthesize",
        )

    def _action_planning(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("planner")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}\n"
            f"Pilot config: samples={self.config.pilot_samples}, "
            f"seeds={self.config.pilot_seeds}, timeout={self.config.pilot_timeout}s"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "planner",
                "prompt": prompt,
                "description": "design experiment plan",
            }],
            description="Design experiment plan with pilot/full configs",
            stage="planning",
        )

    def _action_pilot_experiments(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("experimenter")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"MODE: PILOT\n"
            f"Workspace path: {ws}\n"
            f"SSH server: {self.config.ssh_server}\n"
            f"Remote base: {self.config.remote_base}\n"
            f"GPU IDs: {self.config.gpu_ids}\n"
            f"Pilot samples: {self.config.pilot_samples}\n"
            f"Pilot seeds: {self.config.pilot_seeds}\n"
            f"Pilot timeout: {self.config.pilot_timeout}s\n\n"
            f"Run PILOT experiments only. Report GO/NO-GO for each task."
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "experimenter_pilot",
                "prompt": prompt,
                "description": "run pilot experiments",
            }],
            description="Run pilot experiments for quick validation",
            stage="pilot_experiments",
        )

    def _action_experiment_cycle(self, ws: str, common: str, iteration: int) -> Action:
        prompt_template = load_prompt("experimenter")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"MODE: FULL\n"
            f"Workspace path: {ws}\n"
            f"SSH server: {self.config.ssh_server}\n"
            f"Remote base: {self.config.remote_base}\n"
            f"GPU IDs: {self.config.gpu_ids}\n"
            f"Full seeds: {self.config.full_seeds}\n"
            f"Iteration: {iteration}\n\n"
            f"Run FULL experiments for tasks that passed pilot."
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "experimenter_full",
                "prompt": prompt,
                "description": "run full experiments",
            }],
            description="Run full experiments with statistical rigor",
            stage="experiment_cycle",
        )

    def _action_result_debate(self, ws: str, common: str) -> Action:
        agents = []
        for role in ["optimist", "skeptic", "strategist"]:
            prompt_template = load_prompt(role)
            prompt = (
                f"{common}\n\n{prompt_template}\n\n"
                f"Workspace path: {ws}"
            )
            agents.append({
                "name": role,
                "prompt": prompt,
                "description": f"{role} result analysis",
            })
        return Action(
            action_type="agents_parallel",
            agents=agents,
            description="3 parallel agents debate experiment results",
            stage="result_debate",
        )

    def _action_experiment_decision(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("supervisor")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}\n\n"
            f"SPECIAL TASK: Analyze experiment results and the debate opinions.\n"
            f"Read:\n"
            f"- {ws}/exp/results/summary.md\n"
            f"- {ws}/idea/result_debate/optimist.md\n"
            f"- {ws}/idea/result_debate/skeptic.md\n"
            f"- {ws}/idea/result_debate/strategist.md\n"
            f"- {ws}/idea/proposal.md\n\n"
            f"Determine: PIVOT or PROCEED?\n"
            f"Write to {ws}/supervisor/experiment_analysis.md\n"
            f"End with exactly: DECISION: PIVOT or DECISION: PROCEED"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "supervisor_decision",
                "prompt": prompt,
                "description": "decide pivot or proceed",
            }],
            description="Supervisor analyzes results and decides PIVOT or PROCEED",
            stage="experiment_decision",
        )

    def _action_writing_outline(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("outline_writer")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "outline_writer",
                "prompt": prompt,
                "description": "generate paper outline",
            }],
            description="Generate paper outline",
            stage="writing_outline",
        )

    def _action_writing_sections(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("section_writer")
        agents = []
        for section_id, section_name in PAPER_SECTIONS:
            prompt = (
                f"{common}\n\n{prompt_template}\n\n"
                f"Section: {section_name}\n"
                f"Section ID: {section_id}\n"
                f"Workspace path: {ws}\n"
                f"Write to: {ws}/writing/sections/{section_id}.md"
            )
            agents.append({
                "name": f"writer_{section_id}",
                "prompt": prompt,
                "description": f"write {section_name} section",
            })
        return Action(
            action_type="agents_parallel",
            agents=agents,
            description="6 parallel agents writing paper sections",
            stage="writing_sections",
        )

    def _action_writing_critique(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("section_critic")
        agents = []
        for section_id, section_name in PAPER_SECTIONS:
            prompt = (
                f"{common}\n\n{prompt_template}\n\n"
                f"Section: {section_name}\n"
                f"Section ID: {section_id}\n"
                f"Workspace path: {ws}\n"
                f"Read: {ws}/writing/sections/{section_id}.md\n"
                f"Write critique to: {ws}/writing/critique/{section_id}_critique.md"
            )
            agents.append({
                "name": f"critic_{section_id}",
                "prompt": prompt,
                "description": f"critique {section_name} section",
            })
        return Action(
            action_type="agents_parallel",
            agents=agents,
            description="6 parallel agents critiquing paper sections",
            stage="writing_critique",
        )

    def _action_writing_integrate(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("editor")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "editor",
                "prompt": prompt,
                "description": "integrate paper sections",
            }],
            description="Integrate all sections into coherent paper",
            stage="writing_integrate",
        )

    def _action_writing_final_review(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("final_critic")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "final_critic",
                "prompt": prompt,
                "description": "final paper review",
            }],
            description="Top-tier conference-level paper review",
            stage="writing_final_review",
        )

    def _action_critic_review(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("critic")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "critic",
                "prompt": prompt,
                "description": "comprehensive critic review",
            }],
            description="Harsh but fair academic critique of all outputs",
            stage="critic_review",
        )

    def _action_supervisor_review(self, ws: str, common: str) -> Action:
        prompt_template = load_prompt("supervisor")
        prompt = (
            f"{common}\n\n{prompt_template}\n\n"
            f"Workspace path: {ws}"
        )
        return Action(
            action_type="agent_single",
            agents=[{
                "name": "supervisor",
                "prompt": prompt,
                "description": "supervisor quality review",
            }],
            description="Independent supervisor review with quality scoring",
            stage="supervisor_review",
        )

    def _action_reflection(self, ws: str) -> Action:
        return Action(
            action_type="bash",
            bash_command=(
                f'python3 -c "'
                f"from fars.orchestrate import FarsOrchestrator; "
                f"o = FarsOrchestrator('{ws}'); "
                f'o.run_reflection()"'
            ),
            description="Run reflection and log iteration results",
            stage="reflection",
        )

    def _action_lark_sync(self, ws: str) -> Action:
        return Action(
            action_type="lark_sync",
            description="Sync research diary and experiment data to Lark",
            stage="lark_sync",
        )

    def _action_quality_gate(self) -> Action:
        review = self.ws.read_file("supervisor/review_writing.md") or ""
        match = re.search(r"(?:score|rating|quality)[:\s]*(\d+(?:\.\d+)?)",
                          review, re.IGNORECASE)
        score = float(match.group(1)) if match else 5.0
        iteration = self.ws.get_status().iteration

        if score >= 8.0 and iteration >= 2:
            return Action(
                action_type="done",
                description=f"Quality threshold reached (score={score}). Pipeline complete.",
                stage="done",
            )
        elif iteration >= 3:
            return Action(
                action_type="done",
                description=f"Max iterations reached (score={score}). Pipeline complete.",
                stage="done",
            )
        else:
            self.ws.update_iteration(iteration + 1)
            return Action(
                action_type="bash",
                bash_command=f"echo 'Starting iteration {iteration + 1}'",
                description=f"Quality gate: score={score}, starting iteration {iteration + 1}",
                stage="init",
            )

    # ══════════════════════════════════════════════
    # Reflection (pure Python, no SDK)
    # ══════════════════════════════════════════════

    def run_reflection(self):
        """Run reflection and log iteration results. Called via Bash."""
        from fars.reflection import IterationLogger
        from fars.evolution import EvolutionEngine

        iteration = self.ws.get_status().iteration
        logger = IterationLogger(self.ws.root)

        supervisor_review = self.ws.read_file("supervisor/review_writing.md") or ""
        critic_feedback = self.ws.read_file("critic/critique_writing.md") or ""
        issues_raw = self.ws.read_file("supervisor/issues.json")

        issues_found = []
        if issues_raw:
            try:
                issues_data = json.loads(issues_raw)
                issues_found = [i.get("description", "") for i in issues_data]
            except (json.JSONDecodeError, TypeError):
                pass

        score = 5.0
        score_match = re.search(r'(?:score|rating|quality)[:\s]*(\d+(?:\.\d+)?)',
                                supervisor_review, re.IGNORECASE)
        if score_match:
            score = float(score_match.group(1))

        logger.log_iteration(
            iteration=iteration,
            stage="supervisor",
            changes=[f"Iteration {iteration} complete"],
            issues_found=issues_found[:10],
            issues_fixed=[],
            quality_score=score,
            notes=f"Critic summary: {critic_feedback[:200]}",
        )

        # Research diary
        diary_entry = (
            f"# Iteration {iteration}\n\n"
            f"**Score**: {score}/10\n"
            f"**Issues**: {len(issues_found)}\n\n"
            f"## Review Summary\n{supervisor_review[:1000]}\n\n"
            f"## Critique Summary\n{critic_feedback[:500]}\n"
        )
        existing_diary = self.ws.read_file("logs/research_diary.md") or ""
        self.ws.write_file("logs/research_diary.md", existing_diary + "\n\n" + diary_entry)

        # Evolution recording
        if self.config.evolution_enabled:
            engine = EvolutionEngine()
            engine.record_outcome(
                project=self.ws.name,
                stage="iteration",
                issues=issues_found,
                score=score,
                notes=f"Iteration {iteration}",
            )

        print(json.dumps({"status": "ok", "score": score, "issues": len(issues_found)}))

    # ══════════════════════════════════════════════
    # Utilities
    # ══════════════════════════════════════════════

    def _get_next_stage(self, current_stage: str, result: str = "",
                        score: float | None = None) -> str:
        """Determine the next stage based on current stage and result."""
        try:
            idx = self.STAGES.index(current_stage)
            if idx + 1 < len(self.STAGES):
                return self.STAGES[idx + 1]
        except ValueError:
            pass
        return current_stage

    def _get_current_cycle(self) -> int:
        """Get current idea-experiment cycle number."""
        cycle = 0
        for f in sorted(self.ws.list_files("logs")):
            if "idea_exp_cycle" in f:
                cycle += 1
        return cycle

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        return slug[:60]


# ══════════════════════════════════════════════
# CLI helpers for Bash invocation
# ══════════════════════════════════════════════

def cli_init(topic: str, project_name: str | None = None,
             config_path: str | None = None):
    """CLI: Initialize a project."""
    result = FarsOrchestrator.init_project(topic, project_name, config_path)
    print(json.dumps(result, indent=2))


def cli_next(workspace_path: str):
    """CLI: Get next action."""
    o = FarsOrchestrator(workspace_path)
    action = o.get_next_action()
    print(json.dumps(action, indent=2))


def cli_record(workspace_path: str, stage: str, result: str = "",
               score: float | None = None):
    """CLI: Record stage result."""
    o = FarsOrchestrator(workspace_path)
    o.record_result(stage, result, score)
    print(json.dumps({"status": "ok", "new_stage": o.ws.get_status().stage}))


def cli_status(workspace_path: str):
    """CLI: Get project status."""
    o = FarsOrchestrator(workspace_path)
    print(json.dumps(o.get_status(), indent=2))


def cli_list_projects(workspaces_dir: str = "workspaces"):
    """CLI: List all projects."""
    ws_dir = Path(workspaces_dir)
    if not ws_dir.exists():
        print(json.dumps([]))
        return
    projects = []
    for d in sorted(ws_dir.iterdir()):
        if d.is_dir() and (d / "status.json").exists():
            try:
                ws = Workspace(ws_dir, d.name)
                meta = ws.get_project_metadata()
                meta["topic"] = ws.read_file("topic.txt") or ""
                projects.append(meta)
            except Exception:
                continue
    print(json.dumps(projects, indent=2))
