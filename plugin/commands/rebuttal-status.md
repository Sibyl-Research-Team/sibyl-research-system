---
description: "查看 Rebuttal 项目状态和分数轨迹"
argument-hint: "<workspace_path>"
---

# /sibyl-research:rebuttal-status

查看 Rebuttal 项目的当前状态、分数轨迹、reviewer 信息。

工作目录: `$SIBYL_ROOT`

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

参数: `$ARGUMENTS`（workspace 路径）

## 步骤

1. 获取状态：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_rebuttal_status; cli_rebuttal_status('$ARGUMENTS')"
```

2. 解析 JSON 输出并向用户展示格式化的状态面板：

```
╔═════════════════════════════════════════════════════════════════╗
║     SIBYL REBUTTAL STATUS                                        ║
╚═════════════════════════════════════════════════════════════════╝

  阶段：<stage>
  轮次：#<round> / <max_rounds>
  分数阈值：<score_threshold>
  字数限制：<word_limit or "无限制">
  Codex：<enabled/disabled>

  Reviewers：
    - <reviewer_id_1>
    - <reviewer_id_2>
    ...

  分数轨迹：
    Round 1: avg=<score> (R1=<s1>, R2=<s2>, ...)
    Round 2: avg=<score> (R1=<s1>, R2=<s2>, ...) [+<delta>]
    ...
```

如果项目已完成（stage=done），额外展示输出文件路径：
```
  输出文件：
    - <workspace>/output/rebuttal_letter.md
    - <workspace>/output/per_reviewer/
    - <workspace>/output/experiment_plan.md
    - <workspace>/output/score_trajectory.json
```
