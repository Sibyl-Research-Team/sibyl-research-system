# 编排循环（共享参考文档）

本文档是 start.md、resume.md、continue.md 共用的编排循环定义。
**不要直接调用此文档**。运行时 control-plane prompt 由
`render_control_plane_prompt('loop', workspace_path=...)` 动态编译；本文档仅作为人类参考说明保留。

## CLI API 参考（重要：只使用以下函数，不要猜测其他函数名）

```python
from sibyl.orchestrate import cli_next       # 获取下一步 action
from sibyl.orchestrate import cli_record     # 记录阶段完成并推进
from sibyl.orchestrate import cli_pause      # 仅供 /stop 写入人工停止标记
from sibyl.orchestrate import cli_resume     # 清除停止/遗留暂停标记并恢复项目，返回恢复提示
from sibyl.orchestrate import cli_status     # 查看项目状态
from sibyl.orchestrate import cli_list_projects  # 列出所有项目
from sibyl.orchestrate import cli_init       # 初始化（topic 模式）
from sibyl.orchestrate import cli_init_from_spec # 初始化（spec 模式）
from sibyl.orchestrate import cli_dispatch_tasks # 动态调度: 空闲 GPU 派发排队任务
from sibyl.orchestrate import cli_experiment_status # 实验状态面板（含进度、运行任务、预估时间）
from sibyl.orchestrate import cli_experiment_supervisor_drain_wake # 读取后台 supervisor 的主系统唤醒请求
from sibyl.orchestrate import cli_sentinel_session  # 保存 session ID 供 Sentinel 使用
from sibyl.orchestrate import cli_sentinel_config   # 获取 Sentinel 配置状态
```

**不存在的函数**：`load_state`、`get_state`、`get_project` 等。查状态用 `cli_status`。

## 进度追踪

