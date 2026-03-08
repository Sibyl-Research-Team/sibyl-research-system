"""Sibyl orchestrator for Claude Code native mode.

This module provides a state-machine orchestrator that returns the next action
for the main Claude Code session to execute. It does NOT call claude-agent-sdk.

Usage (called by Skill via Bash):
    python -c "from sibyl.orchestrate import FarsOrchestrator; ..."
"""
import json
import re
import time
from pathlib import Path
from dataclasses import dataclass, asdict

from sibyl.config import Config
from sibyl.workspace import Workspace

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
    """Load an agent prompt from the prompts/ directory, with overlay injection."""
    path = PROMPTS_DIR / f"{agent_name}.md"
    if not path.exists():
        return ""
    base = path.read_text(encoding="utf-8")

    # Global overlay (cross-project experience)
    overlay_path = (
        Path.home() / ".claude" / "sibyl_evolution" / "lessons" / f"{agent_name}.md"
    )
    if overlay_path.exists():
        overlay = overlay_path.read_text(encoding="utf-8")
        base += f"\n\n---\n\n{overlay}"

    return base


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
    action_type: str  # "skill", "skills_parallel", "agents_parallel", "agent_single", "team", "bash", "done", "paused"
    agents: list[dict] | None = None  # for legacy agent actions
    skills: list[dict] | None = None  # for fork skill actions: [{"name": "sibyl-xxx", "args": "..."}]
    team: dict | None = None  # for Agent Teams: {"prompt": "...", "teammates": [{"role": "...", "prompt": "..."}], "require_plan_approval": bool}
    bash_command: str | None = None  # for bash actions
    description: str = ""
    stage: str = ""


