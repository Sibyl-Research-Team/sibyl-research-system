---
name: sibyl-rebuttal-writer
description: Sibyl Rebuttal 写手 agent - 撰写正式 rebuttal 回复
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill
---

!`cd "$SIBYL_ROOT" && SIBYL_WORKSPACE="$ARGUMENTS[0]" ROUND_NUM="$ARGUMENTS[1]" .venv/bin/python3 -c "from sibyl.rebuttal.prompt_helpers import render_rebuttal_skill_prompt; import os; print(render_rebuttal_skill_prompt('rebuttal_writer', workspace_path=os.environ.get('SIBYL_WORKSPACE',''), round_num=int(os.environ.get('ROUND_NUM','1') or '1')))"`

AGENT_NAME: sibyl-rebuttal-writer
AGENT_TIER: sibyl-standard
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
Round: $ARGUMENTS[1]
