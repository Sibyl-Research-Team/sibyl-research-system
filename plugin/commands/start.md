---
description: "启动研究项目并自动进入持续迭代循环"
argument-hint: "<spec_path_or_topic>"
---

# /sibyl-research:start

启动研究项目并自动进入持续迭代循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: `$SIBYL_ROOT`

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

## 输入方式

- Markdown 路径: `workspaces/project/spec.md`
- 纯文本 topic（兼容旧用法）

参数: `$ARGUMENTS`

## 步骤

0. **打印启动横幅**，格式如下（语言遵循项目配置，默认中文）：

```
╔═════════════════════════════════════════════════════════════════╗
║     SIBYL RESEARCH SYSTEM  ·  Autonomous Research Engine        ║
╚═════════════════════════════════════════════════════════════════╝

  项目：<project_name>
  主题：<topic（如已知）>
  阶段：initializing...
  迭代：#0

  正在启动持续迭代研究循环 →
```

然后执行以下命令获取当前所有项目快照并在横幅中展示：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_list_projects; cli_list_projects()"
```
将结果以简洁表格形式附在横幅后，显示各项目的名称、阶段、迭代数。

1. 判断参数类型并初始化：
```bash
# Markdown 模式（参数以 .md 结尾或包含路径分隔符）
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init_from_spec; cli_init_from_spec('SPEC_PATH')"
# Topic 模式
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init; cli_init('TOPIC')"
```
2. 记录返回的 `workspace_path` 和 `project_name`

2.5. **保存 Session ID 供 Sentinel 使用**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('WORKSPACE_PATH', '${CLAUDE_CODE_SESSION_ID:-}')"
   ```

3. **自动启动 Ralph Loop 持续迭代**：

   首先，将迭代指令写入临时文件（避免多行 prompt 导致 shell 解析失败）：
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

4. **启动 Sentinel 看门狗**（在 tmux 的 sibling pane 中，确保实验轮询不中断）：
   ```bash
   # 检测当前是否在 tmux 中
   if [ -n "${TMUX:-}" ]; then
     SIBYL_ROOT="$(cd /Users/cwan0785/sibyl-system && pwd)"
     CURRENT_PANE=$(tmux display-message -p '#{pane_id}')
     # 在当前 window 右侧创建窄 pane 运行 sentinel
     tmux split-window -h -l 60 \
       "bash $SIBYL_ROOT/sibyl/sentinel.sh WORKSPACE_PATH $CURRENT_PANE 120"
     # 焦点切回主 pane
     tmux select-pane -t "$CURRENT_PANE"
     echo "Sentinel 已启动（右侧 pane）"
   else
     echo "未检测到 tmux，Sentinel 未启动。建议在 tmux session 中运行。"
   fi
   ```
   注意：将 WORKSPACE_PATH 替换为实际路径。

## CLI API 参考（重要：只使用以下函数，不要猜测其他函数名）