class FarsOrchestrator:
    """State-machine orchestrator for Sibyl research pipeline.

    Called by the Sibyl Skill, returns the next action for Claude Code to execute.
    """

    # Pipeline stages in order
    STAGES = [
        "init",
        "literature_search",
        "idea_debate",
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
        "writing_latex",
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

        ws.write_file("topic.txt", topic)
        ws.update_stage("init")
        ws.git_init()

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

    def _resolve_model_tier(self, agent_name: str) -> tuple[str, str]:
        """Return (tier, model_id) for a given agent name."""
        tier_key = agent_name
        if agent_name.startswith("writer_"):
            tier_key = "section_writer"
        elif agent_name.startswith("critic_") and agent_name != "critic":
            tier_key = "section_critic"
        elif "_critiques_" in agent_name:
            tier_key = "idea_critique"

        tier = self.config.agent_tier_map.get(tier_key, "standard")
        model = self.config.model_tiers.get(tier, self.config.model_tiers["standard"])
        return tier, model

    def get_next_action(self) -> dict:
        """Determine and return the next action based on current state."""
        status = self.ws.get_status()

        # Check pause state
        if status.paused_at > 0:
            return asdict(Action(
                action_type="paused",
                description=f"项目已暂停（{time.strftime('%H:%M', time.localtime(status.paused_at))}）。"
                            f"等待额度恢复后自动继续。",
                stage=status.stage,
            ))

        stage = status.stage
        topic = self.ws.read_file("topic.txt") or ""

        action = self._compute_action(stage, topic, status.iteration)

        # Inject model tier info into legacy agents (cross-critique still uses this)
        if action.agents:
            for agent in action.agents:
                tier, model = self._resolve_model_tier(agent["name"])
                agent["model_tier"] = tier
                agent["model"] = model

        return asdict(action)

    def record_result(self, stage: str, result: str = "",
                      score: float | None = None):
        """Record the result of a completed stage and advance state."""
        if stage == "done":
            raise ValueError("Cannot record result for terminal stage 'done'")
        current = self.ws.get_status().stage
        if stage != current:
            raise ValueError(
                f"Stage mismatch: recording '{stage}' but current is '{current}'"
            )

        # Post-reflection hook: process reflection agent outputs
        if stage == "reflection":
            self._post_reflection_hook()

        next_stage, new_iteration = self._get_next_stage(stage, result, score)
        if new_iteration is not None:
            self.ws.update_stage_and_iteration(next_stage, new_iteration)
        else:
            self.ws.update_stage(next_stage)

        if score is not None:
            self.ws.write_file(
                f"logs/stage_{stage}_score.txt",
                f"{score}"
            )

        # Auto git commit after each stage
        score_str = f" (score={score})" if score is not None else ""
        self.ws.git_commit(f"sibyl: complete {stage}{score_str}")

    def get_status(self) -> dict:
        """Get current project status."""
        meta = self.ws.get_project_metadata()
        meta["topic"] = self.ws.read_file("topic.txt") or ""
        return meta

    def _compute_action(self, stage: str, topic: str, iteration: int) -> Action:
        """Compute the next action based on current stage."""
        ws = self.workspace_path

        if stage == "init":
            # init is a transient stage; _get_next_stage("init") advances to literature_search
            action = self._action_literature_search(topic, ws)
            action.stage = "init"  # keep stage matching current state for record_result validation
            return action

        elif stage == "literature_search":
            return self._action_literature_search(topic, ws)

        elif stage == "idea_debate":
            return self._action_idea_debate(topic, ws)

        elif stage == "planning":
            return self._action_planning(ws)

        elif stage == "pilot_experiments":
            return self._action_pilot_experiments(ws)

        elif stage == "experiment_cycle":
            return self._action_experiment_cycle(ws, iteration)

        elif stage == "result_debate":
            return self._action_result_debate(ws)

        elif stage == "experiment_decision":
            return self._action_experiment_decision(ws)

        elif stage == "writing_outline":
            return self._action_writing_outline(ws)

        elif stage == "writing_sections":
            return self._action_writing_sections(ws)

        elif stage == "writing_critique":
            return self._action_writing_critique(ws)

        elif stage == "writing_integrate":
            return self._action_writing_integrate(ws)

        elif stage == "writing_final_review":
            return self._action_writing_final_review(ws)

        elif stage == "writing_latex":
            return self._action_writing_latex(ws)

        elif stage == "critic_review":
            return self._action_critic_review(ws)

        elif stage == "supervisor_review":
            return self._action_supervisor_review(ws)

        elif stage == "reflection":
            return self._action_reflection(ws, iteration)

        elif stage == "lark_sync":
            return self._action_lark_sync(ws)

        elif stage == "quality_gate":
            return self._action_quality_gate()

        elif stage == "done":
            return Action(action_type="done", description="Pipeline complete", stage="done")

        else:
            return Action(action_type="done", description="Unknown stage", stage="done")

    # ══════════════════════════════════════════════
    # Action builders
    # ══════════════════════════════════════════════

    def _action_literature_search(self, topic: str, ws: str) -> Action:
        """Single fork skill performs literature search via arXiv + WebSearch."""
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-literature", "args": f"{topic} {ws}"}],
            description="文献调研：arXiv 搜索 + Web 搜索，建立领域现状基础",
            stage="literature_search",
        )

    def _action_idea_debate(self, topic: str, ws: str) -> Action:
        """Agent Team: 3 teammates generate, debate, and synthesize research ideas."""
        # Prepare context file for teammates to read
        spec = self.ws.read_file("spec.md") or ""
        initial_ideas = self.ws.read_file("idea/initial_ideas.md") or ""
        seed_refs = self.ws.read_file("idea/references_seed.md") or ""
        literature = self.ws.read_file("context/literature.md") or ""

        extra_context = ""
        if spec:
            extra_context += f"\n\n## Project Spec\n{spec}"
        if initial_ideas:
            extra_context += f"\n\n## User's Initial Ideas\n{initial_ideas}"
        if seed_refs:
            extra_context += f"\n\n## Seed References (from user)\n{seed_refs}"
        if literature:
            extra_context += f"\n\n## 文献调研报告（请仔细阅读，避免重复已有工作）\n{literature}"

        if extra_context:
            self.ws.write_file("context/idea_context.md", extra_context)

        team_prompt = (
            f"Create an agent team to generate and debate research ideas for: {topic}\n\n"
            f"Workspace: {ws}\n\n"
            f"Spawn 3 teammates:\n"
            f"1. Innovator: bold cross-disciplinary ideas. Read {ws}/context/idea_context.md for background. "
            f"Write idea to {ws}/idea/perspectives/innovator.md\n"
            f"2. Pragmatist: engineering-feasible ideas. Read same context. "
            f"Write to {ws}/idea/perspectives/pragmatist.md\n"
            f"3. Theoretical: mathematically grounded ideas. Read same context. "
            f"Write to {ws}/idea/perspectives/theoretical.md\n\n"
            f"After generating ideas, have teammates critique each other's work (score 1-10). "
            f"Write critiques to {ws}/idea/debate/CRITIC_on_AUTHOR.md\n\n"
            f"Finally, synthesize all ideas and critiques into a final proposal at "
            f"{ws}/idea/proposal.md. Pick the strongest idea, incorporating feedback.\n\n"
        )
        if self.config.codex_enabled:
            team_prompt += (
                f"4. Codex Reviewer (独立第三方): 由 OpenAI Codex 提供独立视角，"
                f"评审将在团队讨论后自动执行，输出到 {ws}/codex/idea_debate_review.md\n\n"
            )
        team_prompt += "All output in Chinese. Use Sonnet for teammates."

        team_dict = {"prompt": team_prompt}
        if self.config.codex_enabled:
            team_dict["codex_step"] = {
                "skill": "sibyl-codex-reviewer",
                "args": f"idea_debate {ws}",
            }

        return Action(
            action_type="team",
            team=team_dict,
            description="Agent Team: 3人辩论生成研究提案（创新者+实用主义者+理论家）"
                        + (" + Codex 独立审查" if self.config.codex_enabled else ""),
            stage="idea_debate",
        )

    def _action_planning(self, ws: str) -> Action:
        pilot_config = (
            f"samples={self.config.pilot_samples}, "
            f"seeds={self.config.pilot_seeds}, timeout={self.config.pilot_timeout}s"
        )
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-planner", "args": f"{ws} {pilot_config}"}],
            description="Design experiment plan with pilot/full configs",
            stage="planning",
        )

    def _action_pilot_experiments(self, ws: str) -> Action:
        gpu_ids_str = ",".join(str(g) for g in self.config.gpu_ids)
        if self.config.experiment_mode in ("server_codex", "server_claude"):
            return Action(
                action_type="skill",
                skills=[{
                    "name": "sibyl-server-experimenter",
                    "args": f"PILOT {ws} {self.config.ssh_server} {self.config.remote_base} {gpu_ids_str} {self.config.experiment_mode} {self.config.server_codex_path} {self.config.server_claude_path}",
                }],
                description=f"Run pilot experiments on server ({self.config.experiment_mode})",
                stage="pilot_experiments",
            )
        return Action(
            action_type="skill",
            skills=[{
                "name": "sibyl-experimenter",
                "args": f"PILOT {ws} {self.config.ssh_server} {self.config.remote_base} {gpu_ids_str}",
            }],
            description="Run pilot experiments for quick validation",
            stage="pilot_experiments",
        )

    def _action_experiment_cycle(self, ws: str, iteration: int) -> Action:
        gpu_ids_str = ",".join(str(g) for g in self.config.gpu_ids)
        if self.config.experiment_mode in ("server_codex", "server_claude"):
            return Action(
                action_type="skill",
                skills=[{
                    "name": "sibyl-server-experimenter",
                    "args": f"FULL {ws} {self.config.ssh_server} {self.config.remote_base} {gpu_ids_str} {self.config.experiment_mode} {self.config.server_codex_path} {self.config.server_claude_path}",
                }],
                description=f"Run full experiments on server ({self.config.experiment_mode})",
                stage="experiment_cycle",
            )
        return Action(
            action_type="skill",
            skills=[{
                "name": "sibyl-experimenter",
                "args": f"FULL {ws} {self.config.ssh_server} {self.config.remote_base} {gpu_ids_str}",
            }],
            description="Run full experiments with statistical rigor",
            stage="experiment_cycle",
        )

    def _action_result_debate(self, ws: str) -> Action:
        team_prompt = (
            f"Create an agent team to debate experiment results.\n\n"
            f"Workspace: {ws}\n"
            f"Read experiment results from {ws}/exp/results/\n\n"
            f"Spawn 3 teammates:\n"
            f"1. Optimist: highlight positive findings, potential impact\n"
            f"2. Skeptic: challenge results, find flaws, demand more evidence\n"
            f"3. Strategist: assess strategic implications, suggest next steps\n\n"
            f"Have them debate each other's positions. The skeptic should challenge "
            f"the optimist's claims, the strategist should mediate.\n\n"
            f"Each teammate writes analysis to {ws}/idea/result_debate/ROLE.md\n"
            f"All output in Chinese."
        )

        team_dict = {"prompt": team_prompt}
        if self.config.codex_enabled:
            team_dict["codex_step"] = {
                "skill": "sibyl-codex-reviewer",
                "args": f"result_debate {ws}",
            }

        return Action(
            action_type="team",
            team=team_dict,
            description="Agent Team: 3人辩论实验结果（乐观者+怀疑论者+战略家）"
                        + (" + Codex 独立审查" if self.config.codex_enabled else ""),
            stage="result_debate",
        )

    def _action_experiment_decision(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-supervisor-decision", "args": ws}],
            description="Supervisor analyzes results and decides PIVOT or PROCEED",
            stage="experiment_decision",
        )

    def _action_writing_outline(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-outline-writer", "args": ws}],
            description="Generate paper outline",
            stage="writing_outline",
        )

    def _action_writing_sections(self, ws: str) -> Action:
        mode = self.config.writing_mode
        if mode == "sequential":
            return Action(
                action_type="skill",
                skills=[{"name": "sibyl-sequential-writer", "args": ws}],
                description="顺序撰写论文各章节（确保行文一致性）",
                stage="writing_sections",
            )
        elif mode == "codex":
            return Action(
                action_type="skill",
                skills=[{"name": "sibyl-codex-writer", "args": ws}],
                description="使用 Codex (GPT-5) 撰写论文各章节",
                stage="writing_sections",
            )
        else:  # "parallel" — 保留现有 team 模式
            sections_info = "\n".join(
                f"- {name} (section id: {sid}): write to {ws}/writing/sections/{sid}.md"
                for sid, name in PAPER_SECTIONS
            )
            team_prompt = (
                f"Create an agent team to write paper sections in parallel.\n\n"
                f"Workspace: {ws}\n"
                f"Read outline from {ws}/writing/outline.md\n"
                f"Read experiment results from {ws}/exp/results/\n\n"
                f"Spawn 6 teammates, one for each section:\n{sections_info}\n\n"
                f"Teammates should coordinate for consistency — share key definitions, "
                f"notation, and cross-references between sections.\n"
                f"All writing in Chinese."
            )
            return Action(
                action_type="team",
                team={"prompt": team_prompt},
                description="Agent Team: 6人并行撰写论文各章节",
                stage="writing_sections",
            )

    def _action_writing_critique(self, ws: str) -> Action:
        sections_info = "\n".join(
            f"- Critic for {name}: read {ws}/writing/sections/{sid}.md, "
            f"write critique to {ws}/writing/critique/{sid}_critique.md"
            for sid, name in PAPER_SECTIONS
        )
        team_prompt = (
            f"Create an agent team to critique paper sections.\n\n"
            f"Workspace: {ws}\n\n"
            f"Spawn 6 teammates, one critic per section:\n{sections_info}\n\n"
            f"Critics should cross-reference other sections for consistency issues. "
            f"Score each section 1-10 and provide specific improvement suggestions.\n"
            f"All output in Chinese."
        )
        return Action(
            action_type="team",
            team={"prompt": team_prompt},
            description="Agent Team: 6人并行批评论文各章节",
            stage="writing_critique",
        )

    def _action_writing_integrate(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-editor", "args": ws}],
            description="Integrate all sections into coherent paper",
            stage="writing_integrate",
        )

    def _action_writing_final_review(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-final-critic", "args": ws}],
            description="Top-tier conference-level paper review",
            stage="writing_final_review",
        )

    def _action_writing_latex(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{
                "name": "sibyl-latex-writer",
                "args": f"{ws} {self.config.ssh_server} {self.config.remote_base}",
            }],
            description="将论文转为 NeurIPS LaTeX 格式并编译 PDF",
            stage="writing_latex",
        )

    def _action_critic_review(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-critic", "args": ws}],
            description="Harsh but fair academic critique of all outputs",
            stage="critic_review",
        )

    def _action_supervisor_review(self, ws: str) -> Action:
        skills = [{"name": "sibyl-supervisor", "args": ws}]
        if self.config.codex_enabled:
            skills.append({"name": "sibyl-codex-reviewer", "args": f"supervisor_review {ws}"})
        return Action(
            action_type="skills_parallel" if len(skills) > 1 else "skill",
            skills=skills,
            description="监督审查" + (" + Codex 独立审查" if self.config.codex_enabled else ""),
            stage="supervisor_review",
        )

    def _action_reflection(self, ws: str, iteration: int) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-reflection", "args": f"{ws} {iteration}"}],
            description="Reflection agent: classify issues, generate improvement plan and lessons",
            stage="reflection",
        )

    def _action_lark_sync(self, ws: str) -> Action:
        return Action(
            action_type="skill",
            skills=[{"name": "sibyl-lark-sync", "args": ws}],
            description="Sync research data to Feishu (docs, bitable, notifications)",
            stage="lark_sync",
        )

    def _is_pipeline_done(self) -> tuple[bool, float, float, int, int]:
        """Determine if the pipeline should terminate.

        Returns (is_done, score, threshold, max_iters, iteration).
        """
        score, threshold, max_iters = self._parse_quality_gate_params()
        iteration = self.ws.get_status().iteration
        done = (score >= threshold and iteration >= 2) or iteration >= max_iters
        return done, score, threshold, max_iters, iteration

    def _action_quality_gate(self) -> Action:
        """Pure computation — no side effects. Side effects in _get_next_stage."""
        is_done, score, threshold, max_iters, iteration = self._is_pipeline_done()

        if is_done:
            return Action(
                action_type="done",
                description=(
                    f"Pipeline complete (score={score}, threshold={threshold}, "
                    f"iter={iteration}/{max_iters})."
                ),
                stage="done",
            )
        else:
            return Action(
                action_type="bash",
                bash_command=f"echo 'Starting iteration {iteration + 1}'",
                description=(
                    f"Quality gate: score={score} < {threshold}, "
                    f"starting iteration {iteration + 1}"
                ),
                stage="quality_gate",
            )

    # ══════════════════════════════════════════════
    # Post-reflection hook (processes reflection agent outputs)
    # ══════════════════════════════════════════════

    def _post_reflection_hook(self):
        """Process reflection agent outputs: log iteration, record evolution, generate overlay."""
        from sibyl.reflection import IterationLogger
        from sibyl.evolution import EvolutionEngine

        iteration = self.ws.get_status().iteration
        logger = IterationLogger(self.ws.root)

        # Read reflection agent's structured output
        action_plan_raw = self.ws.read_file("reflection/action_plan.json")
        classified_issues = []
        if action_plan_raw:
            try:
                action_plan = json.loads(action_plan_raw)
                classified_issues = action_plan.get("issues_classified", [])
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: read supervisor issues if reflection agent didn't produce classified issues
        if not classified_issues:
            issues_raw = self.ws.read_file("supervisor/issues.json")
            if issues_raw:
                try:
                    issues_data = json.loads(issues_raw)
                    from sibyl.evolution import IssueCategory
                    classified_issues = [
                        {
                            "description": i.get("description", ""),
                            "category": IssueCategory.classify(i.get("description", "")).value,
                            "severity": i.get("severity", "medium"),
                        }
                        for i in issues_data
                    ]
                except (json.JSONDecodeError, TypeError):
                    pass

        issues_found = [ci.get("description", "") for ci in classified_issues]

        # Extract score
        supervisor_review = self.ws.read_file("supervisor/review_writing.md") or ""
        score = 5.0
        score_match = re.search(r'(?:score|rating|quality)[:\s]*(\d+(?:\.\d+)?)(?!\w)',
                                supervisor_review, re.IGNORECASE)
        if score_match:
            score = min(max(float(score_match.group(1)), 0.0), 10.0)

        # 1. Log iteration with classified issues
        try:
            logger.log_iteration(
                iteration=iteration,
                stage="reflection",
                changes=[f"Iteration {iteration} complete"],
                issues_found=issues_found[:10],
                issues_fixed=[],
                quality_score=score,
                notes=json.dumps({"classified_issues": classified_issues[:10]}, ensure_ascii=False),
            )
        except Exception as e:
            self.ws.add_error(f"Reflection logging failed: {e}")

        # 2. Research diary
        try:
            critic_feedback = self.ws.read_file("critic/critique_writing.md") or ""
            reflection_md = self.ws.read_file("reflection/reflection.md") or ""
            diary_entry = (
                f"# Iteration {iteration}\n\n"
                f"**Score**: {score}/10\n"
                f"**Issues**: {len(issues_found)}\n\n"
                f"## Reflection\n{reflection_md[:1000]}\n\n"
                f"## Review Summary\n{supervisor_review[:500]}\n\n"
                f"## Critique Summary\n{critic_feedback[:500]}\n"
            )
            existing_diary = self.ws.read_file("logs/research_diary.md") or ""
            self.ws.write_file("logs/research_diary.md", existing_diary + "\n\n" + diary_entry)
        except Exception as e:
            self.ws.add_error(f"Diary update failed: {e}")

        # 3. Evolution recording with classification
        try:
            if self.config.evolution_enabled:
                engine = EvolutionEngine()
                engine.record_outcome(
                    project=self.ws.name,
                    stage="reflection",
                    issues=issues_found,
                    score=score,
                    notes=f"Iteration {iteration}",
                )
                engine.generate_lessons_overlay()
        except Exception as e:
            self.ws.add_error(f"Evolution recording failed: {e}")

    # ══════════════════════════════════════════════
    # Utilities
    # ══════════════════════════════════════════════

    def _parse_quality_gate_params(self) -> tuple[float, float, int]:
        """Parse quality gate parameters from supervisor review and reflection action plan.

        Returns (score, threshold, max_iters).
        """
        review = self.ws.read_file("supervisor/review_writing.md") or ""
        match = re.search(r"(?:score|rating|quality)[:\s]*(\d+(?:\.\d+)?)(?!\w)",
                          review, re.IGNORECASE)
        score = min(max(float(match.group(1)), 0.0), 10.0) if match else 5.0
        threshold = 8.0
        max_iters = 10
        action_plan_raw = self.ws.read_file("reflection/action_plan.json")
        if action_plan_raw:
            try:
                action_plan = json.loads(action_plan_raw)
                v = action_plan.get("suggested_threshold_adjustment")
                if isinstance(v, (int, float)) and 1.0 <= v <= 10.0:
                    threshold = float(v)
                v = action_plan.get("suggested_max_iterations")
                if isinstance(v, int) and 2 <= v <= 20:
                    max_iters = v
            except (json.JSONDecodeError, TypeError):
                pass
        return score, threshold, max_iters

    def _get_next_stage(self, current_stage: str, result: str = "",
                        score: float | None = None) -> tuple[str, int | None]:
        """Determine the next stage based on current stage and result.

        Returns (next_stage, new_iteration). new_iteration is non-None only
        when the quality gate loops back for a new iteration.
        """
        # experiment_decision: PIVOT loops back to idea_debate
        if current_stage == "experiment_decision":
            decision = self.ws.read_file("supervisor/experiment_analysis.md")
            if decision is None:
                self.ws.add_error("PIVOT check: supervisor/experiment_analysis.md not found")
                decision = ""
            if "DECISION: PIVOT" in decision.upper():
                cycle = self._get_current_cycle()
                if cycle < self.config.idea_exp_cycles:
                    iteration = self.ws.get_status().iteration
                    self.ws.write_file(
                        f"logs/idea_exp_cycle_{cycle + 1}.marker",
                        f"PIVOT at iteration {iteration}",
                    )
                    return ("idea_debate", None)
                else:
                    self.ws.add_error(
                        f"PIVOT requested but cycle limit reached ({cycle}/{self.config.idea_exp_cycles})"
                    )

        # writing_final_review: low score loops back to writing_integrate (with round limit)
        if current_stage == "writing_final_review":
            review = self.ws.read_file("writing/review.md") or ""
            match = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", review, re.IGNORECASE)
            review_score = float(match.group(1)) if match else 5.0
            # Count existing revision rounds via orchestrator-managed markers
            critique_dir = self.ws.root / "writing/critique"
            if critique_dir.exists():
                revision_rounds = len([
                    f for f in critique_dir.iterdir()
                    if f.is_file() and f.name.startswith("revision_round_")
                ])
            else:
                revision_rounds = 0
            max_revisions = self.config.writing_revision_rounds
            if review_score < 7.0 and revision_rounds < max_revisions:
                self.ws.write_file(
                    f"writing/critique/revision_round_{revision_rounds + 1}.marker",
                    f"Revision round {revision_rounds + 1}, score={review_score}",
                )
                return ("writing_integrate", None)

        # init is transient: always advance to literature_search
        if current_stage == "init":
            return ("literature_search", None)

        # lark stages: skip if lark disabled
        if current_stage == "reflection" and not self.config.lark_enabled:
            return ("quality_gate", None)

        # quality_gate: execute side effects and determine next stage
        if current_stage == "quality_gate":
            is_done, qg_score, threshold, max_iters, iteration = self._is_pipeline_done()
            if is_done:
                # Tag final iteration and trigger cross-project evolution
                self.ws.git_tag(
                    f"v{iteration}",
                    f"Iteration {iteration} complete, score={qg_score}",
                )
                if self.config.evolution_enabled:
                    from sibyl.evolution import EvolutionEngine
                    EvolutionEngine().run_cross_project_evolution()
                return ("done", None)
            else:
                # Tag end of iteration, archive artifacts, advance counter
                self.ws.git_tag(
                    f"iter-{iteration}",
                    f"End of iteration {iteration}, score={qg_score}",
                )
                try:
                    self.ws.archive_iteration(iteration)
                except OSError as e:
                    self.ws.add_error(f"Archive failed for iteration {iteration}: {e}")
                # Clear stale artifacts that would pollute the next iteration
                self._clear_iteration_artifacts()
                # Iteration counter update is atomic with stage in record_result
                return ("literature_search", iteration + 1)

        try:
            idx = self.STAGES.index(current_stage)
            if idx + 1 < len(self.STAGES):
                return (self.STAGES[idx + 1], None)
        except ValueError:
            self.ws.add_error(f"Unknown stage '{current_stage}', forcing done")
            return ("done", None)
        return (current_stage, None)

    def _clear_iteration_artifacts(self):
        """Clear stale working-directory artifacts between iterations.

        Called after archive_iteration to prevent data pollution
        (e.g., revision markers, supervisor scores) from leaking into the next iteration.
        """
        import shutil
        dirs_to_clear = [
            "idea/perspectives", "idea/debate", "idea/result_debate",
            "plan",
            "writing/sections", "writing/critique",
            "supervisor", "critic", "reflection",
        ]
        for subdir in dirs_to_clear:
            target = self.ws.root / subdir
            if target.exists():
                try:
                    shutil.rmtree(target)
                    target.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass  # best-effort cleanup
        # Clear PIVOT cycle markers (per-iteration budget)
        logs_dir = self.ws.root / "logs"
        if logs_dir.exists():
            for marker in logs_dir.glob("idea_exp_cycle_*.marker"):
                try:
                    marker.unlink()
                except OSError:
                    pass

    def _get_current_cycle(self) -> int:
        """Get current idea-experiment cycle number."""
        logs_dir = self.ws.root / "logs"
        if not logs_dir.exists():
            return 0
        return len(list(logs_dir.glob("idea_exp_cycle_*.marker")))

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


