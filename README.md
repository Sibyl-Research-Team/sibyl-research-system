# Sibyl System

**Fully Autonomous AI Research System with Self-Evolution**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Inspired by the pioneering work of [The AI Scientist](https://github.com/SakanaAI/AI-Scientist) and [AutoResearch](https://github.com/karpathy/autoresearch), Sibyl takes the vision further by building natively on [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to fully leverage its agent ecosystem — skills, plugins, MCP servers, and multi-agent teams.

[中文文档](README_CN.md)

Sibyl is a **fully automated scientific discovery system** that autonomously drives ML research from literature survey to paper submission — and **evolves itself** by learning from every iteration. Unlike systems that merely assist human researchers, Sibyl operates as an **autonomous research organization**: 20+ specialized AI agents debate ideas, design and run GPU experiments, write papers, and critically review their own work, all without human intervention.

### What Makes Sibyl Different?

- **Claude Code Native** — Not a wrapper around API calls. Built directly on Claude Code's architecture (fork skills, agent teams, MCP tools), inheriting its full ecosystem: SSH remote execution, Playwright browser automation, Feishu/Lark cloud sync, and more.
- **Self-Evolving** — The system learns from its own research iterations. It classifies issues, tracks lesson effectiveness, deprioritizes what doesn't work, and automatically injects proven improvements into agent prompts. Each project makes the system smarter.
- **Fully Autonomous Loop** — Start a research topic, walk away. Sibyl handles literature search, multi-perspective idea debate, experiment planning, GPU-parallel execution, result analysis, paper writing, peer-level review, and quality-gated iteration — looping until the research meets publication standards.

---

## System Overview

Sibyl orchestrates 20+ AI agents through a **19-stage state-machine pipeline**, automatically completing literature survey, idea generation, experiment design & execution, result analysis, paper writing, and peer review. The system supports multi-round iterative optimization with built-in cross-project learning that continuously improves research quality.

![Sibyl System Architecture](image/sibyl_architecture.png)

### Core Features

- **19-Stage Research Pipeline**: End-to-end automation from literature search to camera-ready paper
- **Multi-Agent Collaboration**: 6-agent debate for idea generation, 6-agent result analysis, 6-agent parallel writing
- **GPU-Parallel Scheduling**: Topological sort + greedy assignment, automatic task dependency and GPU resource management
- **Iterative Optimization Loop**: Quality gate auto-decides whether to continue iterating or terminate, with PIVOT mechanism to switch research directions
- **Cross-Project Self-Evolution**: Automatically extracts lessons, tracks effectiveness, generates agent prompt improvements
- **Multi-Model Collaboration**: Claude Opus/Sonnet + GPT-5.4 (Codex) independent cross-review

## Pipeline

```
+== Research Iteration =============+  +== Paper Writing ====================+
|                                    |  |                                     |
|  Literature Search (arXiv + Web)   |  |  Outline                            |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Idea Debate (6 Agents)            |  |  Section Writing (seq/para/Codex)   |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Experiment Planning               |  |  Cross Review (6 Agents)            |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Pilot Experiments                 |  |  Integration & Editing              |
|       |                            |  |       |                             |
|       v                            |  |       v                             |
|  Full Experiments (GPU parallel)   |  |  Final Review (NeurIPS level)       |
|       |                            |  |       | fail --> back to edit (x2)  |
|       v                            |  |       v                             |
|  Result Debate (6 Agents)          |  |  LaTeX --> compile PDF              |
|       |                            |  |       |                             |
|       v                            |  +-------|---------+-------------------+
|  Decision                          |          |
|       | PIVOT --> back to Idea     |          |
|       | PROCEED                    |          v
+-------|-----------+----------------+  +== Review & Reflection ==============+
        |                               |                                     |
        +----------> Outline            |  Review (Critic+Supervisor+Codex)    |
                                        |       |                             |
                                        |       v                             |
                                        |  Reflection (lessons learned)       |
                                        |       |                             |
                                        |       v                             |
                                        |  Lark Sync (cloud docs)             |
                                        |       |                             |
                                        |       v                             |
                                        |  Quality Gate                       |
                                        |       | >= 8.0 & >= 2 iter --> DONE |
                                        |       | else --> next iteration     |
                                        |                                     |
                                        +-------------------------------------+
```

### Stage Details

| Stage | Description | Agent Mode |
|-------|-------------|-----------|
| `literature_search` | Dual-source survey via arXiv + Web | Single Agent |
| `idea_debate` | 6-perspective idea debate (Innovator / Pragmatist / Theorist / Contrarian / Interdisciplinary / Empiricist) | 6-Agent Team |
| `planning` | Design experiments, generate task_plan.json with dependencies | Single Agent |
| `pilot_experiments` | Small-scale feasibility validation | Single Agent |
| `experiment_cycle` | GPU-parallel full experiments, topologically sorted batch scheduling | Single Agent + GPU Scheduler |
| `result_debate` | 6-perspective result analysis (Optimist / Skeptic / Strategist / Methodologist / Comparativist / Revisionist) | 6-Agent Team |
| `experiment_decision` | Supervisor decision: PIVOT (change direction) or PROCEED | Single Agent |
| `writing_outline` | Generate paper outline | Single Agent |
| `writing_sections` | Write by section (sequential / parallel / Codex modes) | Configurable |
| `writing_critique` | 6-agent cross-review of each section | 6-Agent Parallel |
| `writing_integrate` | Editor integrates into complete paper | Single Agent |
| `writing_final_review` | NeurIPS/ICML-level final review (can loop for revision) | Single Agent |
| `writing_latex` | Convert to NeurIPS LaTeX format and compile PDF | Single Agent |
| `review` | Critic + Supervisor + Codex parallel review | Parallel Skills |
| `reflection` | Classify issues, generate improvement plan, record lessons | Single Agent |
| `lark_sync` | Sync research data to Feishu/Lark cloud docs | Single Agent |
| `quality_gate` | Evaluate completion (≥8.0 score and ≥2 iterations) | Automatic |

## Agent Roles

### Idea Generation Team

| Agent | Perspective | Responsibility |
|-------|------------|----------------|
| Innovator | Cross-domain innovation | Bold methodology transfer and novel combinations |
| Pragmatist | Engineering feasibility | Ensure ideas are implementable |
| Theorist | Mathematical foundations | Focus on theoretical guarantees and proofs |
| Contrarian | Challenge assumptions | Find counter-evidence and blind spots |
| Interdisciplinary | Analogical inspiration | Import methods from cognitive science, physics, biology |
| Empiricist | Experiment-first | Focus on reproducibility and data quality |

### Result Analysis Team

| Agent | Perspective | Responsibility |
|-------|------------|----------------|
| Optimist | Positive findings | Discover positive results and extension directions |
| Skeptic | Statistical rigor | Question statistical significance and confounders |
| Strategist | Next steps | Suggest resource allocation and research direction |
| Methodologist | Method review | Evaluate internal and external validity |
| Comparativist | SOTA benchmarking | Compare and position against existing best methods |
| Revisionist | Hypothesis revision | Reflect on and adjust hypotheses based on results |

### Model Tiers

| Tier | Model | Usage |
|------|-------|-------|
| Heavy | Opus 4.6 | Synthesis, supervision, editing, criticism, reflection |
| Standard | Opus 4.6 | Literature survey, planning, experiments, writing |
| Light | Sonnet 4.6 | Result debate, cross-review, section critique |
| Codex | GPT-5.4 High | Independent third-party review, optional writing mode |

## Self-Evolution System

Sibyl automatically learns from every research iteration, creating a feedback loop that continuously improves system performance:

```
Research Iteration
       |
       v
  Reflection Agent ──> Record outcome (issues + score + success patterns)
       |
       v
  Evolution Engine ──> Classify issues (7 categories)
       |                    ├── Time-weighted frequency analysis
       |                    ├── Effectiveness tracking (early vs late scores)
       |                    └── Success pattern extraction
       v
  Generate Overlays ──> Inject proven lessons into agent prompts
       |                    ├── Effective lessons: boosted priority
       |                    └── Ineffective lessons: 0.3x deprioritized
       v
  Self-Check ──> Detect anomalies
                    ├── Declining quality trend
                    ├── Recurring system errors
                    └── Ineffective lesson accumulation
```

**Issue Categories**: SYSTEM, EXPERIMENT, WRITING, ANALYSIS, PLANNING, PIPELINE, IDEATION — each routed to the relevant agents for targeted improvement.

## Project Structure

```
sibyl-system/
├── sibyl/                      # Core Python modules
│   ├── orchestrate.py          # State-machine orchestrator (19-stage pipeline)
│   ├── config.py               # Configuration (models/GPU/modes)
│   ├── workspace.py            # Workspace file & Git management
│   ├── gpu_scheduler.py        # GPU topological sort & parallel scheduling
│   ├── evolution.py            # Cross-project evolution engine
│   ├── reflection.py           # Iteration logging
│   └── prompts/                # 32 agent prompt templates
├── .claude/
│   ├── agents/                 # Agent tier definitions (heavy/standard/light)
│   └── skills/sibyl-*/         # 30+ Fork Skills (isolated context execution)
├── plugin/commands/            # Claude Code plugin commands
├── workspaces/                 # Research project workspaces
├── tests/                      # Unit tests (~320 tests)
└── requirements.txt            # Dependencies (PyYAML, rich)
```

### Workspace Structure

Each research project has an independent filesystem under `workspaces/<project>/`:

```
workspaces/<project>/
├── status.json                 # Orchestrator state (stage/iteration/score)
├── config.yaml                 # Project-level config overrides
├── topic.txt / spec.md         # Research topic & requirements spec
├── context/literature.md       # Literature review
├── idea/                       # Proposals, alternatives, debate records
├── plan/                       # Experiment plan, task_plan.json
├── exp/                        # Code, results, logs, GPU progress
├── writing/                    # Outline, sections, reviews, full paper, LaTeX
├── logs/                       # Iteration archives, research diary
└── lark_sync/                  # Feishu/Lark sync registry
```

## Quick Start

### Prerequisites

- Python 3.12+, Node.js 18+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- GPU server (SSH accessible)
- `ANTHROPIC_API_KEY` environment variable
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` environment variable

### Install & Run

```bash
git clone https://github.com/Sibyl-Research/sibyl-research-system.git
cd sibyl-research-system
chmod +x setup.sh && ./setup.sh

# Load plugin
claude --plugin-dir ./plugin

# In Claude Code:
/sibyl-research:init              # Create a research project
/sibyl-research:start <project>   # Start autonomous loop
```

See **[Getting Started Guide](docs/getting-started.md)** for the full walkthrough.

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Full installation and first-run guide |
| [Configuration](docs/configuration.md) | All 35+ config options reference |
| [MCP Servers](docs/mcp-servers.md) | Third-party MCP dependencies & setup |
| [SSH & GPU Setup](docs/ssh-gpu-setup.md) | GPU server configuration |
| [Plugin Commands](docs/plugin-commands.md) | All 12 plugin commands reference |
| [Codex Integration](docs/codex-integration.md) | GPT-5.4 cross-review setup |
| [Feishu/Lark Setup](docs/feishu-lark-setup.md) | Cloud document sync |
| [Architecture](docs/architecture.md) | System internals for contributors |

## Third-Party Dependencies

### MCP Servers

| Server | Required | Purpose | Source |
|--------|----------|---------|--------|
| SSH MCP | Yes | Remote GPU execution | Claude Code built-in |
| arXiv MCP | Yes | Paper search | `pip install arxiv-mcp-server` |
| Google Scholar MCP | Recommended | Citation search | Community |
| Codex MCP | Optional | GPT-5.4 review | [OpenAI Codex CLI](https://github.com/openai/codex) |
| Lark MCP | Optional | Feishu Bitable/IM | `@larksuiteoapi/lark-mcp` |
| Feishu MCP | Optional | Feishu documents | Community |
| bioRxiv MCP | Optional | Biology preprints | Community |

See **[MCP Servers Guide](docs/mcp-servers.md)** for installation and `~/.mcp.json` configuration.

### Python Dependencies

- **PyYAML** >= 6.0 — Config file parsing
- **rich** >= 13.0 — Terminal formatted output

### Optional Tools

- [OpenAI Codex CLI](https://github.com/openai/codex) — Independent cross-review (`codex_enabled: true`)
- [Ralph Loop](https://github.com/anthropics/claude-code) — Autonomous iteration loop (Claude Code plugin)

## Key Mechanisms

### GPU Parallel Scheduling

The experiment stage reads `task_plan.json`, topologically sorts tasks by dependencies, then greedily assigns parallel execution based on available GPUs:

```json
{
  "tasks": [
    {"id": "train_baseline", "depends_on": [], "gpu_count": 2, "estimated_minutes": 60},
    {"id": "train_model_a", "depends_on": ["train_baseline"], "gpu_count": 1, "estimated_minutes": 90},
    {"id": "train_model_b", "depends_on": ["train_baseline"], "gpu_count": 1, "estimated_minutes": 90},
    {"id": "ablation", "depends_on": ["train_model_a", "train_model_b"], "gpu_count": 1, "estimated_minutes": 30}
  ]
}
```

### Cross-Project Self-Evolution

The system automatically extracts lessons from each iteration, tracks effectiveness, and injects verified improvements into agent prompts:

1. **Record**: After each reflection, classify issues (7 categories) and success patterns
2. **Analyze**: Aggregate frequency with time decay (30-day half-life)
3. **Evaluate**: Compare early vs late scores, mark lesson effectiveness (requires >= 4 occurrences)
4. **Apply**: Generate agent-specific prompt overlays; ineffective lessons deprioritized (x0.3)
5. **Self-Check**: Detect quality decline, recurring errors, and ineffective lesson accumulation

### PIVOT Mechanism

When experiment results are unsatisfactory, the supervisor decision agent can trigger PIVOT:

- Analyze whether results support the original hypothesis
- Evaluate whether continued investment is worthwhile
- If PIVOT: roll back to idea debate stage with alternative proposals
- Maximum 6 PIVOT cycles (configurable)

## Comparison

| Feature | Sibyl System | [AI Scientist](https://github.com/SakanaAI/AI-Scientist) | [AutoResearch](https://github.com/karpathy/autoresearch) |
|---------|-------------|-------------|--------------|
| Architecture | Claude Code native (skills, teams, MCP) | API wrapper | Single-file script |
| Agent count | 20+ specialized agents | Single LLM | Single agent |
| Idea generation | 6-agent multi-perspective debate | LLM brainstorming | N/A |
| Experiment execution | GPU-parallel with topo-sort scheduling | Template-based | Single-GPU loop |
| Paper writing | Multi-agent write + review + revise | LLM generation | N/A |
| Self-evolution | Cross-project lesson learning | None | None |
| Quality control | Multi-round review + quality gate | Automated review | Metric-based |
| Human intervention | Fully autonomous | Minimal | Minimal |

## License

MIT License
