# Configuration Reference

> Source of truth: `sibyl/config.py` — `Config` dataclass

## Config Loading Order

Sibyl loads configuration in layers, with later layers overriding earlier ones:

1. **Code defaults** — Built-in defaults from `Config` dataclass (`language: "en"`, etc.)
2. **Root `config.yaml`** — Optional file at the project root directory. Use this for machine-level defaults shared across all research projects (e.g., `language: zh`, `ssh_server`). This file is in `.gitignore` and not committed.
3. **Project `config.yaml`** — Per-project overrides at `workspaces/<project>/config.yaml`. Settings here take priority over root config.

```
Code defaults  <--  config.yaml (root)  <--  workspaces/<project>/config.yaml
```

**Example root config** (for setting local defaults):

```yaml
# config.yaml (project root, git-ignored)
language: zh
ssh_server: my-gpu-box
remote_base: /home/user/sibyl_system
```

**Example project config** (for project-specific overrides):

```yaml
# workspaces/my-project/config.yaml
gpu_aggressive_mode: true
iteration_dirs: true
remote_conda_path: /home/user/miniforge3/bin/conda
```

## Example

See [config.example.yaml](../config.example.yaml) for a minimal example.

## GPU Server

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ssh_server` | string | `"gpu-server"` | SSH host name from `~/.ssh/config` |
| `remote_base` | string | `"/home/user/sibyl_system"` | Base directory on remote server |
| `max_gpus` | int | `4` | Maximum GPUs to use (picks any free ones dynamically) |
| `gpus_per_task` | int | `1` | GPUs allocated per experiment task |

## GPU Polling (Shared Servers)

For shared GPU servers where other users may be running jobs.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gpu_poll_enabled` | bool | `true` | Enable GPU availability polling before experiments |
| `gpu_free_threshold_mb` | int | `2000` | GPU memory threshold (MB) — below this = "free" |
| `gpu_poll_interval_sec` | int | `600` | Seconds between polls (default 10 min) |
| `gpu_poll_max_attempts` | int | `0` | Max poll attempts; `0` = infinite (wait forever) |

## GPU Aggressive Mode

Treat GPUs with low VRAM usage as available, even if allocated.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gpu_aggressive_mode` | bool | `true` | Enable aggressive GPU detection |
| `gpu_aggressive_threshold_pct` | int | `25` | VRAM usage % below which GPU is treated as available |

## Pilot Experiments

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pilot_samples` | int | `16` | Number of samples for pilot validation |
| `pilot_timeout` | int | `600` | Pilot experiment timeout in seconds |
| `pilot_seeds` | list[int] | `[42]` | Random seeds for pilot runs |

## Full Experiments

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `full_seeds` | list[int] | `[42, 123, 456]` | Random seeds for full experiment runs |

## Pipeline Control

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_parallel_tasks` | int | `4` | Maximum parallel experiment tasks |
| `experiment_timeout` | int | `300` | Experiment timeout in seconds |
| `review_enabled` | bool | `true` | Enable review stage |
| `idea_exp_cycles` | int | `6` | Maximum PIVOT count before forcing PROCEED |
| `debate_rounds` | int | `2` | Number of rounds in multi-agent debates |
| `writing_revision_rounds` | int | `2` | Maximum writing revision rounds after final review |

## Language

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `language` | string | `"en"` | Agent output language: `en` (English) or `zh` (Chinese) |

Controls the language for:
- **Console output**: Status messages, progress logs, skill invocation summaries
- **Research artifacts**: Proposals, experiment reports, research diary, outlines, reviews, all intermediate files
- **Log files**: Stage summaries, error messages, status updates

**Always in English regardless of this setting**:
- Code and code comments
- JSON keys
- References and citations
- Papers (paper.md) and LaTeX sources

```yaml
# English (default)
language: en

