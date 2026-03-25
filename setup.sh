#!/bin/bash
# Sibyl Research System - Setup Script
# Installs Python environment, dependencies, and configures MCP servers

set -e
echo "=== Sibyl Research System Setup ==="

cd "$(dirname "$0")"
REPO_ROOT="$(pwd -P)"

detect_shell_rc() {
    case "${SHELL:-}" in
        */zsh)
            echo "${ZDOTDIR:-$HOME}/.zshrc"
            ;;
        */bash)
            echo "$HOME/.bashrc"
            ;;
        *)
            if [ -f "${ZDOTDIR:-$HOME}/.zshrc" ] || [ ! -f "$HOME/.bashrc" ]; then
                echo "${ZDOTDIR:-$HOME}/.zshrc"
            else
                echo "$HOME/.bashrc"
            fi
            ;;
    esac
}

configure_sibyl_root() {
    local shell_rc="$1"
    local action

    action=$("$PY" - "$shell_rc" "$REPO_ROOT" <<'PY'
from pathlib import Path
import re
import sys

rc_path = Path(sys.argv[1]).expanduser()
repo_root = sys.argv[2]
target_line = f'export SIBYL_ROOT="{repo_root}"'

if rc_path.exists():
    text = rc_path.read_text(encoding="utf-8")
else:
    text = ""

existing = re.search(r"(?m)^[ \t]*export[ \t]+SIBYL_ROOT=(.*)$", text)
if existing:
    current_line = existing.group(0).strip()
    if current_line == target_line:
        print("already_set")
    else:
        updated = re.sub(
            r"(?m)^[ \t]*export[ \t]+SIBYL_ROOT=.*$",
            target_line,
            text,
            count=1,
        )
        rc_path.parent.mkdir(parents=True, exist_ok=True)
        rc_path.write_text(updated, encoding="utf-8")
        print("updated")
else:
    suffix = "" if not text or text.endswith("\n") else "\n"
    block = f"{suffix}\n# Added by Sibyl setup\n{target_line}\n"
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(text + block, encoding="utf-8")
    print("added")
PY
)

    case "$action" in
        added)
            echo "  ✓ Added SIBYL_ROOT to $shell_rc"
            ;;
        updated)
            echo "  ✓ Updated SIBYL_ROOT in $shell_rc"
            ;;
        already_set)
            echo "  ✓ SIBYL_ROOT already configured in $shell_rc"
            ;;
    esac
}

# ---------- Python environment ----------
# Prefer python3.12; fall back to python3
PY=""
if command -v python3.12 &>/dev/null; then
    PY="python3.12"
elif command -v python3 &>/dev/null; then
    PY="python3"
else
    echo "ERROR: Python 3.12+ is required but not found."
    echo "Install via: brew install python@3.12  (macOS) or apt install python3.12 (Linux)"
    exit 1
fi

PY_VER=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PY -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PY -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
    echo "ERROR: Python 3.12+ is required, found $PY_VER"
    echo "Install via: brew install python@3.12  (macOS) or apt install python3.12 (Linux)"
    exit 1
fi

echo "Using $PY ($PY_VER)"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PY -m venv .venv
fi
source .venv/bin/activate
VENV_PY="$PWD/.venv/bin/python3"

echo "Installing core dependencies..."
pip install -e . 2>&1 | tail -3

# ---------- MCP servers (Python-based) ----------
echo ""
echo "Installing Python MCP servers..."
pip install arxiv-mcp-server 2>/dev/null && echo "  ✓ arxiv-mcp-server" || echo "  ✗ arxiv-mcp-server (install manually: .venv/bin/pip install arxiv-mcp-server)"

# ---------- tmux check ----------
echo ""
if command -v tmux &>/dev/null; then
    TMUX_VER=$(tmux -V 2>/dev/null || echo "unknown")
    echo "tmux detected ($TMUX_VER) — good for persistent sessions + Sentinel auto-recovery"
else
    echo "⚠  tmux not found. Strongly recommended for persistent sessions and Sentinel watchdog."
    echo "   Install: brew install tmux (macOS) / apt install tmux (Linux)"
fi

# ---------- Node.js check ----------
echo ""
HAS_NODE=false
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    echo "Node.js $NODE_VER detected"
    HAS_NODE=true
else
    echo "⚠  Node.js not found. Required for SSH MCP and optional Lark/Codex MCP servers."
    echo "   Install via: brew install node  (macOS) or https://nodejs.org/"
fi

# ---------- MCP configuration ----------
echo ""
echo "Configuring MCP servers..."

# Check if claude CLI is available
HAS_CLAUDE=false
if command -v claude &>/dev/null; then
    HAS_CLAUDE=true
    echo "  Claude Code CLI detected — using 'claude mcp add --scope local' (preferred)"
