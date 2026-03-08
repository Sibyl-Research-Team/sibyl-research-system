#!/bin/bash
# Sibyl System - Setup Script
# Installs Python environment, dependencies, and configures MCP servers

set -e
echo "=== Sibyl System Setup ==="

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
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    echo "Node.js $NODE_VER detected"
else
    echo "⚠  Node.js not found. Required for Lark/Codex MCP servers."
    echo "   Install via: brew install node  (macOS) or https://nodejs.org/"
fi

# ---------- MCP configuration ----------
echo ""
MCP_CONFIG="$HOME/.mcp.json"
if [ -f "$MCP_CONFIG" ]; then
    echo "~/.mcp.json already exists — skipping MCP auto-config."
    echo "  Verify it includes 'arxiv-mcp-server'. See docs/mcp-servers.md for reference."
else
    echo "Creating ~/.mcp.json with required MCP servers..."
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
    echo "  ✓ Created ~/.mcp.json (arXiv MCP configured)"
    echo "  Note: SSH MCP is built into Claude Code — no config needed."
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
echo "  2. Configure your GPU server in ~/.ssh/config (see docs/ssh-gpu-setup.md)"
echo "  3. Create config.yaml with your GPU server settings:"
echo "       cp config.example.yaml config.yaml && edit config.yaml"
echo "  4. Launch Claude Code with Sibyl plugin:"
echo "       claude --plugin-dir ./plugin"
echo "  5. Inside Claude Code:"
echo "       /sibyl-research:init              # Create a research project"
echo "       /sibyl-research:start <project>   # Start autonomous research"
echo ""
echo "Full guide: docs/getting-started.md"
echo "All commands: docs/plugin-commands.md"