# Chinese
language: zh
```

## Writing Mode

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `writing_mode` | string | `"parallel"` | Writing strategy: `sequential` \| `parallel` \| `codex` |
| `codex_writing_model` | string | `""` | Codex model for writing (empty = use `~/.codex/config.toml` default) |

- **`sequential`**: Single agent writes all sections in order. Best consistency.
- **`parallel`**: 6 agents write sections simultaneously. Faster, but may have style inconsistencies.
- **`codex`**: GPT-5.4 writes the paper. Requires `codex_enabled: true`.

## Experiment Execution

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `experiment_mode` | string | `"ssh_mcp"` | Execution mode: `ssh_mcp` \| `server_codex` \| `server_claude` |
| `server_codex_path` | string | `"codex"` | Codex CLI path on remote server |
| `server_claude_path` | string | `"claude"` | Claude CLI path on remote server |

- **`ssh_mcp`**: Execute commands interactively via SSH MCP (default, recommended).
- **`server_codex`**: Upload experiment prompt, launch Codex CLI on server to execute locally.
- **`server_claude`**: Upload experiment prompt, launch Claude CLI on server to execute locally.

## Remote Environment

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `remote_env_type` | string | `"conda"` | Python environment type on server: `conda` \| `venv` |
| `remote_conda_path` | string | `""` | Custom conda path (empty = auto `{remote_base}/miniconda3/bin/conda`) |
| `iteration_dirs` | bool | `false` | Enable iteration subdirectory mode (`iter_NNN/` + `current` symlink) |

## Codex Integration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `codex_enabled` | bool | `true` | Enable GPT-5.4 independent cross-review |
| `codex_model` | string | `""` | Codex model (empty = use `~/.codex/config.toml` default) |

See [Codex Integration](codex-integration.md) for full setup instructions.

## Integrations

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lark_enabled` | bool | `true` | Enable Feishu/Lark cloud document sync |
| `evolution_enabled` | bool | `true` | Enable cross-project self-evolution engine |

## Model Routing

Advanced: control which Claude model each agent tier uses.

```yaml
model_tiers:
  heavy: "claude-opus-4-6"      # Synthesis, supervision, editing, review
  standard: "claude-opus-4-6"   # Literature, planning, experiments, writing
  light: "claude-sonnet-4-6"    # Debate, cross-review, section critique
```

### Agent-to-Tier Mapping

Override which tier specific agents use:

```yaml
agent_tier_map:
  synthesizer: heavy
  supervisor: heavy
  supervisor_decision: heavy
  editor: heavy
  final_critic: heavy
  critic: heavy
  reflection: heavy
  literature_researcher: standard
  optimist: light
  skeptic: light
  strategist: light
  section_critic: light
  idea_critique: light
  # All other agents default to "standard"
```

## Agent-Specific Settings

Fine-tune model parameters per pipeline phase:

```yaml
ideation:
  model: claude-opus-4-6
  max_tokens: 64000
  temperature: 0.9    # Higher creativity

planning:
  model: claude-opus-4-6
  max_tokens: 64000
  temperature: 0.7

experiment:
  model: claude-opus-4-6
  max_tokens: 64000
  temperature: 0.3    # Low temperature for precise code

writing:
  model: claude-opus-4-6
  max_tokens: 64000
  temperature: 0.5
```

## Full Example

```yaml
# GPU server
ssh_server: "my-gpu-box"
remote_base: "/data/sibyl"
max_gpus: 8
gpus_per_task: 2
remote_env_type: "conda"

# Pipeline
writing_mode: parallel
experiment_mode: ssh_mcp
codex_enabled: true
lark_enabled: false
debate_rounds: 3
idea_exp_cycles: 4

# GPU polling (shared server)
gpu_poll_enabled: true
gpu_free_threshold_mb: 4000
gpu_poll_interval_sec: 300

# Experiments
pilot_samples: 32
pilot_timeout: 900
full_seeds: [42, 123, 456, 789]
experiment_timeout: 600
```
