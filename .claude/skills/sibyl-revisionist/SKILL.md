---
name: sibyl-revisionist
description: Sibyl 修正主义者 agent - 基于实验结果反思假设，提出修正方向
context: fork
agent: sibyl-light
user-invocable: false
allowed-tools: Read, Write, Glob, Grep
---

!`.venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; print(load_common_prompt()); print('---'); print(load_prompt('revisionist'))"`

Workspace path: $ARGUMENTS[0]

Write your output to $ARGUMENTS[0]/idea/result_debate/revisionist.md
