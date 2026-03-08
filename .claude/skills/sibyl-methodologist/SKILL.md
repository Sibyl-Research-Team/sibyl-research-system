---
name: sibyl-methodologist
description: Sibyl 方法论者 agent - 审查实验方法的内外部效度和可复现性
context: fork
agent: sibyl-light
user-invocable: false
allowed-tools: Read, Write, Glob, Grep
---

!`.venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; print(load_common_prompt()); print('---'); print(load_prompt('methodologist'))"`

Workspace path: $ARGUMENTS[0]

Write your output to $ARGUMENTS[0]/idea/result_debate/methodologist.md
