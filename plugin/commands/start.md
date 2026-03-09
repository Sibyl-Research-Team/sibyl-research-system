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
   先读取 WORKSPACE_PATH/breadcrumb.json 了解当前 stage 和循环状态。
   再读取 plugin/commands/_orchestration-loop.md 获取完整编排循环定义。
   每轮迭代步骤：
   1. 获取下一步操作: .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('WORKSPACE_PATH')"
   2. 根据 action_type 执行操作（见 _orchestration-loop.md 编排循环）
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

## 编排循环

**读取 `plugin/commands/_orchestration-loop.md` 获取完整的 CLI API 参考、进度追踪和编排循环定义，然后按其中的 LOOP 流程执行。**

将 `_orchestration-loop.md` 中所有 `WORKSPACE_PATH` 替换为实际的 workspace 路径。
