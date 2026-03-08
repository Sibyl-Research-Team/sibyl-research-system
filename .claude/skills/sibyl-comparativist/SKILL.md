---
name: sibyl-comparativist
description: Sibyl 比较分析者 agent - 对标 SOTA 和同类工作，定位结果贡献
context: fork
agent: sibyl-light
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, WebSearch, WebFetch, mcp__arxiv-mcp-server__search_papers, mcp__google-scholar__search_google_scholar_key_words
---

!`.venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; print(load_common_prompt()); print('---'); print(load_prompt('comparativist'))"`

Workspace path: $ARGUMENTS[0]

Write your output to $ARGUMENTS[0]/idea/result_debate/comparativist.md
