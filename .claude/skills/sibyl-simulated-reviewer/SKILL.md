---
name: sibyl-simulated-reviewer
description: Sibyl 模拟 Reviewer agent - 从真实 reviewer 视角重新评估 rebuttal
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill
---

!`cd "$SIBYL_ROOT" && SIBYL_WORKSPACE="$ARGUMENTS[0]" REVIEWER_ID="$ARGUMENTS[1]" ROUND_NUM="$ARGUMENTS[2]" .venv/bin/python3 -c "from sibyl.rebuttal.prompt_helpers import render_reviewer_persona_prompt; import os; print(render_reviewer_persona_prompt(os.environ.get('SIBYL_WORKSPACE',''), os.environ.get('REVIEWER_ID',''), int(os.environ.get('ROUND_NUM','1') or '1')))"`

AGENT_NAME: sibyl-simulated-reviewer
AGENT_TIER: sibyl-standard
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
Reviewer ID: $ARGUMENTS[1]
Round: $ARGUMENTS[2]
