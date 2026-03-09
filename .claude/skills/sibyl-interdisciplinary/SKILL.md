---
name: sibyl-interdisciplinary
description: Sibyl 跨学科者 agent - 从认知科学、物理、生物等领域引入类比和方法
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, WebSearch, WebFetch, mcp__arxiv-mcp-server__search_papers, mcp__arxiv-mcp-server__download_paper, mcp__arxiv-mcp-server__read_paper, mcp__google-scholar__search_google_scholar_key_words, mcp__claude_ai_bioRxiv__search_preprints
---

!`.venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; print(load_common_prompt()); print('---'); print(load_prompt('interdisciplinary'))"`

Workspace path: $ARGUMENTS[0]
Topic (may contain spaces): $ARGUMENTS[1]

Write your output to $ARGUMENTS[0]/idea/perspectives/interdisciplinary.md
