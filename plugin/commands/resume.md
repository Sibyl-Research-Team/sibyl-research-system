---
description: "手动恢复暂停的研究项目"
argument-hint: "<project>"
---

# /sibyl-research:resume

手动恢复暂停的项目并重新进入编排循环。

**所有用户可见的输出必须使用中文。**

工作目录: `/Users/cwan0785/sibyl-system`

参数: `$ARGUMENTS`（项目名称）

## 步骤

1. 恢复项目：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/$ARGUMENTS')"
```

2. 获取当前状态：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('workspaces/$ARGUMENTS')"
```

3. **自动启动 Ralph Loop 持续迭代**：

   首先，将迭代指令写入临时文件：
   ```bash
   cat > /tmp/sibyl-ralph-prompt.txt << 'PROMPT_EOF'
   持续迭代西比拉研究项目 PROJECT_NAME。
   每轮迭代步骤：
   1. 获取下一步操作: .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('WORKSPACE_PATH')"
   2. 根据 action_type 执行操作（见编排循环）
   3. 记录结果: .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('WORKSPACE_PATH', 'STAGE')"
   4. 重复直到 action_type 为 "done"
   5. done 后检查质量分数，如需继续迭代则回到步骤 1
   每次新迭代要基于上一次的结果和经验教训来改进。
   读取 WORKSPACE_PATH/logs/research_diary.md 了解历史。
   PROMPT_EOF
   ```
   注意：将 PROJECT_NAME 和 WORKSPACE_PATH 替换为实际值。

   然后使用 Skill 工具调用 `ralph-loop:ralph-loop`，prompt 使用**单行 shell-safe 文本**：
   ```
   按照 /tmp/sibyl-ralph-prompt.txt 中的指令持续迭代西比拉研究项目 PROJECT_NAME，工作目录 WORKSPACE_PATH，按编排循环章节执行每轮操作
   ```
   参数: `--max-iterations 30 --completion-promise 'SIBYL_PIPELINE_COMPLETE'`

   如果 Ralph Loop 不可用（插件错误），则手动执行编排循环。

## CLI API 参考（重要：只使用以下函数）

```python
from sibyl.orchestrate import cli_next       # 获取下一步 action
from sibyl.orchestrate import cli_record     # 记录阶段完成并推进
from sibyl.orchestrate import cli_pause      # 暂停项目
from sibyl.orchestrate import cli_resume     # 恢复项目
from sibyl.orchestrate import cli_status     # 查看项目状态
from sibyl.orchestrate import cli_list_projects  # 列出所有项目
```

**不存在的函数**：`load_state`、`get_state`、`get_project` 等。查状态用 `cli_status`。

## 进度追踪

在进入 LOOP 之前，为当前迭代的每个剩余 stage 创建独立 Task：
1. 调用 `cli_status` 获取当前 stage 和 iteration
2. 阶段全集（按顺序）: literature_search → idea_debate → planning → pilot_experiments → experiment_cycle → result_debate → experiment_decision → writing_outline → writing_sections → writing_critique → writing_integrate → writing_final_review → writing_latex → review → reflection → lark_sync → quality_gate → done
3. 从当前 stage 到 done，为每个剩余阶段使用 `TaskCreate` 创建一个 task：
   - subject: `[{project}] #{iteration} - {stage_name}`
   - description: 该阶段的简要说明
   - 按顺序用 `TaskUpdate(addBlockedBy=[前一个taskId])` 建立依赖链
4. 记住第一个 task 的 ID（当前 stage），循环中用它追踪进度
5. 每完成一个 stage（cli_record 成功后）：
   - `TaskUpdate(taskId=当前stage的taskId, status="completed")`
   - 下一个 stage 的 task 会自动 unblock
6. 进入新迭代时（quality_gate 后）：先把旧迭代所有未完成 task 标记 `completed`，再为新迭代创建新的 task 链

## 编排循环

