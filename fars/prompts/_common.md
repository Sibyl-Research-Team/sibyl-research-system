# FARS Agent Common Instructions

## Workspace Convention

All research artifacts are stored in a shared workspace directory. Use the Read and Write tools to interact with files.

### Directory Structure
```
<workspace>/
├── status.json              # Project status (managed by orchestrator)
├── idea/
│   ├── proposal.md          # Final synthesized proposal
│   ├── alternatives.md      # Backup ideas for pivot
│   ├── references.json      # [{title, authors, abstract, url, year}]
│   ├── hypotheses.md        # Testable hypotheses
│   ├── perspectives/        # Per-agent independent ideas
│   ├── debate/              # Cross-critique records
│   └── result_debate/       # Post-experiment discussion
├── plan/
│   ├── methodology.md       # Detailed methodology
│   ├── task_plan.json       # Structured task list
│   └── pilot_plan.json      # Pilot-specific details
├── exp/
│   ├── code/                # Experiment scripts
│   ├── results/
│   │   ├── pilots/          # Pilot experiment results
│   │   └── full/            # Full experiment results
│   ├── logs/                # Execution logs
│   └── experiment_db.jsonl  # Experiment database
├── writing/
│   ├── outline.md           # Paper outline
│   ├── sections/            # Individual sections
│   ├── critique/            # Section critiques
│   ├── paper.md             # Integrated paper
│   ├── review.md            # Final review
│   └── figures/             # Generated figures
├── supervisor/              # Supervisor reviews
├── critic/                  # Critic feedback
├── reflection/              # Reflection artifacts
└── logs/                    # Pipeline logs
```

## File I/O

- **Read files**: Use the `Read` tool with absolute paths: `<workspace>/<relative_path>`
- **Write files**: Use the `Write` tool with absolute paths
- **List files**: Use `Glob` to find files in the workspace

## Model Guidelines

- Use small models for experiments: GPT-2, BERT-base, Qwen/Qwen2-0.5B
- Keep experiments runnable on single GPU
- Set random seeds for reproducibility

## Quality Standards

- Be specific and concrete in all outputs
- Every claim must be supported by evidence
- Flag suspicious results (>30% improvement from simple methods)
- Save sample outputs, not just aggregate metrics
- Be honest about negative results
