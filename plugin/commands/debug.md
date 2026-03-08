---
description: "Debug 模式：单步执行编排循环，不启动 Ralph Loop"
argument-hint: "<spec_path_or_project_name>"
---

# /sibyl-research:debug

Debug 模式：单步执行编排循环，不启动 Ralph Loop，方便调试和修复问题。

**所有用户可见的输出必须使用中文。**

工作目录: `/Users/cwan0785/sibyl-system`

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
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_list_projects; cli_list_projects()"
```
展示项目状态表格。

1. **判断参数并初始化**（如果项目已存在则跳过初始化）：
   - 从参数中提取项目名（如果是路径如 `workspaces/ttt-dlm/spec.md`，提取 `ttt-dlm`；如果是纯名称如 `ttt-dlm`，直接使用）
   - 检查 `workspaces/<project>/state.json` 是否存在：
     - **已存在**：跳过初始化，直接进入步骤 2
     - **不存在 + 参数是 .md 路径**：
       ```bash
       cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init_from_spec; cli_init_from_spec('SPEC_PATH')"
       ```
     - **不存在 + 参数是纯文本**：
       ```bash
       cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init; cli_init('TOPIC')"
       ```
   - 如果项目处于 paused 状态，自动 resume：
     ```bash
     cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/PROJECT')"
     ```

2. **单步获取下一个 action**：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('workspaces/PROJECT')"
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
   "team": 使用 Agent Team 进行多 agent 协作讨论。
     1. 使用 TeamCreate 创建团队，team_name 为 "sibyl-{stage}"
     2. 读取 action 的 team.prompt
     3. 根据 team.prompt 中的指令，使用 TaskCreate 创建各 teammate 的任务
     4. 使用 Agent 工具（带 team_name 和 name 参数）启动各 teammate
     5. 通过 TaskUpdate 分配任务给各 teammate
     6. 等待所有 teammates 完成任务（通过 TaskList 检查）
     7. 使用 SendMessage (type: "shutdown_request") 关闭各 teammate
     8. 收集各 teammate 写入的产出文件
   "bash": 执行 bash_command。
   "lark_sync": 由 sibyl-lark-sync skill 自动执行飞书同步。
   "paused": 自动 resume 并重新获取 action。
   "done": 报告完成。

5. **记录结果**：
```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('workspaces/PROJECT', 'STAGE')"
```

5.5. **阶段间处理**（cli_record 成功后执行）：

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