def cli_pause(workspace_path: str, reason: str = "rate_limit"):
    """CLI: Pause a project."""
    o = FarsOrchestrator(workspace_path)
    o.ws.pause(reason)
    print(json.dumps({"status": "paused", "stage": o.ws.get_status().stage}))


def cli_resume(workspace_path: str):
    """CLI: Resume a paused project."""
    o = FarsOrchestrator(workspace_path)
    o.ws.resume()
    print(json.dumps({"status": "resumed", "stage": o.ws.get_status().stage}))


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


def cli_init_spec(project_name: str, config_path: str | None = None):
    """CLI: Initialize a project directory for spec editing."""
    config = Config.from_yaml(config_path) if config_path else Config()
    ws = Workspace(config.workspaces_dir, project_name)

    # Create spec template
    spec_template = f"""# 项目: {project_name}

## 研究主题
<!-- 一句话描述研究主题 -->

## 背景与动机
<!-- 为什么要研究这个？有什么已知的相关工作？ -->

## 初始想法
<!-- 你已有的想法或方向（可选） -->

## 关键参考文献
<!-- 论文 URL、arXiv ID 等 -->
-

## 可用资源
- GPU: 4x on cs8000d
- 服务器: {config.ssh_server}
- 远程路径: {config.remote_base}

## 实验约束
- 实验类型: training-free / 轻量训练 / 不限
- 模型规模: 小 (GPT-2, BERT-base, Qwen-0.5B)
- 时间预算:

## 目标产出
- 论文 / 技术报告 / 实验验证

## 特殊需求
<!-- 任何特殊需求 -->
"""
    ws.write_file("spec.md", spec_template)
    print(json.dumps({
        "project_name": project_name,
        "workspace_path": str(ws.root),
        "spec_path": str(ws.root / "spec.md"),
    }, indent=2))


