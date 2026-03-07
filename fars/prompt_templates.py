"""Prompt template system for FARS agents.

Replaces hardcoded prompts with structured templates supporting variable substitution.
"""
from string import Template


class PromptTemplates:
    """Centralized prompt templates for all FARS agents."""

    # ── Ideation templates ──

    IDEATION_NEW_PROJECT = Template("""Research the following topic and generate a novel research proposal:

$topic

Search for related work, identify gaps, and propose a concrete, testable study.

Requirements:
- Generate at least 3 different angles: improving existing methods, cross-domain transfer, entirely new approach
- Estimate computational cost and success probability for each idea
- Consider failure modes: what could go wrong with each approach
- Every hypothesis must be testable with limited compute (single GPU or API calls)
- Use small models (GPT-2, BERT-base, Qwen-0.5B) for fast iteration

Write outputs to idea/ directory in the workspace:
- idea/proposal.md: Full proposal
- idea/hypotheses.md: Testable hypotheses
- idea/references.json: Found references""")

    IDEATION_PIVOT = Template("""IDEA-EXPERIMENT CYCLE $cycle: Revise the research approach.

Previous proposal:
$prev_proposal

Experiment results:
$results

Analysis & pivot recommendation:
$analysis

Based on the experimental evidence, REVISE the proposal:
- Keep what worked
- Change the technical approach where results were negative
- Propose new experiments that address the issues found
- Be specific about what to change and why
- Consider alternatives from alternatives.md if available""")

    IDEATION_ITERATE = Template("""ITERATION $iteration: Improve the previous proposal based on feedback.

Previous proposal:
$prev_proposal

Critic feedback:
$critic_feedback

Supervisor review:
$supervisor_review

Address ALL issues raised. Strengthen weak points. Keep what works.""")

    # ── Experiment templates ──

    EXPERIMENT_PILOT = Template("""Run PILOT experiment for quick go/no-go validation.

Task: $task_name
Samples: $pilot_samples
Seeds: $pilot_seeds
Timeout: $pilot_timeout seconds
Pass criteria: $pass_criteria

Instructions:
1. Run on a small subset ($pilot_samples samples) with seed $pilot_seeds
2. Complete within $pilot_timeout seconds
3. After running, qualitatively inspect 5-10 output samples
4. Report GO (results promising) or NO-GO (fundamental issues)
5. Save results to exp/results/pilots/$task_id/
6. Set CUDA_VISIBLE_DEVICES=$gpu_id""")

    EXPERIMENT_FULL = Template("""Run FULL experiment with statistical rigor.

Task: $task_name
Seeds: $full_seeds
GPU: $gpu_id

Instructions:
1. Run on full dataset with seeds: $full_seeds
2. Compute mean and std across seeds
3. Run statistical significance tests
4. Save per-seed results to exp/results/full/$task_id/
5. Save sample outputs (not just metrics)
6. Set CUDA_VISIBLE_DEVICES=$gpu_id
7. Use conda environment: conda run -n fars_$project""")

    # ── Writing templates ──

    WRITING_OUTLINE = Template("""Create a detailed paper outline based on the research.

Topic: $topic
Proposal: $proposal_summary
Key Results: $results_summary

Generate writing/outline.md with:
- Title
- Each section heading with 2-3 bullet points of key content
- Where each figure/table should appear
- Key arguments and evidence for each section
- Transition logic between sections""")

    WRITING_SECTION = Template("""Write the "$section_name" section of the paper.

Section outline:
$section_outline

Available context:
$context

Requirements:
- Follow the outline structure precisely
- Cite references appropriately
- Be honest about limitations
- Use clear, precise scientific language

Write to writing/sections/$section_file""")

    WRITING_INTEGRATE = Template("""Integrate all paper sections into a coherent manuscript.

Sections available: $section_list
Critique feedback: $critique_summary

Tasks:
1. Read all sections from writing/sections/
2. Ensure consistent notation, terminology, and style
3. Add smooth transitions between sections
4. Address critique feedback
5. Write the integrated paper to writing/paper.md""")

    # ── Debate templates ──

    DEBATE_CROSS_CRITIQUE = Template("""Critically evaluate this research idea from another agent.

Your role: $critic_role
Idea author: $author_role
Idea:
$idea_content

Evaluate:
1. Novelty: Is this truly new? What prior work does it overlap with?
2. Feasibility: Can this be implemented and tested with limited compute?
3. Impact: Would positive results be meaningful to the field?
4. Risks: What are the main failure modes?
5. Suggestions: How could this idea be improved?

Score: 1-10 with justification.
Write to idea/debate/$critic_role_on_$author_role.md""")

    DEBATE_SYNTHESIS = Template("""Synthesize multiple research ideas and critiques into a final proposal.

Ideas:
$all_ideas

Critiques:
$all_critiques

Tasks:
1. Rank ideas by novelty + feasibility + impact
2. Select the best idea (or merge complementary ones)
3. Address the most critical concerns raised
4. Write the final proposal to idea/proposal.md
5. Write backup ideas to idea/alternatives.md (for pivot)
6. Explain your reasoning""")

    RESULT_DEBATE_PROMPT = Template("""Discuss the experiment results from the perspective of: $role

Results summary:
$results

Proposal:
$proposal

Your role guidelines:
$role_guidelines

Provide your analysis focusing on your role's perspective.
Write to idea/result_debate/$role.md""")

    @classmethod
    def render(cls, template_name: str, **kwargs) -> str:
        """Render a template by name with the given variables."""
        template = getattr(cls, template_name.upper(), None)
        if template is None:
            raise ValueError(f"Unknown template: {template_name}")
        return template.safe_substitute(**kwargs)
