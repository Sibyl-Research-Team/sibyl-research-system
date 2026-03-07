#!/bin/bash
# FARS Pipeline - Setup Script
# Installs all dependencies including optional MCP servers

set -e
echo "=== FARS Pipeline Setup ==="

cd "$(dirname "$0")"

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing core dependencies..."
pip install -e .

echo ""
echo "Installing MCP servers (optional but recommended)..."
pip install arxiv-mcp-server 2>/dev/null && echo "  ✓ arxiv-mcp-server" || echo "  ✗ arxiv-mcp-server (optional)"
pip install paper-search-mcp 2>/dev/null && echo "  ✓ paper-search-mcp" || echo "  ✗ paper-search-mcp (optional)"
pip install semanticscholar-mcp-server 2>/dev/null && echo "  ✓ semanticscholar-mcp-server" || echo "  ✗ semanticscholar-mcp-server (optional)"

echo ""
echo "Installing ML dependencies for experiments..."
pip install torch transformers datasets matplotlib numpy scikit-learn 2>/dev/null || echo "  (ML deps need manual install based on your platform)"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Usage:"
echo "  source .venv/bin/activate"
echo "  fars check-tools          # verify installation"
echo "  fars run 'your topic'     # run a research pipeline"
echo "  fars list                 # view projects"
echo ""
echo "Make sure ANTHROPIC_API_KEY is set in your environment."