def cli_init_from_spec(spec_path: str, config_path: str | None = None):
    """CLI: Initialize a project from a spec markdown file."""
    spec_file = Path(spec_path)
    if not spec_file.exists():
        print(json.dumps({"error": f"Spec file not found: {spec_path}"}))
        return

    spec_content = spec_file.read_text(encoding="utf-8")

    # Extract project name from path or spec
    # Try to get from parent directory name if in workspaces/
    if spec_file.parent.parent.name == "workspaces" or "workspaces" in str(spec_file):
        project_name = spec_file.parent.name
    else:
        # Extract from spec header
        match = re.search(r'^#\s*(?:Project|项目):\s*(.+)', spec_content, re.MULTILINE)
        project_name = match.group(1).strip() if match else spec_file.stem

    project_name = FarsOrchestrator._slugify(project_name)
    config = Config.from_yaml(config_path) if config_path else Config()

    ws = Workspace(config.workspaces_dir, project_name)

    # Extract topic from spec
    topic_match = re.search(r'##\s*(?:Topic|研究主题)\s*\n+(.+?)(?:\n\n|\n##)', spec_content, re.DOTALL)
    topic = topic_match.group(1).strip() if topic_match else project_name
    # Remove HTML comments
    topic = re.sub(r'<!--.*?-->', '', topic).strip()

    # Save spec and topic
    ws.write_file("spec.md", spec_content)
    ws.write_file("topic.txt", topic)
    ws.update_stage("init")
    ws.git_init()

    # Extract references if present
    refs_match = re.search(r'##\s*(?:Key References|关键参考文献)\s*\n(.+?)(?:\n##|\Z)', spec_content, re.DOTALL)
    if refs_match:
        ws.write_file("idea/references_seed.md", refs_match.group(1).strip())

    # Extract initial ideas if present
    ideas_match = re.search(r'##\s*(?:Initial Ideas|初始想法)\s*\n(.+?)(?:\n##|\Z)', spec_content, re.DOTALL)
    if ideas_match:
        ideas_text = ideas_match.group(1).strip()
        ideas_text = re.sub(r'<!--.*?-->', '', ideas_text).strip()
        if ideas_text:
            ws.write_file("idea/initial_ideas.md", ideas_text)

    print(json.dumps({
        "project_name": project_name,
        "workspace_path": str(ws.root),
        "topic": topic,
        "spec_path": str(ws.root / "spec.md"),
        "config": {
            "ssh_server": config.ssh_server,
            "remote_base": config.remote_base,
            "gpu_ids": config.gpu_ids,
            "pilot_samples": config.pilot_samples,
            "full_seeds": config.full_seeds,
            "lark_enabled": config.lark_enabled,
        },
    }, indent=2))


