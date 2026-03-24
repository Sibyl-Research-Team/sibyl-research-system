---
name: sibyl-rebuttal-synthesizer
description: Sibyl Rebuttal 综合者 agent - 整合团队输出为完整 rebuttal
context: fork
agent: sibyl-heavy
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" REBUTTAL_MODE="$ARGUMENTS[1]" WORD_LIMIT="$ARGUMENTS[2]" .venv/bin/python3 -c "from sibyl.rebuttal.prompt_helpers import render_rebuttal_skill_prompt; import os; print(render_rebuttal_skill_prompt('rebuttal_synthesizer', workspace_path=os.environ.get('SIBYL_WORKSPACE',''), mode=os.environ.get('REBUTTAL_MODE','round'), round_num=int(os.environ.get('ROUND_NUM','1') or '1')))"`

AGENT_NAME: sibyl-rebuttal-synthesizer
AGENT_TIER: sibyl-heavy
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
Mode: $ARGUMENTS[1]
Word limit: $ARGUMENTS[2]
