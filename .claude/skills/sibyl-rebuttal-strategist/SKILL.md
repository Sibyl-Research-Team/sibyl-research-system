---
name: sibyl-rebuttal-strategist
description: Sibyl Rebuttal 策略分析 agent - 解析 reviewer 评价、优先级排序、评估分数
context: fork
agent: sibyl-heavy
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, WebSearch, WebFetch, Skill
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" REBUTTAL_MODE="$ARGUMENTS[1]" ROUND_NUM="$ARGUMENTS[2]" .venv/bin/python3 -c "from sibyl.rebuttal.prompt_helpers import render_rebuttal_skill_prompt; import os; print(render_rebuttal_skill_prompt('rebuttal_strategist', workspace_path=os.environ.get('SIBYL_WORKSPACE',''), mode=os.environ.get('REBUTTAL_MODE',''), round_num=int(os.environ.get('ROUND_NUM','1') or '1')))"`

AGENT_NAME: sibyl-rebuttal-strategist
AGENT_TIER: sibyl-heavy
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
Mode: $ARGUMENTS[1]
Round: $ARGUMENTS[2]
