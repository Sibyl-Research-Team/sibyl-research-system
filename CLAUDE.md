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
| `agents_parallel` | 遗留：cross-critique 仍用此方式（6 个动态 prompt） |
| `bash` | 执行 shell 命令 |
| `lark_sync` | 飞书同步（已统一为 skill，实际 action_type 为 `skill`） |
| `done` / `paused` | 终止/暂停 |

### 模型选择
- 默认 session 模型: **Sonnet**（最佳性价比）
- Agent tier 通过 `.claude/agents/sibyl-{heavy,standard,light}.md` 声明式配置
- 纯轻量任务（交叉批评、结果辩论）自动使用 Sonnet

## Git 提交规则（强制）

以下情况**必须立即提交 git commit**：
1. 修复 bug（系统代码、编排逻辑、prompt 等）
2. 自我改进（更新记忆、优化 prompt、改进错误处理）
3. 系统逻辑代码有修改（`sibyl/` 下任何文件、`plugin/` 下的 command）

提交格式遵循 conventional commits：`fix:`, `feat:`, `refactor:`, `docs:` 等。
按功能拆分提交，不要把不相关的改动混在一起。
