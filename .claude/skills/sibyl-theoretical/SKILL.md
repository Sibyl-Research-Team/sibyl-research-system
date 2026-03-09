---
name: sibyl-theoretical
description: Sibyl 理论研究者 agent - 注重数学基础和理论保证的研究提案
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, WebSearch, WebFetch, mcp__arxiv-mcp-server__search_papers, mcp__arxiv-mcp-server__download_paper, mcp__arxiv-mcp-server__read_paper, mcp__google-scholar__search_google_scholar_key_words
---

!`.venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; print(load_common_prompt()); print('---'); print(load_prompt('theoretical'))"`

Workspace path: $ARGUMENTS[0]
Topic (may contain spaces): $ARGUMENTS[1]

Write your output to $ARGUMENTS[0]/idea/perspectives/theoretical.md
