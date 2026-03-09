# Sibyl Research System

## 运行环境建议

**强烈建议在 tmux 中运行 Claude Code**，以支持 Sentinel 看门狗自动恢复。安装：`brew install tmux`(macOS) / `apt install tmux`(Linux)。启动：`tmux new -s sibyl`。

## Python 环境（强制规则）

本项目使用 **venv** 环境，位于 `.venv/`（Python 3.12，基于 conda base 创建）。

**所有 Python 调用必须使用 `.venv/bin/python3`**，禁止使用裸 `python3`。

原因：系统 `python3` 指向 homebrew Python 3.14，缺少 `pyyaml`、`rich` 等依赖，会导致 `import yaml` 等失败。

```bash
# 正确
.venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('...')"
.venv/bin/pip install <package>

# 错误
python3 -c "from sibyl.orchestrate import ..."
pip install <package>
```

依赖由 `pyproject.toml` / `pip install -e .` 管理。`requirements.txt` 仅保留最小兼容依赖清单。如需重建环境：
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e .
```

## 工作目录

所有 Sibyl CLI 命令（`cli_next`, `cli_record` 等）必须在项目根目录下执行，因为 `from sibyl.xxx` 依赖包路径。

## Agent 架构（context: fork Skills）

Sibyl 的所有 agent 角色已封装为 `context: fork` skill，运行在独立 subagent context 中：

### Agent Tier 定义（`.claude/agents/`）
- `sibyl-heavy` → Opus 4.6（synthesizer, supervisor, editor, critic, reflection）
- `sibyl-standard` → Opus 4.6（literature, planner, experimenter, idea generation, writing）
- `sibyl-light` → Sonnet 4.6（optimist, skeptic, strategist, section-critic, cross-critique）

### Skills（`.claude/skills/sibyl-*/`）
编排器返回的 action 包含 `action_type: "skill"` 或 `"skills_parallel"`，主 session 通过 `/sibyl-xxx` 或 Skill tool 调用。每个 skill 通过 `!`command`` 动态加载对应的 prompt 模板。
`.claude/agents/*.md` 与 `.claude/skills/*/SKILL.md` 属于运行时资产，必须和 Python 编排器一起版本管理。

### Action 类型
| action_type | 说明 |
|---|---|
| `skill` | 单个 fork skill 执行 |
| `skills_parallel` | 多个 fork skill 并行 |
| `team` | Agent Team 多人协作，结构为 `team_name + teammates[] + post_steps[] + prompt` |
| `agents_parallel` | 遗留：cross-critique 仍用此方式（6 个动态 prompt） |
| `bash` | 执行 shell 命令 |
| `gpu_poll` | GPU 轮询等待（见下方说明） |
| `experiment_wait` | 实验运行中，自适应轮询等待完成（见下方说明） |
| `done` / `paused` | 终止/暂停 |

### GPU 轮询（`gpu_poll` action）
当所有 GPU 被占用时，orchestrator 返回 `action_type: "gpu_poll"`，主 session 执行：
```
1. **优先执行 `action.gpu_poll.script`**：
   - 该脚本已经内置 `interval_sec`、aggressive mode、`max_attempts`
   - exit 0: 找到空闲 GPU，marker_file 已写好
   - exit 1: 达到 `action.gpu_poll.max_attempts` 仍无空闲 GPU
2. 如果不能直接执行 script，才按以下协议手工实现：
   - 用 SSH MCP (execute-command, connection=action.gpu_poll.ssh_connection)
     执行 action.gpu_poll.query_cmd
   - 调用 parse_free_gpus(output, candidate_gpu_ids, threshold_mb) 解析结果
   - 如果有空闲 GPU:
     - 写入 marker_file: {"free_gpus": [...], "poll_count": N}
     - 重新调用 cli_next() 获取实验任务
   - 如果没有空闲 GPU:
     - sleep action.gpu_poll.interval_sec 秒
     - 若 `action.gpu_poll.max_attempts == 0`，继续轮询
     - 若 `action.gpu_poll.max_attempts > 0` 且达到上限，调用
       `.venv/bin/python3 -c "from sibyl.orchestrate import cli_pause; cli_pause('WORKSPACE_PATH', 'gpu_poll_timeout')"`
       将项目暂停，并向用户报告 GPU 轮询超时