def cli_migrate(workspace_path: str):
    """CLI: Migrate a legacy project to v5 structure."""
    ws_path = Path(workspace_path)
    if not ws_path.exists():
        print(json.dumps({"error": f"Workspace not found: {workspace_path}"}))
        return

    config = Config()
    project_name = ws_path.name
    ws = Workspace(config.workspaces_dir, project_name)

    changes = []

    # Ensure v5 directories exist (Workspace.__init__ handles this)
    changes.append("Ensured v5 directory structure")

    # Create topic.txt if missing
    if not (ws.root / "topic.txt").exists():
        # Try to extract from proposal
        proposal = ws.read_file("idea/proposal.md")
        if proposal:
            # Try to extract title
            title_match = re.search(r'^#\s*(.+)', proposal, re.MULTILINE)
            topic = title_match.group(1).strip() if title_match else project_name
        else:
            topic = project_name.replace("-", " ").title()
        ws.write_file("topic.txt", topic)
        changes.append(f"Created topic.txt: {topic}")

    # Ensure status.json has iteration field
    status = ws.get_status()
    if status.iteration == 0 and status.stage == "done":
        status.iteration = 1
        ws._save_status(status)
        changes.append("Set iteration to 1 (was 0 for completed project)")

    # Create missing subdirectories
    for subdir in ["idea/perspectives", "idea/debate", "idea/result_debate",
                   "plan", "exp/results/pilots", "exp/results/full",
                   "lark_sync", "logs/iterations"]:
        d = ws.root / subdir
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            changes.append(f"Created directory: {subdir}")

    print(json.dumps({
        "project_name": project_name,
        "workspace_path": str(ws.root),
        "changes": changes,
        "status": {
            "stage": ws.get_status().stage,
            "iteration": ws.get_status().iteration,
        },
    }, indent=2))


