---
name: sibyl-rebuttal-experimentalist
description: Sibyl Rebuttal 实验设计 agent - 设计补充实验计划（不执行）
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill
---

!`cd "$SIBYL_ROOT" && SIBYL_WORKSPACE="$ARGUMENTS[0]" ROUND_NUM="$ARGUMENTS[1]" .venv/bin/python3 -c "from sibyl.rebuttal.prompt_helpers import render_rebuttal_skill_prompt; import os; print(render_rebuttal_skill_prompt('rebuttal_experimentalist', workspace_path=os.environ.get('SIBYL_WORKSPACE',''), round_num=int(os.environ.get('ROUND_NUM','1') or '1')))"`

AGENT_NAME: sibyl-rebuttal-experimentalist
AGENT_TIER: sibyl-standard
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
Round: $ARGUMENTS[1]