fi

# Warn about legacy ~/.mcp.json
if [ -f "$HOME/.mcp.json" ]; then
    echo ""
    echo "  ⚠ Legacy ~/.mcp.json detected."
    echo "    Consider migrating to 'claude mcp add --scope local' for repo-scoped config."
    echo "    See docs/mcp-servers.md for details."
fi

# --- SSH MCP Server ---
SSH_HOST=""
SSH_PORT="22"
SSH_USER=""
SSH_KEY="$HOME/.ssh/id_ed25519"
COMPUTE_BACKEND="local"

echo ""
echo "SSH MCP Server (@fangjunjie/ssh-mcp-server) — required for remote GPU experiments"
echo "  GitHub: https://github.com/classfang/ssh-mcp-server"
echo "  (Leave empty to skip if using local GPUs only)"
echo ""
read -p "  GPU server hostname or IP: " SSH_HOST
if [ -n "$SSH_HOST" ]; then
    read -p "  SSH port [22]: " input_port
    SSH_PORT="${input_port:-22}"
    read -p "  SSH username: " SSH_USER
    read -p "  SSH private key path [$SSH_KEY]: " input_key
    SSH_KEY="${input_key:-$SSH_KEY}"
    COMPUTE_BACKEND="ssh"
fi

echo ""
if [ "$HAS_CLAUDE" = true ]; then
    # Preferred: use claude mcp add --scope local
    if [ -n "$SSH_HOST" ] && [ -n "$SSH_USER" ]; then
        claude mcp add --scope local ssh-mcp-server -- npx -y @fangjunjie/ssh-mcp-server \
            --host "$SSH_HOST" --port "$SSH_PORT" --username "$SSH_USER" \
            --privateKey "$SSH_KEY" 2>/dev/null \
            && echo "  ✓ SSH MCP configured ($SSH_USER@$SSH_HOST:$SSH_PORT)" \
            || echo "  ✗ SSH MCP failed — run manually: claude mcp add --scope local ssh-mcp-server -- ..."
    else
        echo "  ⚠ SSH MCP skipped — configure later if using remote GPUs"
    fi

    claude mcp add --scope local arxiv-mcp-server -- "$VENV_PY" -m arxiv_mcp_server 2>/dev/null \
        && echo "  ✓ arXiv MCP configured" \
        || echo "  ✗ arXiv MCP failed — run manually: claude mcp add --scope local arxiv-mcp-server -- $VENV_PY -m arxiv_mcp_server"
else
    # Fallback: create project-level .mcp.json
    if [ -f ".mcp.json" ]; then
        echo "  .mcp.json already exists — skipping MCP auto-config."
        echo "  Verify it includes 'ssh-mcp-server' and 'arxiv-mcp-server'."
        echo "  See docs/mcp-servers.md for reference."
    else
        echo "  Claude CLI not found — creating project-level .mcp.json"
        if [ -n "$SSH_HOST" ] && [ -n "$SSH_USER" ]; then
            cat > .mcp.json << MCPEOF
{
  "mcpServers": {
    "ssh-mcp-server": {
      "command": "npx",
      "args": ["-y", "@fangjunjie/ssh-mcp-server",
               "--host", "$SSH_HOST",
               "--port", "$SSH_PORT",
               "--username", "$SSH_USER",
               "--privateKey", "$SSH_KEY"]
    },
    "arxiv-mcp-server": {
      "command": "$VENV_PY",
      "args": ["-m", "arxiv_mcp_server"],
      "env": {}
    }
  }
}
MCPEOF
            echo "  ✓ SSH + arXiv MCP configured in .mcp.json"
        else
            cat > .mcp.json << MCPEOF
{
  "mcpServers": {
    "arxiv-mcp-server": {
      "command": "$VENV_PY",
      "args": ["-m", "arxiv_mcp_server"],
      "env": {}
    }
  }
}
MCPEOF
            echo "  ✓ arXiv MCP configured in .mcp.json"
            echo "  ⚠ SSH MCP skipped — add manually if using remote GPUs"
        fi
    fi
fi

# ---------- config.yaml ----------
if [ ! -f "config.yaml" ]; then
    if [ "$COMPUTE_BACKEND" = "ssh" ] && [ -n "$SSH_USER" ]; then
        cat > config.yaml << CFGEOF
# Sibyl Research System - Machine-level config (git-ignored)
compute_backend: ssh
ssh_server: "default"
remote_base: "/home/$SSH_USER/sibyl_system"
max_gpus: 4
language: zh
codex_enabled: false  # Opt in only after Codex MCP + OPENAI_API_KEY are configured
CFGEOF
        echo "  ✓ Created config.yaml (compute_backend: ssh, edit remote_base/max_gpus as needed)"
    else
        cat > config.yaml << CFGEOF