def cli_migrate_server(project_name: str, ssh_connection: str = "default"):
    """CLI: Generate server migration commands.

    Prints the SSH commands needed to reorganize server-side files
    into the v5 project structure. Execute these via SSH MCP.
    """
    if not re.fullmatch(r'[a-zA-Z0-9_\-]{1,60}', project_name):
        print(json.dumps({"error": f"Invalid project_name: {project_name!r}"}))
        return
    config = Config()
    remote_base = config.remote_base
    project_dir = f"{remote_base}/projects/{project_name}"

    # The migration plan: move flat files into project-specific directory
    commands = [
        f"# === 服务器端 v5 迁移: {project_name} ===",
        f"mkdir -p {project_dir}/{{idea,plan,exp/code,exp/results/pilots,exp/results/full,exp/logs,writing/latex,writing/sections,writing/figures,supervisor,critic,reflection,logs/iterations,lark_sync}}",
        "",
        "# 迁移实验代码",
        f"cp -r {remote_base}/exp/code/* {project_dir}/exp/code/ 2>/dev/null || true",
        "",
        "# 迁移实验日志",
        f"cp -r {remote_base}/exp/logs/* {project_dir}/exp/logs/ 2>/dev/null || true",
        "",
        "# 迁移研究想法",
        f"cp -r {remote_base}/idea/* {project_dir}/idea/ 2>/dev/null || true",
        "",
        "# 迁移迭代日志",
        f"cp -r {remote_base}/logs/* {project_dir}/logs/ 2>/dev/null || true",
        "",
        "# 迁移论文草稿",
        f"cp -r {remote_base}/writing/* {project_dir}/writing/ 2>/dev/null || true",
        "",
        "# 创建状态文件",
        f'echo \'{{"stage": "done", "started_at": 0, "updated_at": 0, "iteration": 1, "errors": []}}\' > {project_dir}/status.json',
        "",
        "# 保留共享资源的符号链接",
        f"ln -sf {remote_base}/models {project_dir}/models 2>/dev/null || true",
        f"ln -sf {remote_base}/src {project_dir}/src 2>/dev/null || true",
        "",
        f"echo '迁移完成: {project_dir}'",
    ]

    print(json.dumps({
        "project_name": project_name,
        "remote_project_dir": project_dir,
        "commands": commands,
        "instructions": (
            "使用 mcp__ssh-mcp-server__execute-command 依次执行上述命令。\n"
            "模型和源码目录通过符号链接共享，避免重复存储。\n"
            "迁移后，新项目将在 projects/ 子目录下创建，互不干扰。"
        ),
    }, indent=2))
