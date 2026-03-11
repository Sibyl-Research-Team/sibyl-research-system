# Architecture

Deep dive into Sibyl Research System internals. For contributors and advanced users.

## Orchestrator State Machine

The core of Sibyl is a **18-stage state machine** in `sibyl/orchestrate.py`.

### State Flow

```
init → literature_search → idea_debate → planning → pilot_experiments
→ experiment_cycle → result_debate → experiment_decision
→ writing_outline → writing_sections → writing_critique
→ writing_integrate → writing_final_review → writing_latex
→ review → reflection → quality_gate → done
```

### Key Methods

- **`_compute_action(stage)`** — Returns the Action for the **current** stage (not the next one)
- **`_get_next_stage(stage)`** — Computes the transition to the next stage (called by `cli_record`)
- **`cli_next(workspace)`** — Public API: returns the next action as JSON
- **`cli_record(workspace, stage)`** — Public API: marks a stage complete and advances state

### Special Transitions

| From | Condition | To |
|------|-----------|-----|
| `experiment_decision` | PIVOT | `idea_debate` (with alternatives) |
| `experiment_decision` | PROCEED | `writing_outline` |
| `writing_final_review` | Fail (< max rounds) | `writing_integrate` |
| `quality_gate` | Score ≥ 8.0 AND iterations ≥ 2 | `done` |
| `quality_gate` | Otherwise | `literature_search` (next iteration) |
| Any stage except `init` / `quality_gate` / `done` | `lark_enabled` | append background sync trigger after `cli_record()` |

### Background Lark Sync

When `lark_enabled: true`, Feishu sync is no longer a pipeline stage. Instead, `cli_record()` appends a trigger to `lark_sync/pending_sync.jsonl` and returns `sync_requested: true`. The main Claude session must launch `sibyl-lark-sync` in the background and continue the research loop without waiting. Sync status is written to `lark_sync/sync_status.json`.

### Background Experiment Supervisor Wake Path

The experiment supervisor owns local recovery, GPU refresh, dispatch, and lightweight intervention. When it either resolves something material or hits a blocker that needs main-loop judgment, it appends a structured wake event to `exp/experiment_supervisor_main_wake.jsonl` via `experiment-supervisor-notify-main`. The main control-plane loop must not sleep for the full experiment poll interval in one chunk; instead it checks `wake_cmd` every short interval (`wake_check_interval_sec`, default 90 seconds) and immediately collaborates when an event reports `requires_main_system: true`.

## Action Types

The orchestrator returns actions that the main session executes:

| `action_type` | Description | Execution |
|---------------|-------------|-----------|
| `skill` | Single fork skill | `Skill` tool |
| `skills_parallel` | Multiple skills in parallel | `Agent` tool (parallel) |
| `team` | Multi-agent team collaboration | `TeamCreate` → `TaskCreate` → `Agent` per teammate |
| `agents_parallel` | Legacy: parallel agents with dynamic prompts | `Agent` tool (parallel) |
| `bash` | Shell command | `Bash` tool |
| `gpu_poll` | Poll for free GPUs | SSH MCP → parse → write marker file |
| `done` | Pipeline complete | Report to user |
| `stopped` | User explicitly halted the project | Resume only after `/sibyl-research:resume` |

`status.json` now uses explicit `paused` / `stop_requested` booleans, with optional `paused_at` / `stop_requested_at` timestamps for diagnostics. Legacy numeric `*_at` markers are still read for backward compatibility, and transient `paused` state is auto-cleared by `cli_next()` so the control plane does not stall. Explicit `/sibyl-research:stop` remains the only supported manual halt path.

## Fork Skills Architecture

All agent roles are implemented as **fork skills** in `.claude/skills/sibyl-*/SKILL.md`.

### How Skills Work

1. Orchestrator returns `action_type: "skill"` with skill name and args
2. Main session invokes skill via `Skill` tool
3. Skill runs in an isolated subagent context (fork)
4. Skill uses `!`command`` to dynamically load the prompt template from `sibyl/prompts/`
5. Skill executes with the loaded prompt and writes outputs to workspace

