# Sibyl Research System Setup Guide (for Claude)

This document is the **single source of truth** for configuring Sibyl Research System. It is designed for Claude Code to read and execute automatically. When a user says "help me set up Sibyl Research System" or "configure Sibyl for me", follow this guide step by step.

**Approach**: Check the current state first, then only fix what's missing. Ask the user for information you cannot detect automatically (GPU server IP, username, etc.). Report progress after each step.

**Important setup preference**: For MCP servers, prefer `claude mcp add --scope local ...` unless the user explicitly wants a broader scope. Manual JSON editing is a fallback only for users already managing Claude Code MCP configs that way.

---

## Step 1: Python Environment

**Goal**: `.venv/` exists with Python 3.12+ and core dependencies installed.

**Check**:
```bash
# Verify .venv exists and has correct Python version
.venv/bin/python3 --version
```

**Fix if missing**:
```bash
# Find Python 3.12+
python3.12 -m venv .venv   # preferred
# or: python3 -m venv .venv  (verify version >= 3.12 first)

.venv/bin/pip install -e .
```

**Verify**:
```bash
.venv/bin/python3 -c "from sibyl.config import Config; print('OK')"
```

---

## Step 2: Environment Variables

**Goal**: `ANTHROPIC_API_KEY` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` are set.

**Check**: These are shell environment variables. You can check if they're set in the current session.

**Fix if missing**:
- `ANTHROPIC_API_KEY`: Ask the user for their Anthropic API key. Add to `~/.zshrc` (macOS) or `~/.bashrc` (Linux).
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`: Add `export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` to the same shell rc file.

**Important**: After adding to rc file, remind the user to restart their shell or `source` the file.

---

## Step 3: SSH MCP Server

**Goal**: SSH MCP server is registered in Claude Code with the correct GPU server connection.