```python
from sibyl.orchestrate import cli_next       # 获取下一步 action
from sibyl.orchestrate import cli_record     # 记录阶段完成并推进
from sibyl.orchestrate import cli_pause      # 暂停项目
from sibyl.orchestrate import cli_resume     # 恢复项目
from sibyl.orchestrate import cli_status     # 查看项目状态
from sibyl.orchestrate import cli_list_projects  # 列出所有项目
from sibyl.orchestrate import cli_init       # 初始化（topic 模式）
from sibyl.orchestrate import cli_init_from_spec # 初始化（spec 模式）
from sibyl.orchestrate import cli_dispatch_tasks # 动态调度: 空闲 GPU 派发排队任务
from sibyl.orchestrate import cli_experiment_status # 实验状态面板（含进度、运行任务、预估时间）
from sibyl.orchestrate import cli_sentinel_session  # 保存 session ID 供 Sentinel 使用
from sibyl.orchestrate import cli_sentinel_config   # 获取 Sentinel 配置状态
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
     -> 返回 JSON: {action_type, skills, team, agents, description, stage, language}

  1.5. 设置语言环境变量（每轮都要执行）:
       export SIBYL_LANGUAGE=<action.language>  (默认 "zh")
       这控制 agent prompt 的语言版本。

  2. 根据 action_type 执行:

     "skill": 使用 Skill 工具调用对应的 sibyl skill（包括 lark_sync 阶段）。
     "skills_parallel": 并行调用 action.skills 列表中的所有 skill。
       使用 Agent 工具并行启动多个 subagent，每个调用对应的 Skill。
       等待所有 subagent 完成后继续。
       注意：实验阶段的 action 可能包含 estimated_minutes 字段，
       表示预计运行时间（分钟）。如果 >0，各 subagent 应据此设置
       SSH 超时和轮询间隔，避免过早超时或过度轮询浪费 token。
       实验完成后，编排器会自动检查是否有剩余任务并循环执行下一批。

       **实验监控与动态调度（experiment_monitor）：**
       如果 action 包含 experiment_monitor 字段，在启动实验 skill 的同时：

       **监控轮询循环（SSH MCP 模式）：**
       ```
       WHILE true:
         1. 等待 experiment_monitor.poll_interval_sec 秒
         2. 用 SSH MCP execute-command 执行 check_cmd，解析 task_id:DONE/PENDING
         3. **打印状态面板（每次轮询必须执行）：**
            调用 cli_experiment_status 获取状态 JSON:
            .venv/bin/python3 -c "from sibyl.orchestrate import cli_experiment_status; cli_experiment_status('WORKSPACE_PATH')"
            从返回的 JSON 中提取 display 字段的值，然后**直接用文本消息输出给用户**（不要通过 Bash print，Bash 输出会被 UI 折叠）。
            示例：拿到 result 后，直接在对话中输出 result.display 的内容。

         4. 读取 marker_file 检查状态:
            - status="all_complete": 所有任务完成，跳出循环
            - status="timeout": 监控超时，报告并暂停
            - dispatch_needed=true: 有任务刚完成，GPU 释放

         5. **动态调度（dispatch_needed=true 时）：**
            a. 调用 cli_dispatch_tasks 获取新任务:
               .venv/bin/python3 -c "from sibyl.orchestrate import cli_dispatch_tasks; cli_dispatch_tasks('WORKSPACE_PATH')"
            b. 如果返回 dispatch 非空:
               - 为每个 skill 启动新的 Agent（run_in_background）
               - 更新 check_cmd 加入新 task_ids
               - 输出: "🚀 动态调度: task_X → GPU[Y]"
            c. 如果 dispatch 为空（no_ready_tasks/no_free_gpus）: 继续等待
       ```

       **Bash 直连模式（备选）：**
       1. 将 experiment_monitor.script 写入 /tmp/sibyl_exp_monitor.sh
       2. 使用 Bash 工具后台执行: `bash /tmp/sibyl_exp_monitor.sh &`（run_in_background）
       3. 监控脚本定期 SSH 检查 DONE 标记文件，进度写入 marker_file
       4. 主 session 定期读取 marker_file，dispatch_needed=true 时调用 cli_dispatch_tasks
       5. 每次读取 marker_file 后调用 cli_experiment_status 打印状态面板
     "agents_parallel": 遗留格式（cross-critique 仍用此方式）。
       依次执行 action.agents 列表中的各 agent 任务。
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
     "experiment_wait": 实验已在远程运行，定期轮询直到完成。
       **绝对不要暂停项目**，必须持续轮询直到所有任务完成。
       ```
       WHILE true:
         1. 等待 experiment_monitor.poll_interval_sec 秒（使用 sleep）
         2. 用 SSH MCP execute-command 执行 check_cmd，解析 task_id:DONE/PENDING
         3. **打印状态面板（每次轮询必须执行）：**
            调用 cli_experiment_status:
            .venv/bin/python3 -c "from sibyl.orchestrate import cli_experiment_status; cli_experiment_status('WORKSPACE_PATH')"
            从返回的 JSON 中提取 display 字段，**直接用文本消息输出给用户**
         4. 检查轮询结果：
            - 所有 task_id 都是 DONE: 执行步骤 7 同步状态，然后跳出循环继续 cli_record
            - 有 DONE + 有 PENDING: 输出 "部分完成"，执行步骤 5 动态调度
            - 全部 PENDING: 继续等待
         5. **动态调度（有任务刚完成时）：**
            调用 cli_dispatch_tasks 获取新任务:
            .venv/bin/python3 -c "from sibyl.orchestrate import cli_dispatch_tasks; cli_dispatch_tasks('WORKSPACE_PATH')"
            如果返回 dispatch 非空，为每个 skill 启动新 Agent（run_in_background）
         6. 可选：用 pid_check_cmd 检查进程存活，用 progress_check_cmd 查看详细进度
         7. **同步实验状态（跳出循环前必须执行）：**
            生成 SSH 检测脚本并执行恢复，确保 experiment_state.json 与远程状态一致：
            a. 生成检测脚本:
               .venv/bin/python3 -c "from sibyl.orchestrate import cli_recover_experiments; cli_recover_experiments('WORKSPACE_PATH')"
               → 返回 JSON 含 script 字段
            b. 用 SSH MCP execute-command 执行该 script，获取 ssh_output
            c. 应用检测结果:
               .venv/bin/python3 -c "from sibyl.orchestrate import cli_apply_recovery; cli_apply_recovery('WORKSPACE_PATH', '''SSH_OUTPUT''')"
            这一步确保 _natural_next_stage 检测到所有任务已完成，正确推进到下一阶段。
       ```
       **轮询间隔是自适应的**（由 orchestrator 根据预计剩余时间计算）：
       - 剩余 ≤15min: 每 5min
       - 剩余 15-60min: 每 10min
       - 剩余 1-4h: 每 15min
       - 剩余 >4h: 每 30min
       注意：轮询等待期间使用 sleep 而非 LLM 推理，不消耗 token。
     "gpu_poll": GPU 轮询等待（所有 GPU 被占用）。
       按 CLAUDE.md 中的 GPU 轮询协议执行，每次轮询时输出状态提示：
       ```
       +-----------------------------------------+
       |      SIBYL - Waiting for GPUs            |
       +-----------------------------------------+
       |  Poll #{N}: No free GPUs available
       |  Threshold: <threshold>MB free VRAM
       |  Checking every <interval>min via SSH
       |  System running, please wait...
       +-----------------------------------------+
       ```
       如果 `action.gpu_poll.max_attempts > 0`：
       - 必须尊重该上限，优先执行 `action.gpu_poll.script`
       - script / 手工轮询达到上限后，调用
         `.venv/bin/python3 -c "from sibyl.orchestrate import cli_pause; cli_pause('WORKSPACE_PATH', 'gpu_poll_timeout')"`
       - 向用户明确报告 “GPU 轮询超时，项目已暂停，等待手动恢复或稍后 resume”
     "paused": 项目已暂停，每 5 分钟检查一次，最长等待 5 小时。
       每次检查时输出: "系统暂停中，等待恢复... (已等待 Xmin)"
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
        - 用 1-3 句项目语言对应的语言总结本阶段完成的工作和关键发现
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

  5. Checkpoint 协议（子步骤恢复）:

     部分 stage（writing_sections, writing_critique, idea_debate, result_debate）
     支持子步骤 checkpoint。

     执行时:
     - cli_next() 返回的 action 若包含 checkpoint_info，表示该 stage 支持 checkpoint
     - checkpoint_info.remaining_steps 列出需要执行的子步骤
     - checkpoint_info.completed_steps 列出已完成的子步骤（可作为上下文参考）
     - 如果 checkpoint_info.all_complete == true，直接 cli_record() 推进

     每个子步骤完成后（team 模式下每个 teammate 写完文件后）:
     .venv/bin/python3 -c "from sibyl.orchestrate import cli_checkpoint; cli_checkpoint('WORKSPACE_PATH', 'STAGE', 'STEP_ID')"

     恢复机制: 中断后重新 cli_next() 会自动检测 checkpoint，只返回未完成的子步骤。

  6. 重复直到 done。
```
