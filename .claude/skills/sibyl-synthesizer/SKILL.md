---
name: sibyl-synthesizer
description: Sibyl 综合决策者 agent - 综合多方观点生成最终研究提案
context: fork
agent: sibyl-heavy
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, WebSearch, Skill
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" .venv/bin/python3 -c "from sibyl.orchestrate import render_skill_prompt; import os; ws = os.environ.get('SIBYL_WORKSPACE', ''); print(render_skill_prompt('synthesizer', workspace_path=ws))"`

AGENT_NAME: sibyl-synthesizer
AGENT_TIER: sibyl-heavy
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