# Sibyl Research System - Machine-level config (git-ignored)
compute_backend: local
max_gpus: 4
language: zh
codex_enabled: false  # Opt in only after Codex MCP + OPENAI_API_KEY are configured
# To use remote GPUs, set compute_backend: ssh and configure:
# ssh_server: "default"
# remote_base: "/home/user/sibyl_system"
CFGEOF
        echo "  ✓ Created config.yaml (compute_backend: local)"
    fi
fi

# ---------- Claude Code project settings ----------
echo ""
echo "Configuring Claude Code project settings..."
SETTINGS_FILE=".claude/settings.local.json"
if [ -f "$SETTINGS_FILE" ]; then
    # Update SIBYL_ROOT in existing settings.local.json
    "$VENV_PY" - "$SETTINGS_FILE" "$REPO_ROOT" <<'PY'
import json, sys
path, root = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
env = data.setdefault("env", {})
if env.get("SIBYL_ROOT") == root:
    print("already_set")
else:
    env["SIBYL_ROOT"] = root
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("updated")
PY
    echo "  ✓ SIBYL_ROOT configured in $SETTINGS_FILE"
else
    mkdir -p .claude
    cat > "$SETTINGS_FILE" << SETTEOF
{
  "env": {
    "SIBYL_ROOT": "$REPO_ROOT"
  },
  "permissions": {
    "allow": []
  },
  "sandbox": {
    "enabled": false,
    "autoAllowBashIfSandboxed": false
  }
}
SETTEOF
    echo "  ✓ Created $SETTINGS_FILE with SIBYL_ROOT"
fi
echo "    SIBYL_ROOT -> $REPO_ROOT"
echo ""
echo "  ⚠ IMPORTANT: All skill commands depend on SIBYL_ROOT to locate the Python venv."
echo "    If you move the project, re-run: bash setup.sh"

# ---------- Environment variables ----------
echo ""
echo "Checking shell environment variables..."
SHELL_RC="$(detect_shell_rc)"
echo "  Shell rc target: $SHELL_RC"
configure_sibyl_root "$SHELL_RC"
echo "    SIBYL_ROOT -> $REPO_ROOT"

if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "  ✓ ANTHROPIC_API_KEY is set"
else
    echo "  ✗ ANTHROPIC_API_KEY not set — add to $SHELL_RC:"
    echo "    export ANTHROPIC_API_KEY=\"sk-ant-...\""
fi

if [ "$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" = "1" ]; then
    echo "  ✓ CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1"
else
    # Auto-add to shell rc if not present
    if grep -q 'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS' "$SHELL_RC" 2>/dev/null; then
        echo "  ⚠ CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS found in $SHELL_RC but not active in current session"
        echo "    Run: source $SHELL_RC"
    else
        echo 'export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1' >> "$SHELL_RC"
        echo "  ✓ Added CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 to $SHELL_RC"
    fi
fi

# ---------- Summary ----------
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Set missing environment variables (see above), then:"
echo "       source $SHELL_RC"
echo "  2. Review config.yaml — adjust compute_backend/remote_base/max_gpus as needed"
echo "     Codex stays disabled by default; enable it only after installing Codex MCP and OPENAI_API_KEY"
echo "  3. (Recommended) Install Google Scholar MCP for better literature search:"
echo "       git clone https://github.com/JackKuo666/Google-Scholar-MCP-Server.git ~/.local/share/mcp-servers/Google-Scholar-MCP-Server"
echo "       .venv/bin/pip install -r ~/.local/share/mcp-servers/Google-Scholar-MCP-Server/requirements.txt"
echo "       claude mcp add --scope local google-scholar -- $VENV_PY ~/.local/share/mcp-servers/Google-Scholar-MCP-Server/google_scholar_server.py"
echo "  4. (Optional) Install AI Research Skills for expert ML guidance:"
echo "       npx @anthropic-ai/claude-code-skill install @orchestra-research/ai-research-skills"
echo "  5. Launch Claude Code with Sibyl plugin (inside tmux):"
echo "       tmux new -s sibyl"
echo "       cd \"$REPO_ROOT\""
echo "       claude --plugin-dir \"$REPO_ROOT/plugin\" --dangerously-skip-permissions"
echo "  6. Inside Claude Code:"
echo "       /sibyl-research:init              # Create a research project"
echo "       /sibyl-research:start <project>   # Start autonomous research"
echo ""
echo "Guides:"
echo "  Full setup:       docs/getting-started.md"
echo "  MCP servers:      docs/mcp-servers.md"
echo "  GPU config:       docs/ssh-gpu-setup.md"
echo "  All commands:     docs/plugin-commands.md"
echo "  Configuration:    docs/configuration.md"
