---
name: sibyl-empiricist
description: Sibyl 实验主义者 agent - 关注可复现性、数据质量和实验设计严谨性
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, WebSearch, WebFetch, mcp__arxiv-mcp-server__search_papers, mcp__arxiv-mcp-server__download_paper, mcp__arxiv-mcp-server__read_paper, mcp__google-scholar__search_google_scholar_key_words, mcp__claude_ai_bioRxiv__search_preprints
---

!`.venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; print(load_common_prompt()); print('---'); print(load_prompt('empiricist'))"`

Topic: $ARGUMENTS[0]
Workspace path: $ARGUMENTS[1]

Write your output to $ARGUMENTS[1]/idea/perspectives/empiricist.md