```
LOOP:
  1. 获取下一步:
     .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('WORKSPACE_PATH')"
     -> 返回 JSON: {action_type, skills, team, agents, description, stage}

  2. 根据 action_type 执行:

     "skill": 使用 Skill 工具调用对应的 sibyl skill。
     "skills_parallel": 并行调用多个 sibyl skill（如 supervisor + codex-reviewer）。
       对 skills 列表中的每个 skill，使用 Agent 工具并行启动。
     "agents_parallel": 并行启动多个 agent（如 cross-critique 的 6 个动态 prompt agent）。
       对 agents 列表中的每个 agent，使用 Agent 工具并行启动。
     "team": 使用 Agent Team 进行结构化多 agent 协作讨论。
       前置条件：需要环境变量 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
       action.team 包含结构化字段：team_name, teammates[], post_steps[], prompt
       1. TeamCreate(team_name=action.team.team_name)
       2. 遍历 action.team.teammates，为每个 teammate:
          a. TaskCreate(
               subject=teammate.name,
               description="调用 Skill /teammate.skill teammate.args"
             )
          b. 记住返回的 taskId
       3. 并行启动所有 teammates（使用 Agent 工具）:
          对每个 teammate:
            - team_name: action.team.team_name
            - name: teammate.name
            - subagent_type: "general-purpose"（需要完整工具访问）
            - prompt: "你是 {teammate.name}，请查看 TaskList 找到分配给你的任务，
                       用 TaskUpdate(status='in_progress') 标记开始，
                       然后按 description 中的指令执行 Skill，
                       完成后 TaskUpdate(status='completed')"
       4. 由 Lead（当前 session）为每个 teammate 分配任务:
          TaskUpdate(taskId=对应taskId, owner=teammate.name)
          注意：Lead 主动分配，而非让 teammate 自行认领
       5. 等待所有 teammates 完成:
          teammate 完成任务后会自动发送 idle 通知到 lead，无需轮询。
          当所有 teammate 都 idle 且 TaskList 显示全部 completed 时继续。
       6. 逐一关闭各 teammate:
          SendMessage(type="shutdown_request", recipient=teammate.name,
                      content="任务完成，请关闭")
          teammate 收到后用 SendMessage(type="shutdown_response", approve=true) 回复
       7. 顺序执行 action.team.post_steps（如有）:
          - type="skill": 使用 Skill 工具调用（如 sibyl-synthesizer）
          - type="codex": 使用 Skill 工具调用 sibyl-codex-reviewer
       8. 收集 teammates 和 post_steps 写入的产出文件
     "bash": 执行 bash_command。
     "paused": 项目已暂停，每 5 分钟检查一次，最长等待 5 小时。
     "done": 报告完成，输出 <promise>SIBYL_PIPELINE_COMPLETE</promise>。

  错误处理:
     遇到错误必须先尝试修复，不要跳过继续！
     - ImportError / NameError -> 检查 CLI API 参考，使用正确的函数名
     - rate limit -> cli_pause -> 进入 paused 等待循环
     - 其他错误 -> 分析根因 -> 重试一次 -> 连续失败 2 次 -> 暂停

  3. 记录结果（使用 cli_next 返回的 stage 字段）:
     .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('WORKSPACE_PATH', 'STAGE')"

  4. 阶段间处理（每次 cli_record 成功后执行）:

     a0. 更新进度 Task:
         - TaskUpdate(taskId=当前stage的taskId, status="completed")
         - 下一个 stage 的 task 自动 unblock（无需手动 removeBlockedBy）
         - 如果进入新迭代（quality_gate 后），先把所有旧 task 标记 completed，
           再为新迭代的各 stage 创建新 task 链（同"进度追踪"步骤 3-4）

     a. 阶段汇总:
        - 用 1-3 句中文总结本阶段完成的工作和关键发现
        - 如果是长上下文阶段（literature_search, idea_debate, experiment_*,
          writing_*, critique_*, review_*），将汇总写入阶段文档：
          写入 WORKSPACE_PATH/logs/stage_summaries/STAGE.md
          内容包括：阶段名、时间、关键产出文件列表、核心发现/结论摘要
        - 这份文档将在下一阶段开始时被读取作为上下文

     b. 更新研究日志:
        - 追加一条记录到 WORKSPACE_PATH/logs/research_diary.md
        - 格式: ## [STAGE] YYYY-MM-DD HH:MM\n<汇总内容>\n

     c. 飞书同步（轻量版）:
        - 跳过：完整飞书同步在 lark_sync 阶段由 sibyl-lark-sync skill 统一执行
        - 如需手动触发：/sibyl-research:sync {project}

     d. 压缩上下文:
        - 执行 /compact 压缩当前会话上下文
        - 这确保下一阶段在干净的上下文中启动

  5. 重复直到 done。
```
