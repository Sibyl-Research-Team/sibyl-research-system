#!/bin/bash
# Sibyl Research System - Setup Script
# Installs Python environment, dependencies, and configures MCP servers

set -e
echo "=== Sibyl Research System Setup ==="

cd "$(dirname "$0")"

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

echo "Installing core dependencies..."
pip install -e . 2>&1 | tail -3

# ---------- MCP servers (Python-based) ----------
echo ""
echo "Installing Python MCP servers..."
pip install arxiv-mcp-server 2>/dev/null && echo "  ✓ arxiv-mcp-server" || echo "  ✗ arxiv-mcp-server (install manually: pip install arxiv-mcp-server)"

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
MCP_CONFIG="$HOME/.mcp.json"
if [ -f "$MCP_CONFIG" ]; then
    echo "~/.mcp.json already exists — skipping MCP auto-config."
    echo "  Verify it includes 'ssh-mcp-server' and 'arxiv-mcp-server'."
    echo "  See docs/mcp-servers.md for reference."
else
    echo "Configuring required MCP servers..."
    echo ""

    # --- SSH MCP Server ---
    SSH_HOST=""
    SSH_PORT="22"
    SSH_USER=""
    SSH_KEY="$HOME/.ssh/id_ed25519"

    echo "SSH MCP Server (@fangjunjie/ssh-mcp-server) — required for GPU experiments"
    echo "  GitHub: https://github.com/classfang/ssh-mcp-server"
    echo ""
    read -p "  GPU server hostname or IP (e.g., 192.168.1.100): " SSH_HOST
    if [ -n "$SSH_HOST" ]; then
        read -p "  SSH port [22]: " input_port
        SSH_PORT="${input_port:-22}"
        read -p "  SSH username: " SSH_USER
        read -p "  SSH private key path [$SSH_KEY]: " input_key
        SSH_KEY="${input_key:-$SSH_KEY}"
    fi

    echo ""
    echo "Creating ~/.mcp.json..."

    if [ -n "$SSH_HOST" ] && [ -n "$SSH_USER" ]; then
        cat > "$MCP_CONFIG" << MCPEOF
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
      "command": "python",
      "args": ["-m", "arxiv_mcp_server"],
      "env": {}
    }
  }
}
MCPEOF
        echo "  ✓ SSH MCP configured ($SSH_USER@$SSH_HOST:$SSH_PORT)"
        echo "  ✓ arXiv MCP configured"

        # Also create config.yaml if it doesn't exist
        if [ ! -f "config.yaml" ]; then
            cat > config.yaml << CFGEOF
# Sibyl Research System - Machine-level config (git-ignored)
ssh_server: "default"
remote_base: "/home/$SSH_USER/sibyl_system"
max_gpus: 4
codex_enabled: false  # Opt in only after Codex MCP + OPENAI_API_KEY are configured
CFGEOF
            echo "  ✓ Created config.yaml (edit remote_base/max_gpus as needed)"
        fi
    else
        # SSH skipped — create with arXiv only
        cat > "$MCP_CONFIG" << 'MCPEOF'
{
  "mcpServers": {
    "arxiv-mcp-server": {
      "command": "python",
      "args": ["-m", "arxiv_mcp_server"],
      "env": {}
    }
  }
}
MCPEOF
        echo "  ✓ arXiv MCP configured"
        echo "  ⚠ SSH MCP skipped — configure manually later. See docs/mcp-servers.md"
    fi
fi

# ---------- Environment variables check ----------
echo ""
echo "Checking environment variables..."
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "  ✓ ANTHROPIC_API_KEY is set"
else
    echo "  ✗ ANTHROPIC_API_KEY not set — add to your ~/.zshrc or ~/.bashrc:"
    echo "    export ANTHROPIC_API_KEY=\"sk-ant-...\""
fi

if [ "$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" = "1" ]; then
    echo "  ✓ CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1"
else
    echo "  ✗ CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS not set — add to your ~/.zshrc or ~/.bashrc:"
    echo "    export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1"
fi

# ---------- Summary ----------
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Set missing environment variables (see above)"
echo "  2. Review config.yaml — adjust remote_base/max_gpus for your server"
echo "     Codex stays disabled by default; enable it only after installing Codex MCP and OPENAI_API_KEY"
echo "  3. Launch Claude Code with Sibyl plugin:"
echo "       claude --plugin-dir ./plugin"
echo "  4. Inside Claude Code:"
echo "       /sibyl-research:init              # Create a research project"
echo "       /sibyl-research:start <project>   # Start autonomous research"
echo ""
echo "Guides:"
echo "  Full setup:       docs/getting-started.md"
echo "  MCP servers:      docs/mcp-servers.md"
echo "  GPU config:       docs/ssh-gpu-setup.md"
echo "  All commands:     docs/plugin-commands.md"
echo "  Configuration:    docs/configuration.md"
