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
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('WORKSPACE_PATH')"
     -> 返回 JSON: {action_type, skills, team, agents, description, stage, language}

  1.5. 设置语言环境变量（每轮都要执行）:
       export SIBYL_LANGUAGE=<action.language>  (默认 "zh")
       这控制 agent prompt 的语言版本。

  2. 执行 action:

     **首选: 读取 execution_script 按指令执行**
     cli_next() 返回的 JSON 包含 `execution_script` 字段——预编译的精简执行指令。
     如果 execution_script 非空，直接按其中的步骤机械执行即可，无需解读 action_type。
     execution_script 已包含: 需要调用的工具名+参数、完成后的 cli_record 命令、错误处理说明。

     **Fallback: execution_script 为空时，按 action_type 手动分发**
     仅在 execution_script 为空或执行失败时，才回退到以下 action_type 分发逻辑。

     **实验监控与动态调度（experiment_monitor）：**
     如果 action 包含 experiment_monitor 字段：
     - **PostToolUse hook 自动处理**: `on-bash-complete.sh` 检测 cli_next 输出，自动启动 bash 监控 daemon
     - **仅当 `experiment_monitor.background_agent` 存在时**，才手动启动后台 supervisor
     - 主系统把 `experiment_monitor.wake_cmd` 当作高优先级 inbox

     **action_type 参考（fallback 时使用）：**
     - “skill”: Skill tool 调用 action.skills[0]
     - “skills_parallel”: 并行 Agent 各调用一个 Skill
     - “team”: TeamCreate → TaskCreate×N → Agent×N → post_steps
     - “agents_parallel”: 遗留格式（cross-critique），依次执行 action.agents
     - “bash”: Bash tool 执行 bash_command
     - “experiment_wait”: 持续轮询直到实验完成（绝不暂停），自适应间隔
     - “gpu_poll”: 执行 gpu_poll.script 轮询空闲 GPU（永不放弃）
     - “done”: 输出 SIBYL_PIPELINE_COMPLETE，检查质量门
     - “stopped”: 用户 /stop 后的停机状态，需 cli_resume 后 cli_next

     **experiment_wait 轮询协议（无论 execution_script 还是 fallback 都遵循）：**
     ```
     WHILE true:
       1. 按 wake_check_interval_sec 分段 sleep，每段结束检查 wake_cmd
          wake_requested=true 且 requires_main_system=true → 立即介入
       2. SSH check_cmd → 解析 task_id:DONE/PENDING
       3. cli_experiment_status → 直接输出 display 字段（不用 Bash echo）
       4. 读 marker_file: all_complete→同步状态后 break, dispatch_needed→调度
       5. 动态调度: cli_dispatch_tasks → 启动新 Agent(run_in_background)
       6. 跳出前必须: cli_recover_experiments → SSH 执行 → cli_apply_recovery
     ```

  错误处理（铁律：永不停机）:
     遇到错误必须自主解决，系统不能停下来！
     - ImportError / NameError -> 检查 CLI API 参考，使用正确的函数名
     - rate limit -> sleep 等待冷却（1min → 5min → 15min 指数退避）后重试
     - SSH/网络故障 -> 指数退避重试（30s → 1min → 5min → 15min）
     - 其他错误 -> 分析根因 -> 重试 -> 连续失败 3 次 -> 记录日志跳过当前步骤 -> 继续下一步
     - 任何情况下都**不调用 cli_pause**，除非是用户通过 /sibyl-research:stop 主动请求
     - 如果发现遗留 `paused_at` 状态，不要停下来等人；重新调用 `cli_next`，它会自动清除暂停标记并继续执行

  3. 记录结果（使用 cli_next 返回的 stage 字段）:
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('WORKSPACE_PATH', 'STAGE')"
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
        - **由 PostToolUse hook 自动处理**: `plugin/hooks/scripts/on-bash-complete.sh`
          监听 cli_record 的 Bash 调用，检测 `sync_requested: true` 后注入上下文
        - 当你看到 `[LARK-SYNC-HOOK]` 上下文提示时，按提示启动后台 Agent:
          使用 Agent tool（run_in_background=true）调用 Skill `sibyl-lark-sync`，参数为 WORKSPACE_PATH
        - **不要等待完成**，继续主循环。飞书同步失败不能阻塞研究流程
        - 触发日志: `WORKSPACE_PATH/lark_sync/pending_sync.jsonl`
        - 同步结果: `WORKSPACE_PATH/lark_sync/sync_status.json`
        - 手动触发: `/sibyl-research:sync {project}`
        - SessionStart hook 会在会话启动时自动检测 pending sync 并通过系统消息提醒

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
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_checkpoint; cli_checkpoint('WORKSPACE_PATH', 'STAGE', 'STEP_ID')"

     恢复机制: 中断后重新 cli_next() 会自动检测 checkpoint，只返回未完成的子步骤。

  6. 重复直到 done。
```
