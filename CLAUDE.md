# Sibyl System

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

依赖声明在 `requirements.txt`。如需重建环境：
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 工作目录

所有 Sibyl CLI 命令（`cli_next`, `cli_record` 等）必须在项目根目录 `/Users/cwan0785/sibyl-system` 下执行，因为 `from sibyl.xxx` 依赖包路径。

## Agent 架构（context: fork Skills）

Sibyl 的所有 agent 角色已封装为 `context: fork` skill，运行在独立 subagent context 中：

### Agent Tier 定义（`.claude/agents/`）
- `sibyl-heavy` → Opus 4.6（synthesizer, supervisor, editor, critic, reflection）
- `sibyl-standard` → Opus 4.6（literature, planner, experimenter, idea generation, writing）
- `sibyl-light` → Sonnet 4.6（optimist, skeptic, strategist, section-critic, cross-critique）

### Skills（`.claude/skills/sibyl-*/`）
编排器返回的 action 包含 `action_type: "skill"` 或 `"skills_parallel"`，主 session 通过 `/sibyl-xxx` 或 Skill tool 调用。每个 skill 通过 `!`command`` 动态加载对应的 prompt 模板。

### Action 类型
| action_type | 说明 |
|---|---|
| `skill` | 单个 fork skill 执行 |
| `skills_parallel` | 多个 fork skill 并行 |
| `team` | Agent Team 多人协作（辩论阶段），可含 `codex_step` |
| `agents_parallel` | 遗留：cross-critique 仍用此方式（6 个动态 prompt） |
| `bash` | 执行 shell 命令 |
| `gpu_poll` | GPU 轮询等待（见下方说明） |
| `done` / `paused` | 终止/暂停 |

### GPU 轮询（`gpu_poll` action）
当所有 GPU 被占用时，orchestrator 返回 `action_type: "gpu_poll"`，主 session 执行：
```
1. 用 SSH MCP (execute-command, connection=action.gpu_poll.ssh_connection)
   执行 action.gpu_poll.query_cmd
2. 调用 parse_free_gpus(output, candidate_gpu_ids, threshold_mb) 解析结果
3. 如果有空闲 GPU:
   - 写入 marker_file: {"free_gpus": [...], "poll_count": N}
   - 重新调用 cli_next() 获取实验任务
4. 如果没有空闲 GPU:
   - sleep action.gpu_poll.interval_sec 秒
   - 回到步骤 1 继续轮询（无限等待）
```

### Codex 集成
- `codex_enabled`: 启用后，idea_debate、result_debate、supervisor_review 阶段自动引入 Codex 独立审查
- team action 的 `codex_step` 字段指定 Codex 审查 skill，在 team 讨论后执行
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

## 飞书同步

双 MCP 架构（配置在 `~/.mcp.json`）：
- **lark** (官方 `@larksuiteoapi/lark-mcp`): tenant token, 用于 Bitable/IM
- **feishu** (社区 `feishu-mcp`): user OAuth, 用于文件夹/文档/原生表格

**关键规则**: 文档中的表格**必须用 `create_feishu_table` 创建原生表格**，禁止用 code block 渲染。

飞书同步 skill: `.claude/skills/sibyl-lark-sync/SKILL.md`

## Git 提交规则（强制）

以下情况**必须立即提交 git commit 并 push 到 GitHub**：
1. 修复 bug（系统代码、编排逻辑、prompt 等）
2. 自我改进（更新记忆、优化 prompt、改进错误处理）
3. 系统逻辑代码有修改（`sibyl/` 下任何文件、`plugin/` 下的 command）
4. 新增功能或文件变更（测试、配置、文档等）

**每次 commit 后必须 `git push`**，确保 GitHub 始终是最新状态。

提交格式遵循 conventional commits：`fix:`, `feat:`, `refactor:`, `docs:`, `test:` 等。
按功能拆分提交，不要把不相关的改动混在一起。