```

### 动态 GPU 调度（实验监控中）
实验运行中，每次轮询发现有任务完成（GPU 释放）时，动态调度排队任务：
```
1. 监控检测到 dispatch_needed=true（有任务刚完成）
2. 调用 cli_dispatch_tasks(workspace_path) 获取新任务
3. 返回 {dispatch: [...assignments], skills: [...skill_dicts]}
4. 为每个 skill 启动新 experimenter Agent
```
- `gpu_progress.json` 新增 `running` map: 跟踪运行中任务的 GPU 占用
- `register_running_tasks()` / `unregister_running_task()`: 注册/注销运行中任务
- `get_next_batch()` 同时排除 completed 和 running 任务

### 实验等待轮询（`experiment_wait` action）
当实验已在远程运行且无新任务可调度时，orchestrator 返回 `action_type: "experiment_wait"`：
- **区别于 `gpu_poll`**: `gpu_poll` 等待空闲 GPU 以启动实验，`experiment_wait` 等待已运行的实验完成
- **绝对不暂停**: 系统必须持续轮询直到所有任务完成，不调用 `cli_pause`
- **自适应间隔**: 根据预计剩余时间动态调整（<30min→2min, 30-120min→5min, >120min→10min）
- **低 token 消耗**: 轮询等待期间使用 sleep，不做 LLM 推理
- **状态面板**: 每次轮询后调用 `cli_experiment_status` 打印进度横幅
- **动态调度**: 检测到任务完成后调用 `cli_dispatch_tasks` 派发排队任务
- Action 包含 `experiment_monitor` 字段: `check_cmd`(DONE 检查), `pid_check_cmd`(进程存活), `progress_check_cmd`(详细进度), `status_cmd`(状态面板), `poll_interval_sec`(轮询间隔)

### 实验状态追踪与恢复（`experiment_state.json`）
- `exp/experiment_state.json` 是实验任务生命周期的权威源（source of truth）
- 每个任务状态: pending → running → completed/failed
- Experimenter 写入远程文件: `.pid`（进程标识）、`_PROGRESS.json`（实时进度）、`_DONE`（完成标记）
- 恢复检测: SSH 批量脚本检查 DONE 标记 / PID 存活 / 进程死亡
- `cli_recover_experiments(workspace_path)`: 生成 SSH 检测脚本
- `cli_apply_recovery(workspace_path, ssh_output)`: 应用 SSH 检测结果，更新状态
- 状态同步: `experiment_state.json`（权威）→ `gpu_progress.json`（调度视图）→ 远程文件（实际状态）
- 迭代清理时归档到 `exp/history/experiment_state_iter_NNN.json`
- `_action_experiment_batch` 入口自动执行本地恢复（检查 gpu_progress 中的 completed）
- `_natural_next_stage` 同时检查 experiment_state 和 gpu_progress 中的 running 任务

### Sentinel 看门狗（自动恢复）
Sentinel 是纯 bash 看门狗脚本（`sibyl/sentinel.sh`），跑在 tmux 的 sibling pane 中，确保 Claude Code 中断后自动恢复。
- **心跳文件**: `<workspace>/sentinel_heartbeat.json`（`cli_next`/`cli_record` 自动写入）
- **Session 持久化**: `<workspace>/sentinel_session.json`（start/resume 时保存 `$CLAUDE_CODE_SESSION_ID`）
- **停止信号**: `<workspace>/sentinel_stop.json`（stop 时写入 `{"stop": true}`）
- **检测逻辑**: 每 2 分钟检查 Claude 进程 + 子进程活跃度 + 心跳新鲜度 + 实验状态
- **子进程检测**: Claude 有活跃子进程（bash/sleep/ssh）时视为正常工作中，不干预（避免误判 `bash sleep 600`）
- **唤醒策略**:
  - 进程不存在 → `claude --resume <session_id>` + `/sibyl-research:continue`
  - 进程在但心跳 >5min 且无子进程 → 注入 `/sibyl-research:continue`
- **退避机制**: 连续 3 次唤醒失败后暂停 6 分钟
- **CLI**: `cli_sentinel_session(workspace, session_id)`, `cli_sentinel_config(workspace)`
- **启动**: `/sibyl-research:start` 和 `/sibyl-research:resume` 自动在 tmux 中启动
- **停止**: `/sibyl-research:stop` 写入停止信号

### Codex 集成
- `codex_enabled`: 启用后，idea_debate、result_debate、review 阶段可引入 Codex 独立审查
- 对于你自己的本地开发机，如果 Codex MCP 和 `OPENAI_API_KEY` 都已配置完成，建议在本地 `config.yaml` 中设 `codex_enabled: true`。这个文件会存在于工作区里，但 Git 不会跟踪和提交它
- team action 通过 `post_steps` 顺序追加 Codex/综合步骤，而不是单独的 `codex_step`
- Codex 来源: OpenAI Codex CLI (`codex mcp-server` stdio)，配置在 `~/.codex/config.toml`
- 实际模型: gpt-5.4 high（由 config.toml 配置，MCP 调用时**不传 model 参数**，设 `approval-policy: "never"`）

### 写作模式 (`writing_mode`)
| 模式 | 说明 |
|---|---|
| `sequential` | 单 agent 按章节顺序写作（默认，确保一致性） |
| `parallel` | 6 个 agent 并行写作（速度快但一致性差） |
| `codex` | 通过 Codex (gpt-5.4 high) 撰写论文 |

### 实验执行模式 (`experiment_mode`)
| 模式 | 说明 |
|---|---|
| `ssh_mcp` | 通过 SSH MCP 逐条命令交互（默认） |
| `server_codex` | 在服务器上启动 Codex CLI 本地执行 |
| `server_claude` | 在服务器上启动 Claude CLI 本地执行 |

### 模型选择
- 默认 session 模型: **Sonnet**（最佳性价比）
- Agent tier 通过 `.claude/agents/sibyl-{heavy,standard,light}.md` 声明式配置
- 纯轻量任务（交叉批评、结果辩论）自动使用 Sonnet
- Codex 任务使用 `gpt-5.4-high`

## 飞书同步（后台非阻塞）

双 MCP 架构（优先通过 `claude mcp add --scope local ...` 注册；旧环境也可能仍用 `~/.mcp.json`）：
- **lark** (官方 `@larksuiteoapi/lark-mcp`): tenant token, 用于 Bitable/IM
- **feishu** (社区 `feishu-mcp`): user OAuth, 用于文件夹/文档/原生表格

**关键规则**: 文档中的表格**必须用 `create_feishu_table` 创建原生表格**，禁止用 code block 渲染。

### 后台同步机制
- `lark_sync` **不再是流水线 stage**，改为后台非阻塞 agent
- `cli_record()` 完成 stage 后自动追加触发到 `lark_sync/pending_sync.jsonl`，返回 `sync_requested: true`
- 主 session 收到 `sync_requested` 后用 Agent tool (`run_in_background`) 启动 `sibyl-lark-sync` skill
- 锁文件 `lark_sync/sync.lock` 防止并发同步（10 分钟超时自动接管）
- 同步结果记录在 `lark_sync/sync_status.json`（含 history 审计记录）
- 失败自动写入 `logs/errors.jsonl`，接入自愈系统
- `cli_status()` 输出包含 `lark_sync_status` 字段
- 不触发同步的 stage: `init`, `quality_gate`, `done`

飞书同步 skill: `.claude/skills/sibyl-lark-sync/SKILL.md`

## Git 提交规则（强制）

**默认开发分支: `dev`**。日常开发、commit、push 都在 `dev` 分支上进行。`main` 分支仅用于稳定发布。PR 基准分支为 `dev`。

以下情况**必须立即提交 git commit 并 push 到 GitHub**：
1. 修复 bug（系统代码、编排逻辑、prompt 等）
2. 自我改进（更新记忆、优化 prompt、改进错误处理）
3. 系统逻辑代码有修改（`sibyl/` 下任何文件、`plugin/` 下的 command）
4. 新增功能或文件变更（测试、配置、文档等）

**每次 commit 后必须 `git push`**，确保 GitHub 始终是最新状态。

提交格式遵循 conventional commits：`fix:`, `feat:`, `refactor:`, `docs:`, `test:` 等。
按功能拆分提交，不要把不相关的改动混在一起。

## 自愈系统（Self-Healing）

后台常驻 agent，自动检测并修复系统运行时错误。

### 架构
- **错误收集器** (`sibyl/error_collector.py`): 结构化错误记录到 `logs/errors.jsonl`
- **错误路由器** (`sibyl/self_heal.py`): 去重、优先级排序、skill 路由、熔断器
- **修复执行器** (`sibyl-self-healer` skill): 调用对应 skill 修复 + 新增测试 + git commit

### Skill 路由表
| 错误类型 | 修复 Skill |
|---------|-----------|
| import | python-patterns → tdd-workflow |
| test | systematic-debugging → tdd-workflow |
| type | python-patterns → python-review |
| state | systematic-debugging → verification-loop |
| config | systematic-debugging |
| build | build-error-resolver → tdd-workflow |

### CLI API
- `cli_self_heal_scan(workspace_path)`: 扫描错误并生成修复任务
- `cli_self_heal_record(error_id, success, commit_hash)`: 记录修复结果
- `cli_self_heal_status(workspace_path)`: 查看自愈系统状态
- `self_heal_monitor_script(workspace_path)`: 生成后台监控脚本

### 安全机制
- **熔断器**: 同一错误 3 次修复失败 → 标记需人工干预
- **文件限制**: 单次修复最多改 5 个文件
- **受保护文件**: `orchestrate.py` 只允许最小化修改
- **测试门槛**: 修复后全量测试必须通过

### Git 策略
- Commit format: `fix(self-heal): <描述> [auto]`
- 所有修复提交到 `dev` 分支
- 阶段性通过 PR 同步到 `main`

### 配置 (`config.yaml`)
```yaml
self_heal_enabled: true        # 启用自愈（默认 true）
self_heal_interval_sec: 300    # 扫描间隔（默认 5 分钟）
self_heal_max_attempts: 3      # 熔断阈值（默认 3 次）
```
