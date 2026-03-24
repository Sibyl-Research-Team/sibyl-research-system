---
description: "启动 Rebuttal 对抗迭代循环"
argument-hint: "<workspace_path>"
---

# /sibyl-research:rebuttal-start

启动 Rebuttal 对抗迭代循环。需要已初始化的工作区（通过 `/sibyl-research:rebuttal-init` 创建）。

工作目录: `$SIBYL_ROOT`

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

参数: `$ARGUMENTS`（workspace 路径）

## 步骤

0. **打印启动横幅**：

```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_rebuttal_status; cli_rebuttal_status('$ARGUMENTS')"
```

解析输出，打印横幅：
```
╔═════════════════════════════════════════════════════════════════╗
║     SIBYL REBUTTAL SYSTEM  ·  Adversarial Rebuttal Engine       ║
╚═════════════════════════════════════════════════════════════════╝

  工作区：<workspace_path>
  阶段：<current_stage>
  轮次：#<round> / <max_rounds>
  Reviewers：<reviewer_ids>
  字数限制：<word_limit or "无限制">
  Codex：<enabled/disabled>

  正在启动对抗迭代循环 →
```

1. **创建 Task 依赖链**追踪进度：
   - 为每个剩余阶段创建 Task（从当前 stage 到 done）
   - 用 `addBlockedBy` 串联依赖

2. **进入编排循环**：

```
LOOP:
  1. 获取下一步操作：
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_rebuttal_next; cli_rebuttal_next('WORKSPACE_PATH')"

  2. 导出语言环境变量：
     export SIBYL_LANGUAGE=<action.language>

  3. 按 action_type 分发执行：

     skill:
       调用 action.skills[0].name 技能，args 为 action.skills[0].args

     skills_parallel:
       并行启动所有 action.skills 中的技能，等待全部完成

     team:
       a. 使用 TeamCreate 创建团队 action.team.team_name
       b. 为每个 teammate 创建 TaskCreate，指定 owner 为 teammate.name
       c. 为每个 teammate 启动 Agent，调用其 skill，传入 args
       d. 等待所有 teammates 完成
       e. 按顺序执行 action.team.post_steps（每个 post_step 是一个 skill）

     bash:
       执行 action.bash_command

     done:
       打印完成横幅，输出最终 rebuttal 路径，退出循环

  4. 记录完成：
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_rebuttal_record; cli_rebuttal_record('WORKSPACE_PATH', 'STAGE')"

  5. 更新对应 Task 状态为 completed

  6. 检查返回结果：
     - 如果 new_stage == "rebuttal_draft" 且 round > 1：打印迭代状态面板
       （当前轮次、分数变化、剩余 concern 数）
     - 如果 new_stage == "done"：退出循环

  7. 回到 LOOP 开头
```

3. **完成横幅**：

```
╔═════════════════════════════════════════════════════════════════╗
║     REBUTTAL COMPLETE                                            ║
╚═════════════════════════════════════════════════════════════════╝

  最终分数：<avg_score>
  迭代轮次：<total_rounds>
  输出文件：
    - WORKSPACE/output/rebuttal_letter.md（完整 rebuttal 信）
    - WORKSPACE/output/per_reviewer/（逐 reviewer 回复）
    - WORKSPACE/output/experiment_plan.md（补充实验计划）
    - WORKSPACE/output/score_trajectory.json（分数轨迹）
```

## 注意事项

- **不涉及 GPU/实验执行**：rebuttal 系统不自动执行实验，只生成实验计划
- **不需要 Sentinel**：rebuttal 循环较短（通常 2-3 轮 × 几分钟），不需要看门狗
- **字数限制**：team prompt 和 synthesizer 会自动感知并强制执行配置的字数限制
- **每轮迭代**包含：Rebuttal Team 起草(8人) → Simulated Reviewers 攻击(N人) → [Codex 审查] → 评分判断
- **停止条件**：`平均分 ≥ 阈值` 或 `轮次 ≥ 上限`，两者取先
