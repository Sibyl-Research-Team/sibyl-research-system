# Getting Started

Complete installation and first-run guide for Sibyl Research System.

> **Fastest path**: Open the cloned repo in Claude Code and say *"Read docs/setup-guide.md and help me set up Sibyl"*. Claude will automatically check your environment and configure everything, only asking for info it can't detect. See [setup-guide.md](setup-guide.md) for the full checklist Claude follows.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | Used for orchestrator and experiments |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | Latest | Core runtime for all agents |
| Node.js | 18+ | Required for npm-based MCP servers |
| Git | Any | Version control for workspaces |
| GPU Server | SSH accessible | For experiment execution |

### API Keys

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key, required by Claude Code CLI |
| `OPENAI_API_KEY` | If `codex_enabled: true` | OpenAI API key for Codex cross-review |

### Environment Variable

Agent team features require:

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

Add this to your `~/.zshrc` or `~/.bashrc` for persistence.

## Installation

### Option 1: Automated Setup

```bash
git clone https://github.com/Sibyl-Research/sibyl-research-system.git
cd sibyl-research-system
chmod +x setup.sh && ./setup.sh
```

`setup.sh` will:
- Find Python 3.12+ and create a virtual environment (`.venv/`)
- Install core dependencies (PyYAML, rich)
- Install required MCP servers (arXiv)
- Interactively configure SSH MCP server (GPU server host, user, SSH key)
- Create `~/.mcp.json` with SSH MCP + arXiv MCP configured
- Create `config.yaml` with GPU server settings
- Check for required environment variables (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`)

### Option 2: Manual Setup

```bash
git clone https://github.com/Sibyl-Research/sibyl-research-system.git
cd sibyl-research-system

# Create Python virtual environment
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### MCP Server Setup

Sibyl relies on several MCP servers. `setup.sh` configures the required ones automatically. See [MCP Servers](mcp-servers.md) for full installation and configuration instructions.

**Required (configured by setup.sh):**
- [SSH MCP](https://github.com/classfang/ssh-mcp-server) — remote GPU execution (`@fangjunjie/ssh-mcp-server`)
- [arXiv MCP](https://github.com/blazickjp/arxiv-mcp-server) — literature search (`pip install arxiv-mcp-server`)

**Recommended:**
- [Google Scholar MCP](https://github.com/JackKuo666/Google-Scholar-MCP-Server) — academic search
- [Codex MCP](https://github.com/openai/codex) — GPT-5.4 independent cross-review

**Optional:**
- [Lark](https://github.com/larksuite/lark-openapi-mcp)/[Feishu](https://github.com/cso1z/Feishu-MCP) MCP — cloud document sync
- [bioRxiv MCP](https://github.com/JackKuo666/bioRxiv-MCP-Server) — biology preprints
- [Playwright MCP](https://github.com/microsoft/playwright-mcp) — web browsing

### GPU Server Setup

`setup.sh` handles SSH MCP configuration interactively. For server-side setup (conda environments, GPU polling, shared resources), see [SSH & GPU Setup](ssh-gpu-setup.md).

## Load Plugin

Sibyl is provided as a **Claude Code Plugin**:

```bash
# Option 1: Specify plugin dir at startup (recommended with --dangerously-skip-permissions)
claude --plugin-dir /path/to/sibyl-research-system/plugin --dangerously-skip-permissions

# Option 2: Persist in Claude Code settings
# Edit ~/.claude/settings.json:
{
  "pluginDirs": ["/path/to/sibyl-research-system/plugin"]
}
# Then launch with: claude --dangerously-skip-permissions
```

Replace `/path/to/sibyl-research-system` with your actual local path.

> **`--dangerously-skip-permissions` is strongly recommended** for Sibyl to function as designed. Without it, Claude Code will prompt for permission on every tool call — file reads, SSH commands, MCP calls, agent spawns — making autonomous multi-stage research impractical (hundreds of manual approvals per iteration).
>
> **⚠️ Security trade-off**: This flag grants Claude Code unrestricted access to execute commands, read/write files, and call MCP tools without confirmation. Only use it on machines dedicated to research, and consider running inside a container or VM. Do not use on systems with sensitive credentials or data outside the project scope.

**Verify plugin loaded:** After starting Claude Code, type `/sibyl-research:status` — if the plugin is loaded, it will execute the status command.

## First Research Project

Need a realistic end-to-end smoke test first? Use the fixed tiny demo in [../demos/remote_parallel_smoke/README.md](../demos/remote_parallel_smoke/README.md). It scaffolds a project that exercises remote SSH execution, GPU polling, experiment monitoring, parallel tasks, and the writing/LaTeX chain against pre-existing remote checkpoints.

### 1. Initialize

```bash
/sibyl-research:init
```

This interactive command will:
- Ask for your research topic
- Generate a `spec.md` requirements file
- Create a workspace under `workspaces/<project>/`

### 2. Configure

Create a root-level config file for machine-level defaults (git-ignored):

```bash
cp config.example.yaml config.yaml
```

Edit the key fields:
```yaml
ssh_server: "your-gpu-server"       # Must match Host in ~/.ssh/config
remote_base: "/home/you/sibyl"      # Base directory on GPU server
max_gpus: 4                         # Max GPUs to use
```

You can also create project-specific overrides in `workspaces/<project>/config.yaml` — these take priority over root config. See [Configuration Reference](configuration.md) for all options.

### 3. Start Research

```bash
/sibyl-research:start <project>
```

This enters the autonomous research loop. The system will:
1. Search literature (arXiv + Web)
2. Generate and debate ideas (6-agent team)
3. Plan and execute experiments (GPU-parallel)
4. Analyze results (6-agent debate)
5. Write and review paper (multi-agent)
6. Iterate until quality gate passes

### 4. Monitor Progress

```bash
/sibyl-research:status          # View all projects
/sibyl-research:debug <project> # Single-step mode
```

## All Plugin Commands

See [Plugin Commands Reference](plugin-commands.md) for the complete list of 12 commands.

## Next Steps

- [Configuration Reference](configuration.md) — All 35+ config options
- [MCP Servers](mcp-servers.md) — Install and configure MCP dependencies
- [SSH & GPU Setup](ssh-gpu-setup.md) — GPU server configuration
- [Codex Integration](codex-integration.md) — GPT-5.4 cross-review setup
- [Feishu/Lark Setup](feishu-lark-setup.md) — Cloud document sync
- [Architecture](architecture.md) — System internals for contributors
