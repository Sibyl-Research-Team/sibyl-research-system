---
description: "Debug 模式：单步执行编排循环，不启动 Ralph Loop"
argument-hint: "<spec_path_or_project_name>"
---

# /sibyl-research:debug

Debug 模式：单步执行编排循环，不启动 Ralph Loop，方便调试和修复问题。

**所有用户可见的输出必须使用中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

## 与 /sibyl-start 的区别

- 不启动 Ralph Loop 循环
- 每次只执行一个 action，然后停下来等待用户确认
- 出错时直接停下来，方便排查和修复
- 可反复执行 `/sibyl-debug` 继续下一步

## 输入方式

- Markdown 路径: `workspaces/project/spec.md`
- 纯文本 topic
- 项目名称（已初始化的项目直接跳过初始化）

参数: `$ARGUMENTS`

## 步骤

0. **打印 debug 横幅**：

```
╔══════════════════════════════════════════════════════════════╗
║       SIBYL SYSTEM  ·  Debug Mode (单步调试)                 ║
╚══════════════════════════════════════════════════════════════╝
```

然后执行以下命令获取当前所有项目快照并在横幅中展示：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_list_projects; cli_list_projects()"
```
展示项目状态表格。

1. **判断参数并初始化**（如果项目已存在则跳过初始化）：
   - 从参数中提取项目名（如果是路径如 `workspaces/ttt-dlm/spec.md`，提取 `ttt-dlm`；如果是纯名称如 `ttt-dlm`，直接使用）
   - 检查 `workspaces/<project>/state.json` 是否存在：
     - **已存在**：跳过初始化，直接进入步骤 2
     - **不存在 + 参数是 .md 路径**：
       ```bash
       cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init_from_spec; cli_init_from_spec('SPEC_PATH')"
       ```
     - **不存在 + 参数是纯文本**：
       ```bash
       cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init; cli_init('TOPIC')"
       ```
   - 如果项目处于 paused 状态，自动 resume：
     ```bash
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/PROJECT')"
     ```

1.5. **创建当前步骤 Task**（仅追踪本次单步执行）：
   - 调用 `cli_status` 获取当前 stage 和 iteration
   - 使用 `TaskCreate` 创建一个 task：
     - subject: `[{project}] debug #{iteration} - {current_stage}`
     - description: 当前阶段的简要说明

2. **单步获取下一个 action**：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('workspaces/PROJECT')"
```

3. **显示 action 详情**，格式：
```
  [DEBUG] Action 详情
  ──────────────────
  action_type: xxx
  stage:       xxx
  description: xxx
```

4. **执行该 action**（同编排循环逻辑）：

   "skill": 使用 Skill 工具调用对应的 sibyl skill。
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
   "lark_sync": 由 sibyl-lark-sync skill 自动执行飞书同步。
   "paused": 自动 resume 并重新获取 action。
   "done": 报告完成。

5. **记录结果**：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('workspaces/PROJECT', 'STAGE')"
```

5.5. **阶段间处理**（cli_record 成功后执行）：

   a0. **更新进度 Task**：TaskUpdate(taskId=步骤1.5创建的taskId, status="completed")。

   a. **阶段汇总**：用 1-3 句中文总结本阶段完成的工作和关键发现。
      如果是长上下文阶段（literature_search, idea_debate, experiment_*,
      writing_*, critique_*, review_*），将汇总写入阶段文档：
      写入 WORKSPACE_PATH/logs/stage_summaries/STAGE.md
      内容包括：阶段名、时间、关键产出文件列表、核心发现/结论摘要

   b. **更新研究日志**：追加一条记录到 WORKSPACE_PATH/logs/research_diary.md
      格式: ## [STAGE] YYYY-MM-DD HH:MM\n<汇总内容>\n

   c. **飞书同步**：跳过，完整同步在 lark_sync 阶段由 skill 统一执行。

   注意：debug 模式**不执行 /compact**，因为每次执行一步就停下来，新 session 自然有新上下文。

6. **停下来等待**：打印结果摘要，提示用户：
```
  [DEBUG] 当前步骤执行完毕
  ──────────────────────
  已完成：<stage> - <description>
  下一步：再次执行 /sibyl-debug <project> 继续
```

## 错误处理

- 出错时直接报告错误详情，**不自动重试**
- 用户可修复问题后重新执行 `/sibyl-debug`
- 不调用 cli_pause，不进入等待循环