### Agent Tiers

Defined in `.claude/agents/`:

| File | Model | Agents |
|------|-------|--------|
| `sibyl-heavy.md` | Opus 4.6 | synthesizer, supervisor, editor, critic, reflection |
| `sibyl-standard.md` | Opus 4.6 | literature, planner, experimenter, writing |
| `sibyl-light.md` | Sonnet 4.6 | optimist, skeptic, strategist, section-critic |

## Team Mode

Used for debate stages (idea_debate, result_debate, writing_sections, writing_critique).

**Requires**: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`

### Flow

1. `TeamCreate(team_name)` — Create team
2. `TaskCreate(subject, description)` — Create task per teammate
3. `Agent(team_name, name)` — Launch teammates in parallel
4. `TaskUpdate(taskId, owner)` — Lead assigns tasks (not self-claimed)
5. Wait for all teammates to idle
6. `SendMessage(shutdown_request)` — Close each teammate
7. Execute `post_steps` (e.g., synthesizer, codex review)

## Checkpoint System

Four parallel stages support sub-step checkpoints for crash recovery:

| Stage | Checkpoint Dir |
|-------|---------------|
| `idea_debate` | `idea/` |
| `result_debate` | `exp/results/` |
| `writing_sections` | `writing/sections/` |
| `writing_critique` | `writing/critiques/` |

Checkpoints use 4-way validation:
1. Status == completed
2. Output file exists
3. File mtime ≥ stage start time
4. File size matches recorded size

On resume, only incomplete steps are re-executed.

## GPU Scheduler

`sibyl/gpu_scheduler.py` handles parallel experiment execution:

1. Read `task_plan.json` with task dependencies
2. **Topological sort** into dependency layers
3. **Greedy assignment** based on available GPUs and `gpu_count` per task
4. Return batch of tasks that can run in parallel
5. After batch completes, compute next batch from remaining tasks

### GPU Polling

On shared servers, before each experiment batch:

1. Orchestrator returns `action_type: "gpu_poll"`
2. Main session SSH queries `nvidia-smi` on the server
3. `parse_free_gpus()` identifies available GPUs
4. Results written to a workspace-scoped marker such as `/tmp/sibyl_<workspace_scope>_gpu_free.json`
5. Next `cli_next()` reads the marker and assigns tasks

## Self-Evolution Engine

`sibyl/evolution.py` implements cross-project learning:

### Issue Categories

`SYSTEM`, `EXPERIMENT`, `WRITING`, `ANALYSIS`, `PLANNING`, `PIPELINE`, `IDEATION`

Each category maps to specific agents for targeted improvement.

### Digest Layer

`build_digest()` aggregates `outcomes.jsonl` into `digest.json` with mtime caching.

### Effectiveness Tracking

- Compare early vs late iteration scores
- Mark lessons as effective/ineffective/unverified
- Requires ≥ 4 occurrences for judgment
- Ineffective lessons get 0.3x weight reduction

### Overlay Generation

Effective lessons are injected into agent prompts through the compiled prompt layer:
`render_skill_prompt(agent, workspace_path=...)` builds the final prompt and appends
contextual evolution lessons plus any project-specific overrides.

### Self-Check

`get_self_check_diagnostics()` detects:
- Declining quality trend
- Recurring system errors
- Ineffective lesson accumulation

Written to `logs/self_check_diagnostics.json` after each reflection.

## Config Auto-Loading

`FarsOrchestrator.__init__` auto-loads project-level `config.yaml`:

```python
def __init__(self, workspace_path, config=None):
    if config is not None:
        self.config = config
    else:
        project_config = Path(workspace_path) / "config.yaml"
        if project_config.exists():
            self.config = Config.from_yaml(str(project_config))
        else:
            self.config = Config()
```

This ensures per-project configuration works without explicit config passing.
