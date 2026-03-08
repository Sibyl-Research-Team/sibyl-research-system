# Sibyl System Setup Guide (for Claude)

This document is the **single source of truth** for configuring Sibyl System. It is designed for Claude Code to read and execute automatically. When a user says "help me set up Sibyl" or "configure Sibyl for me", follow this guide step by step.

**Approach**: Check the current state first, then only fix what's missing. Ask the user for information you cannot detect automatically (GPU server IP, username, etc.). Report progress after each step.

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

**Goal**: SSH MCP server configured in `~/.mcp.json` (or Claude Code managed MCP) with correct GPU server connection.

**Source**: [`@fangjunjie/ssh-mcp-server`](https://github.com/classfang/ssh-mcp-server) — npm package, runs via `npx`.

**Check**:
```bash
# Check if already configured
cat ~/.mcp.json 2>/dev/null | python3 -m json.tool | grep -A5 "ssh-mcp-server"

# Also check Claude-managed MCP (added via `claude mcp add`)
claude mcp list 2>/dev/null | grep ssh
```

**If not configured — ask the user**:
1. GPU server IP or hostname
2. SSH port (default: 22)
3. SSH username
4. SSH private key path (default: `~/.ssh/id_ed25519`)

**Configure** (two options):

Option A — via `~/.mcp.json` (add to existing or create new):
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

Option B — via Claude CLI:
```bash
claude mcp add ssh-mcp-server -- npx -y @fangjunjie/ssh-mcp-server \
  --host <GPU_HOST> --port <SSH_PORT> --username <SSH_USER> \
  --privateKey <SSH_KEY_PATH>
```

**Critical**: The server name **must** be `"ssh-mcp-server"`. Agent prompts reference `mcp__ssh-mcp-server__execute-command`.

**Verify**: After configuring, the user needs to restart Claude Code for the MCP server to load. Then:
```
mcp__ssh-mcp-server__list-servers
```
Should return the configured server.

---

## Step 4: arXiv MCP Server

**Goal**: arXiv MCP server installed and configured.

**Source**: [`arxiv-mcp-server`](https://github.com/blazickjp/arxiv-mcp-server) — Python package.

**Check**:
```bash
.venv/bin/python3 -m arxiv_mcp_server --help 2>/dev/null
# or
pip show arxiv-mcp-server 2>/dev/null
```

**Fix if missing**:
```bash
.venv/bin/pip install arxiv-mcp-server
```

**Configure** — add to `~/.mcp.json`:
```json
{
  "mcpServers": {
    "arxiv-mcp-server": {
      "command": "python",
      "args": ["-m", "arxiv_mcp_server"],
      "env": {}
    }
  }
}
```

Or via CLI:
```bash
claude mcp add arxiv-mcp-server -- python -m arxiv_mcp_server
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
1. `ssh_server`: The server connection name configured in Step 3 (usually `"default"` if using ssh-mcp-server args directly, or a hostname if using `~/.ssh/config`)
2. `remote_base`: Base directory on GPU server (e.g., `/home/username/sibyl_system`)
3. `max_gpus`: Number of GPUs to use (e.g., 4)
4. `language`: Output language, `"en"` (default) or `"zh"`

**Write** `config.yaml`:
```yaml
# Sibyl System - Machine-level config (git-ignored)
ssh_server: "<SSH_SERVER_NAME>"
remote_base: "<REMOTE_BASE>"
max_gpus: <MAX_GPUS>
# language: en        # uncomment and change to "zh" for Chinese
```

**Note**: `ssh_server` value depends on how SSH MCP was configured:
- If using `@fangjunjie/ssh-mcp-server` with `--host` args: use `"default"` (the server auto-names the connection "default")
- If using `~/.ssh/config` Host entries: use the Host name

---

## Step 6: Plugin Registration

**Goal**: User knows how to launch Claude Code with Sibyl plugin.

**Tell the user**:
```bash
# Option 1: Specify at launch (recommended for first time)
claude --plugin-dir /path/to/sibyl-research-system/plugin

# Option 2: Persist in settings (edit ~/.claude/settings.json)
{
  "pluginDirs": ["/path/to/sibyl-research-system/plugin"]
}
```

Replace `/path/to/sibyl-research-system` with the actual clone path.

**Verify**: After launching, type `/sibyl-research:status` — if it runs, the plugin is loaded.

---

## Step 7: Remote Server Initialization (Optional)

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

## Step 8: Verify Complete Setup

Run these checks to confirm everything works:

1. **Python env**: `.venv/bin/python3 -c "from sibyl.config import Config; print('✓ Python OK')"`
2. **Config file**: `cat config.yaml` — should show ssh_server, remote_base, max_gpus
3. **MCP servers**: Restart Claude Code and check that `mcp__ssh-mcp-server__list-servers` and `mcp__arxiv-mcp-server__search_papers` are available
4. **Plugin**: `/sibyl-research:status` runs without error

If all pass, the user can start researching:
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

**MCP tools not found after config**: MCP servers only load when Claude Code starts. The user must restart Claude Code after modifying `~/.mcp.json`.

**"arxiv_mcp_server" import error**: The `python` in the MCP config must be the one with `arxiv-mcp-server` installed. If using a venv, change `"command"` to the full path: `.venv/bin/python`.

**Config not taking effect**: Sibyl loads config in order: code defaults → root `config.yaml` → project `config.yaml`. Check that the file is in the right location and has valid YAML syntax.
