# Codex Integration

Sibyl uses OpenAI's Codex CLI (GPT-5.4) as an independent third-party reviewer, providing a different AI perspective alongside Claude.

## When Codex Is Used

| Pipeline Stage | Usage |
|----------------|-------|
| `idea_debate` | Independent review of generated ideas |
| `result_debate` | Independent analysis of experiment results |
| `review` | Parallel review alongside Critic and Supervisor |
| `writing_sections` | Optional: entire paper written by GPT-5.4 (when `writing_mode: codex`) |

## Setup

### 1. Install Codex CLI

```bash
npm install -g @openai/codex
```

### 2. Configure `~/.codex/config.toml`

```toml
model = "gpt-5.4"
model_reasoning_effort = "high"
```

### 3. Set API Key

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

### 4. Register MCP Server

Add to `~/.mcp.json`:

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

### 5. Enable in Config

```yaml
codex_enabled: true    # Default: false (opt-in after Codex MCP is configured)
```

For your own local machine, once Codex MCP and `OPENAI_API_KEY` are working, it is recommended to enable `codex_enabled: true` in your local `config.yaml`. That file lives in your working tree, but Git does not track or commit it, so your machine can default to Codex without changing the repo-wide default.

## How It Works

1. Sibyl calls `mcp__codex__codex` with a review prompt
2. Codex CLI routes to GPT-5.4 (configured in `config.toml`)
3. The review is written to the workspace alongside Claude's review
4. The Synthesizer agent integrates both perspectives

**Important**: MCP calls do NOT pass a `model` parameter — the model configured in `~/.codex/config.toml` is used. This is because ChatGPT accounts may not support API-level model override.

The `approval-policy` should be set to `"never"` for fully autonomous operation.

## Disabling Codex

```yaml
codex_enabled: false
```

When disabled:
- Idea debate and result debate run without Codex review
- Review stage uses only Critic + Supervisor
- Writing cannot use `codex` mode (falls back to `parallel`)

## Server-Side Codex

When using `experiment_mode: "server_codex"`, Codex CLI must also be installed on the GPU server:

```bash
# On GPU server
npm install -g @openai/codex
```

And set `OPENAI_API_KEY` in the server environment. Configure the path if non-standard:

```yaml
server_codex_path: "/usr/local/bin/codex"
```