**Source**: [`@fangjunjie/ssh-mcp-server`](https://github.com/classfang/ssh-mcp-server) — npm package, runs via `npx`.

**Check**:
```bash
# Check if already configured
claude mcp list 2>/dev/null | grep ssh-mcp-server
```

**If not configured — ask the user**:
1. GPU server IP or hostname
2. SSH port (default: 22)
3. SSH username
4. SSH private key path (default: `~/.ssh/id_ed25519`)

**Configure** (preferred):
```bash
claude mcp add --scope local ssh-mcp-server -- npx -y @fangjunjie/ssh-mcp-server \
  --host <GPU_HOST> --port <SSH_PORT> --username <SSH_USER> \
  --privateKey <SSH_KEY_PATH>
```

Use `--scope user` instead only if the user wants the same SSH MCP entry available across multiple repos.

**Manual JSON fallback**:
If the user already manages MCP servers via JSON, update the existing Claude Code MCP config instead of creating a second source of truth. Common locations are project `.mcp.json` or older user-level `~/.mcp.json`.

```json
{
  "mcpServers": {
    "ssh-mcp-server": {
      "command": "npx",
      "args": ["-y", "@fangjunjie/ssh-mcp-server",
               "--host", "<GPU_HOST>",
               "--port", "<SSH_PORT>",
               "--username", "<SSH_USER>",
               "--privateKey", "<SSH_KEY_PATH>"]
    }
  }
}
```

**Critical**: The server name **must** be `"ssh-mcp-server"`. Agent prompts reference `mcp__ssh-mcp-server__execute-command`.

**Verify**: After configuring, the user needs to restart Claude Code for the MCP server to load. Then:
```
mcp__ssh-mcp-server__list-servers
```
Should return the configured server.

---

## Step 4: arXiv MCP Server

**Goal**: arXiv MCP server is installed and configured to use Sibyl's local virtual environment Python.

**Source**: [`arxiv-mcp-server`](https://github.com/blazickjp/arxiv-mcp-server) — Python package.

**Check**:
```bash
.venv/bin/python3 -m arxiv_mcp_server --help 2>/dev/null
# or
.venv/bin/pip show arxiv-mcp-server 2>/dev/null
```

**Fix if missing**:
```bash
.venv/bin/pip install arxiv-mcp-server
```

**Configure** (preferred):
Use the repo's absolute `.venv/bin/python3` path, not bare `python`, so Claude Code always launches the interpreter that actually has `arxiv-mcp-server` installed.

```bash
claude mcp add --scope local arxiv-mcp-server -- /ABSOLUTE/PATH/TO/sibyl-research-system/.venv/bin/python3 -m arxiv_mcp_server
```

Replace `/ABSOLUTE/PATH/TO/sibyl-research-system` with the actual clone path.

**Manual JSON fallback**:
If the user already manages MCP servers via JSON, update the existing MCP config with the same absolute interpreter path:

```json
{
  "mcpServers": {
    "arxiv-mcp-server": {
      "command": "/ABSOLUTE/PATH/TO/sibyl-research-system/.venv/bin/python3",
      "args": ["-m", "arxiv_mcp_server"],
      "env": {}
    }
  }
}
```

**Critical**: The server name **must** be `"arxiv-mcp-server"`. Agent prompts reference `mcp__arxiv-mcp-server__search_papers`.

---

## Step 5: Sibyl Config File

**Goal**: `config.yaml` exists at project root with GPU server settings.

**Check**:
```bash
cat config.yaml 2>/dev/null
```

**Create if missing** — ask the user for:
1. `ssh_server`: The server connection name configured in Step 3 (usually `"default"` if using `ssh-mcp-server --host ...` directly, or a host alias if the MCP setup resolves one)
2. `remote_base`: Base directory on GPU server (e.g., `/home/username/sibyl_system`)
3. `max_gpus`: Number of GPUs to use (e.g., 4)
4. `language`: Control-plane output language, `"zh"` (default) or `"en"`; paper drafting and LaTeX remain English
5. `codex_enabled`: Keep `false` unless Codex MCP and `OPENAI_API_KEY` are already configured and the user explicitly wants Codex review enabled now

**Write** `config.yaml`:
```yaml
# Sibyl Research System - Machine-level config (git-ignored)
ssh_server: "<SSH_SERVER_NAME>"
remote_base: "<REMOTE_BASE>"
max_gpus: <MAX_GPUS>
language: zh
codex_enabled: false
# Change language to "en" only if the user wants English control-plane output.
# remote_conda_env_name: base   # optional: reuse an existing remote conda env instead of sibyl_<project>
```

**Note**: `ssh_server` value depends on how SSH MCP was configured:
- If using `@fangjunjie/ssh-mcp-server` with `--host` args: use `"default"` (the direct connection exposed by the MCP server)
- If the user's MCP setup resolves a named SSH host alias: use that connection name instead

---

## Step 6: tmux (Strongly Recommended)

**Goal**: tmux is installed for persistent sessions and Sentinel auto-recovery.

**Check**:
```bash
tmux -V
```

**Fix if missing**:
```bash
# macOS
brew install tmux

# Linux (Debian/Ubuntu)
sudo apt install tmux

# Linux (RHEL/CentOS)
sudo yum install tmux
```

**Tell the user**: Always start Sibyl inside a tmux session. This enables the Sentinel watchdog to automatically restart Claude Code if it crashes, goes idle, or gets interrupted during long-running experiments.

```bash
tmux new -s sibyl
```

To detach: `Ctrl+B` then `D`. To reattach: `tmux attach -t sibyl`.

---

## Step 7: Plugin Registration

**Goal**: User knows how to launch Claude Code with Sibyl plugin inside tmux.

**Tell the user**:
```bash
# First, start a tmux session
tmux new -s sibyl

# Then launch Claude Code with Sibyl plugin
# --dangerously-skip-permissions is strongly recommended for fully autonomous operation
claude --plugin-dir /path/to/sibyl-research-system/plugin --dangerously-skip-permissions
```

**Important**: Explain to the user that `--dangerously-skip-permissions` is strongly recommended because Sibyl involves hundreds of tool calls per iteration (file I/O, SSH, MCP, sub-agents). Without it, each call requires manual approval, making autonomous research impossible. However, ⚠️ warn them that this grants unrestricted execution — they should only use it on dedicated research machines and consider container/VM isolation.

Replace `/path/to/sibyl-research-system` with the actual clone path.

**Verify**: After launching, type `/sibyl-research:status` — if it runs, the plugin is loaded.

---

## Step 8: Remote Server Initialization (Optional)

**Goal**: Remote server has correct directory structure and Python environment.

**Only needed for first-time setup on a new GPU server.**

Run inside Claude Code after plugin is loaded:
```
/sibyl-research:migrate-server <project-name>
```

Or manually on the server:
```bash
ssh <gpu-server>
mkdir -p ~/sibyl_system/{projects,shared/{datasets,checkpoints}}
echo '{}' > ~/sibyl_system/shared/registry.json

# Create conda env (if using conda)
conda create -n sibyl_<project> python=3.12 -y
conda activate sibyl_<project>
pip install torch transformers datasets matplotlib numpy scikit-learn
```

---

## Step 9: Verify Complete Setup

Run these checks to confirm everything works:

1. **Python env**: `.venv/bin/python3 -c "from sibyl.config import Config; print('✓ Python OK')"`
2. **Config file**: `cat config.yaml` — fresh installs should show `ssh_server`, `remote_base`, `max_gpus`, `language`, and `codex_enabled: false`
3. **MCP servers**: Restart Claude Code and check that `mcp__ssh-mcp-server__list-servers` and `mcp__arxiv-mcp-server__search_papers` are available
4. **Codex (recommended on your own machine once installed)**: after installing Codex MCP and setting `OPENAI_API_KEY`, flip `codex_enabled: true` in your local `config.yaml` and verify `mcp__codex__codex` is available. That file exists in your working tree, but Git does not track or commit it
5. **tmux**: `tmux -V` returns a version — needed for Sentinel watchdog auto-recovery
6. **Plugin**: `/sibyl-research:status` runs without error

If all pass, remind the user to launch inside tmux with `--dangerously-skip-permissions` for fully autonomous operation, and start researching:
```
/sibyl-research:init          # Create a project
/sibyl-research:start <name>  # Start autonomous research
```

---

## Optional MCP Servers

These are not required but enhance functionality. Configure only if the user wants them.

| Server | Purpose | Install | Config name |
|--------|---------|---------|-------------|
| [Google Scholar](https://github.com/JackKuo666/Google-Scholar-MCP-Server) | Academic search | `git clone` + `pip install -r requirements.txt` | `"google-scholar"` |
| [Codex](https://github.com/openai/codex) | GPT-5.4 cross-review | `npm install -g @openai/codex` | `"codex"` |
| [Lark MCP](https://github.com/larksuite/lark-openapi-mcp) | Feishu Bitable/IM | `npm install -g @larksuiteoapi/lark-mcp` | `"lark"` |
| [Feishu MCP](https://github.com/cso1z/Feishu-MCP) | Feishu documents | `npm install -g feishu-mcp` | `"feishu"` |
| [bioRxiv](https://github.com/JackKuo666/bioRxiv-MCP-Server) | Biology preprints | `pip install biorxiv-mcp-server` | `"claude_ai_bioRxiv"` |
| [Playwright](https://github.com/microsoft/playwright-mcp) | Web browsing | `npm install -g @playwright/mcp` | `"playwright"` |

See [MCP Servers Guide](mcp-servers.md) for full configuration details of each.

---

## Troubleshooting

**"Permission denied" on SSH**: Check that the private key path in ssh-mcp-server args is correct and the key has been added to the server's `~/.ssh/authorized_keys`.

**MCP tools not found after config**: MCP servers only load when Claude Code starts. The user must restart Claude Code after adding or editing MCP servers, whether they used `claude mcp add` or manual JSON.

**"arxiv_mcp_server" import error**: The interpreter in the MCP config must be the one with `arxiv-mcp-server` installed. For Sibyl, prefer the full repo venv path such as `/path/to/sibyl-research-system/.venv/bin/python3`.

**Config not taking effect**: Sibyl loads config in order: code defaults → root `config.yaml` → project `config.yaml`. Check that the file is in the right location and has valid YAML syntax.