在进入 LOOP 之前，为当前迭代的每个剩余 stage 创建独立 Task：
1. 调用 `cli_status` 获取当前 stage 和 iteration
2. 阶段全集（按顺序）: literature_search → idea_debate → planning → pilot_experiments → experiment_cycle → result_debate → experiment_decision → writing_outline → writing_sections → writing_critique → writing_integrate → writing_final_review → writing_latex → review → reflection → quality_gate → done
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

     "skill": 使用 Skill 工具调用对应的 sibyl skill。
     "skills_parallel": 并行调用 action.skills 列表中的所有 skill。
       使用 Agent 工具并行启动多个 subagent，每个调用对应的 Skill。
       等待所有 subagent 完成后继续。
       注意：实验阶段的 action 可能包含 estimated_minutes 字段，
       表示预计运行时间（分钟）。如果 >0，各 subagent 应据此设置
       SSH 超时和轮询间隔，避免过早超时或过度轮询浪费 token。
       实验完成后，编排器会自动检查是否有剩余任务并循环执行下一批。

       **实验监控与动态调度（experiment_monitor）：**
       如果 `skill` / `skills_parallel` / `experiment_wait` action 包含 experiment_monitor 字段，在启动实验 skill 的同时：
       - **立即**用 Agent tool (`run_in_background=true`) 启动 `experiment_monitor.background_agent`
       - 该后台 supervisor 负责刷新 GPU 空闲状态、派发排队任务、以及发现运行时间/状态漂移后的干预
       - 主系统必须把 `experiment_monitor.wake_cmd` 当作高优先级 inbox：后台 supervisor 会把“重大结果”或“需要主系统参与”的事项主动投递到这里
       - 不要等待它完成；主循环继续按下面的 experiment_wait / 状态面板协议工作

       **监控轮询循环（SSH MCP 模式）：**
       ```
       WHILE true:
         1. 不要整段傻睡；按 `min(experiment_monitor.wake_check_interval_sec, experiment_monitor.poll_interval_sec)` 分段 sleep
            每段 sleep 结束先调用 `experiment_monitor.wake_cmd`
            如果返回 `wake_requested=true`：
              - 立即停止等待，先处理 events
              - 若任一 event.requires_main_system=true 或 kind=needs_main_system，主系统必须立刻介入，不要等到下一轮大轮询
         2. 用 SSH MCP execute-command 执行 check_cmd，解析 task_id:DONE/PENDING
         3. **打印状态面板（每次轮询必须执行）：**
            调用 cli_experiment_status 获取状态 JSON:
            .venv/bin/python3 -c "from sibyl.orchestrate import cli_experiment_status; cli_experiment_status('WORKSPACE_PATH')"
            从返回的 JSON 中提取 display 字段的值，然后**直接用文本消息输出给用户**（不要通过 Bash print，Bash 输出会被 UI 折叠）。
            示例：拿到 result 后，直接在对话中输出 result.display 的内容。

         4. 读取 marker_file 检查状态:
            - status="all_complete": 所有任务完成，跳出循环
            - status="timeout": 监控超时，增大轮询间隔后继续轮询（不暂停）
            - dispatch_needed=true: 有任务刚完成，GPU 释放

         5. **动态调度（dispatch_needed=true 时）：**
            a. 调用 cli_dispatch_tasks 获取新任务:
               .venv/bin/python3 -c "from sibyl.orchestrate import cli_dispatch_tasks; cli_dispatch_tasks('WORKSPACE_PATH')"
            b. 如果返回 dispatch 非空:
               - 为每个 skill 启动新的 Agent（run_in_background）
               - 更新 check_cmd 加入新 task_ids
               - 输出: "动态调度: task_X -> GPU[Y]"
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
         1. 不要一次 sleep 到下个大轮询点；按 `experiment_monitor.wake_check_interval_sec` 分段 sleep
            每段 sleep 结束后先执行:
            .venv/bin/python3 -c "from sibyl.orchestrate import cli_experiment_supervisor_drain_wake; cli_experiment_supervisor_drain_wake('WORKSPACE_PATH')"
            如果返回 `wake_requested: true`：
              - 立即读取 events
              - 如果事件表示“已解决关键问题”或“需要主系统参与”，立刻跳出等待分支处理，不要拖到下一个 2/5/10 分钟轮询
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
            如果后台 supervisor 已经在 events 里提供诊断/已做动作/建议下一步，优先复用，不要重复排查同一问题
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
       - 剩余 ≤30min: 每 2min
       - 剩余 30-120min: 每 5min
       - 剩余 >120min: 每 10min
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
       **永不放弃**: 持续轮询直到有空闲 GPU，忽略 max_attempts 上限。
       每 10 轮输出一次日志避免 token 浪费。
     "done": 单轮迭代完成。
       1. 输出 <promise>SIBYL_PIPELINE_COMPLETE</promise>
       2. 检查 quality_gate 分数是否达标
       3. 如果未达标或有改进空间，自动开始下一轮迭代（cli_next 会处理）
       4. 如果已达到最高质量，开始探索新的研究方向或改进现有结果
     "stopped": 项目曾被用户显式 `/stop`。
       1. 当前命令若是用户主动触发的 `/continue` 或 `/resume`，先调用 `cli_resume`
       2. 再重新调用 `cli_next` 继续执行
       3. Sentinel 不应对 `stopped` 项目自动拉起

  错误处理（铁律：永不停机）:
     遇到错误必须自主解决，系统不能停下来！
     - ImportError / NameError -> 检查 CLI API 参考，使用正确的函数名
     - rate limit -> sleep 等待冷却（1min → 5min → 15min 指数退避）后重试
     - SSH/网络故障 -> 指数退避重试（30s → 1min → 5min → 15min）
     - 其他错误 -> 分析根因 -> 重试 -> 连续失败 3 次 -> 记录日志跳过当前步骤 -> 继续下一步
     - 任何情况下都**不调用 cli_pause**，除非是用户通过 /sibyl-research:stop 主动请求
     - 如果发现遗留 `paused_at` 状态，不要停下来等人；重新调用 `cli_next`，它会自动清除暂停标记并继续执行

  3. 记录结果（使用 cli_next 返回的 stage 字段）:
     .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('WORKSPACE_PATH', 'STAGE')"
     -> 返回 JSON，至少包含 {status, new_stage}；当飞书后台同步需要启动时还会返回 `sync_requested: true`

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

     c. 飞书后台同步（Hook 自动触发，无需手动处理）:
        - **已由 PostToolUse hook 自动处理**: `.claude/hooks/lark-sync-trigger.sh`
          监听 cli_record 的 Bash 调用，检测 `sync_requested: true` 后注入上下文
        - 当你看到 `[LARK-SYNC-HOOK]` 上下文提示时，按提示启动后台 Agent:
          使用 Agent tool（run_in_background=true）调用 Skill `sibyl-lark-sync`，参数为 WORKSPACE_PATH
        - **不要等待完成**，继续主循环。飞书同步失败不能阻塞研究流程
        - 触发日志: `WORKSPACE_PATH/lark_sync/pending_sync.jsonl`
        - 同步结果: `WORKSPACE_PATH/lark_sync/sync_status.json`
        - 手动触发: `/sibyl-research:sync {project}`
        - 如果会话是在 `/sibyl-research:resume` 或 `/sibyl-research:continue` 后恢复，
          也要检查 `pending_sync.jsonl`；只要还有未消费条目，就先把 `sibyl-lark-sync`
          后台 agent 重新拉起来，再继续主循环

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
