# MCP Server Dependencies

Sibyl relies on [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers for external integrations. All MCP servers are registered in `~/.mcp.json`.

## Overview

| MCP Server | Required | Purpose | Source |
|------------|----------|---------|--------|
| [SSH MCP](#ssh-mcp-server) | Yes | Remote GPU execution & file transfer | [classfang/ssh-mcp-server](https://github.com/classfang/ssh-mcp-server) |
| [arXiv MCP](#arxiv-mcp-server) | Yes | Academic paper search | [blazickjp/arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server) |
| [Google Scholar MCP](#google-scholar-mcp) | Recommended | Citation & author search | [JackKuo666/Google-Scholar-MCP-Server](https://github.com/JackKuo666/Google-Scholar-MCP-Server) |
| [Codex MCP](#codex-mcp) | Optional | GPT-5.4 cross-review | [openai/codex](https://github.com/openai/codex) |
| [Lark MCP (Official)](#lark-mcp-official) | Optional | Feishu Bitable & messaging | [larksuite/lark-openapi-mcp](https://github.com/larksuite/lark-openapi-mcp) |
| [Feishu MCP (Community)](#feishu-mcp-community) | Optional | Feishu documents & folders | [cso1z/Feishu-MCP](https://github.com/cso1z/Feishu-MCP) |
| [bioRxiv MCP](#biorxiv-mcp) | Optional | Biology preprint search | [JackKuo666/bioRxiv-MCP-Server](https://github.com/JackKuo666/bioRxiv-MCP-Server) |
| [Playwright MCP](#playwright-mcp) | Optional | Web browsing automation | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) |

## SSH MCP Server

> GitHub: [classfang/ssh-mcp-server](https://github.com/classfang/ssh-mcp-server) · npm: [`@fangjunjie/ssh-mcp-server`](https://www.npmjs.com/package/@fangjunjie/ssh-mcp-server)

**Purpose**: Execute commands on remote GPU servers, upload/download files.

**Tools used**: `execute-command`, `upload`, `download`, `list-servers`

### Install

Requires Node.js 18+:

```bash
# No global install needed — runs via npx
npx @fangjunjie/ssh-mcp-server --help
```

### Configure (`~/.mcp.json`)

```json
{
  "mcpServers": {
    "ssh-mcp-server": {
      "command": "npx",
      "args": ["-y", "@fangjunjie/ssh-mcp-server",
               "--host", "192.168.1.100",
               "--port", "22",
               "--username", "your-username",
               "--privateKey", "~/.ssh/id_ed25519"]
    }
  }
}
```

> **Important**: The server name **must** be `"ssh-mcp-server"` — Sibyl's agent prompts reference tools as `mcp__ssh-mcp-server__execute-command`. The `--privateKey` path should point to your SSH private key.

Or use `claude mcp add`:

```bash
claude mcp add ssh-mcp-server -- npx -y @fangjunjie/ssh-mcp-server \
  --host 192.168.1.100 --port 22 --username your-username \
  --privateKey ~/.ssh/id_ed25519
```

See [SSH & GPU Setup](ssh-gpu-setup.md) for server-side configuration.

## arXiv MCP Server

> GitHub: [blazickjp/arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server)

**Purpose**: Search and retrieve academic papers from arXiv.

**Tools used**: `search_papers`, `download_paper`, `read_paper`, `list_papers`

**Used by**: Literature search, idea generation agents, comparativist agent

### Install

```bash
pip install arxiv-mcp-server
```

### Configure (`~/.mcp.json`)

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

> **Important**: The server name **must** be `"arxiv-mcp-server"` — Sibyl's agent prompts reference tools as `mcp__arxiv-mcp-server__search_papers`. Using a different name will break tool resolution.

## Google Scholar MCP

> GitHub: [JackKuo666/Google-Scholar-MCP-Server](https://github.com/JackKuo666/Google-Scholar-MCP-Server)

**Purpose**: Search Google Scholar for papers, get author information.

**Tools used**: `search_google_scholar_key_words`, `search_google_scholar_advanced`, `get_author_info`

**Used by**: Literature search, idea generation agents, comparativist agent

### Install

```bash
# Clone the repository
git clone https://github.com/JackKuo666/Google-Scholar-MCP-Server.git ~/.local/share/mcp-servers/Google-Scholar-MCP-Server
cd ~/.local/share/mcp-servers/Google-Scholar-MCP-Server
pip install -r requirements.txt
```

### Configure (`~/.mcp.json`)

```json
{
  "mcpServers": {
    "google-scholar": {
      "command": "python",
      "args": ["~/.local/share/mcp-servers/Google-Scholar-MCP-Server/google_scholar_server.py"],
      "env": {}
    }
  }
}
```

> **Note**: If Google Scholar MCP is unavailable, the system falls back to arXiv + WebSearch for literature discovery.

## Codex MCP

> GitHub: [openai/codex](https://github.com/openai/codex)

**Purpose**: Independent GPT-5.4 cross-review for idea debate, result analysis, and paper review.

**Tools used**: `codex` (single query), `codex-reply` (multi-turn conversation)

**Used by**: Codex reviewer skill, optional Codex writing mode

### Install

```bash
npm install -g @openai/codex
```

### Configure

1. Set up `~/.codex/config.toml`:

```toml
model = "gpt-5.4"
model_reasoning_effort = "high"
```

2. Set `OPENAI_API_KEY` environment variable.

3. Add to `~/.mcp.json`:

```json
{
  "mcpServers": {
    "codex": {
      "command": "codex",
      "args": ["mcp-server"],
      "env": {
        "OPENAI_API_KEY": "your-key-here"
      }
    }
  }
}
```

See [Codex Integration](codex-integration.md) for full details.

**Enable**: Install Codex MCP, set `OPENAI_API_KEY`, then set `codex_enabled: true` in `config.yaml` (default is `false`).

## Lark MCP (Official)

> GitHub: [larksuite/lark-openapi-mcp](https://github.com/larksuite/lark-openapi-mcp)

**Purpose**: Feishu/Lark Bitable (multidimensional tables) and instant messaging.

**Tools used**: `bitable_v1_*`, `im_v1_*`

**Used by**: Lark sync skill (data tables, team notifications)

### Install

```bash
npm install -g @larksuiteoapi/lark-mcp
```

### Configure (`~/.mcp.json`)

```json
{
  "mcpServers": {
    "lark": {
      "command": "npx",
      "args": ["-y", "@larksuiteoapi/lark-mcp"],
      "env": {
        "LARK_APP_ID": "your-app-id",
        "LARK_APP_SECRET": "your-app-secret"
      }
    }
  }
}
```

Requires a Feishu/Lark app with tenant access token. See [Feishu/Lark Setup](feishu-lark-setup.md).

## Feishu MCP (Community)

> GitHub: [cso1z/Feishu-MCP](https://github.com/cso1z/Feishu-MCP)

**Purpose**: Feishu document creation, folder management, native tables.

**Tools used**: `create_feishu_document`, `batch_create_feishu_blocks`, `create_feishu_table`, `create_feishu_folder`, etc.

**Used by**: Lark sync skill (research documents, paper uploads)

### Install

```bash
npm install -g feishu-mcp
```

### Configure (`~/.mcp.json`)

```json
{
  "mcpServers": {
    "feishu": {
      "command": "feishu-mcp",
      "args": [],
      "env": {
        "FEISHU_USER_ACCESS_TOKEN": "your-user-token"
      }
    }
  }
}
```

Requires user OAuth token. See [Feishu/Lark Setup](feishu-lark-setup.md).

> **Important**: Sibyl uses a dual-MCP architecture for Feishu — the official `lark` MCP for Bitable/IM, and the community `feishu` MCP for document operations. Both are needed for full sync functionality.

## bioRxiv MCP

> GitHub: [JackKuo666/bioRxiv-MCP-Server](https://github.com/JackKuo666/bioRxiv-MCP-Server)

**Purpose**: Search biological and medical preprints.

**Tools used**: `search_preprints`, `get_preprint`

**Used by**: Innovator, interdisciplinary, and contrarian agents (for cross-domain inspiration)

### Install

```bash
pip install biorxiv-mcp-server
```

### Configure (`~/.mcp.json`)

```json
{
  "mcpServers": {
    "claude_ai_bioRxiv": {
      "command": "python",
      "args": ["-m", "biorxiv_mcp"],
      "env": {}
    }
  }
}
```

## Playwright MCP

> GitHub: [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)

**Purpose**: Web browsing automation for research (accessing websites, reading documentation).

**Used by**: Literature search (web sources), experiment agents (documentation lookup)

### Install

```bash
npm install -g @playwright/mcp
```

### Configure (`~/.mcp.json`)

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp"]
    }
  }
}
```

Or install as a Claude Code plugin:

```bash
claude mcp add playwright -- npx -y @playwright/mcp
```

## Minimal `~/.mcp.json` Example

A minimal configuration with only the two required servers:

```json
{
  "mcpServers": {
    "ssh-mcp-server": {
      "command": "npx",
      "args": ["-y", "@fangjunjie/ssh-mcp-server",
               "--host", "192.168.1.100",
               "--port", "22",
               "--username", "your-username",
               "--privateKey", "~/.ssh/id_ed25519"]
    },
    "arxiv-mcp-server": {
      "command": "python",
      "args": ["-m", "arxiv_mcp_server"]
    }
  }
}
```

## Full `~/.mcp.json` Example

All servers configured together:

```json
{
  "mcpServers": {
    "ssh-mcp-server": {
      "command": "npx",
      "args": ["-y", "@fangjunjie/ssh-mcp-server",
               "--host", "192.168.1.100", "--port", "22",
               "--username", "your-username",
               "--privateKey", "~/.ssh/id_ed25519"]
    },
    "arxiv-mcp-server": {
      "command": "python",
      "args": ["-m", "arxiv_mcp_server"]
    },
    "google-scholar": {
      "command": "python",
      "args": ["~/.local/share/mcp-servers/Google-Scholar-MCP-Server/google_scholar_server.py"]
    },
    "codex": {
      "command": "codex",
      "args": ["mcp-server"],
      "env": { "OPENAI_API_KEY": "your-key" }
    },
    "lark": {
      "command": "npx",
      "args": ["-y", "@larksuiteoapi/lark-mcp"],
      "env": { "LARK_APP_ID": "your-id", "LARK_APP_SECRET": "your-secret" }
    },
    "feishu": {
      "command": "feishu-mcp",
      "env": { "FEISHU_USER_ACCESS_TOKEN": "your-token" }
    },
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp"]
    }
  }
}
```

## Adapting MCP Servers

If you use different MCP server implementations than those listed above:

1. **Tool name compatibility**: Sibyl's agent prompts reference specific MCP tool names (e.g., `mcp__arxiv-mcp-server__search_papers`). If your MCP server uses different tool names, you'll need to update the corresponding prompt files in `sibyl/prompts/`.

2. **Server name in `~/.mcp.json`**: The server name in `~/.mcp.json` becomes part of the tool name prefix. For example, if you name your arXiv server `my-arxiv`, tools will be called `mcp__my-arxiv__search_papers`. Update prompt references accordingly.

3. **Permission allowlists**: If using `.claude/settings.local.json` for tool permissions, update the allowlist to match your server names.
