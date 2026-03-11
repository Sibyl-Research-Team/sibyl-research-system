---
description: "手动恢复已停止或遗留暂停标记的研究项目"
argument-hint: "<project_or_workspace>"
---

# /sibyl-research:resume

手动恢复已停止的项目，或清除遗留暂停标记后重新进入编排循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: `$SIBYL_ROOT`

参数: `$ARGUMENTS`（项目名称或 workspace 路径）

## 步骤

0. **规范化目标 workspace**：
```bash
TARGET_WORKSPACE="$ARGUMENTS"
if [[ "$TARGET_WORKSPACE" != */* && "$TARGET_WORKSPACE" != .* ]]; then
  TARGET_WORKSPACE="workspaces/$TARGET_WORKSPACE"
fi
PROJECT_NAME="$(basename "$TARGET_WORKSPACE")"
```

1. 恢复项目并记录恢复提示：
```bash
RESUME_JSON=$(cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('$TARGET_WORKSPACE')")
echo "$RESUME_JSON"
```

2. 获取当前状态：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('$TARGET_WORKSPACE')"
```

2.5. **更新 Session / Pane 归属供 Sentinel 使用，并先检查是否和其他项目冲突**：
   ```bash
   CURRENT_PANE=""
   if [ -n "${TMUX:-}" ]; then
     CURRENT_PANE=$(tmux display-message -p '#{pane_id}')
   fi
   SESSION_JSON=$(cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('$TARGET_WORKSPACE', '${CLAUDE_CODE_SESSION_ID:-}', '${CURRENT_PANE:-}')")
   echo "$SESSION_JSON"
   if [[ "$(echo "$SESSION_JSON" | jq -r '.ownership_conflict // false')" == "true" ]]; then
     echo "检测到当前 Claude Session 或 tmux pane 已被其他项目占用。每个项目必须使用独立的 Claude pane/session。"
     echo "$SESSION_JSON" | jq '.conflicts'
     exit 0
   fi
   ```

3. **恢复中断前的后台 hook / agent，再启动 Ralph Loop**：

   - 优先读取 `RESUME_JSON.recovery`；如果 shell 变量丢失，可重新运行 `cli_status` 并读取 `status.recovery`。
   - 如果 `RESUME_JSON` 里的 `pending_sync_count > 0`，立刻用 Agent tool 以 `run_in_background=true`
     启动 Skill `sibyl-lark-sync`，参数为 `TARGET_WORKSPACE`。不要等待完成。
   - 如果 `RESUME_JSON.background_agent_required == true`，读取
     `RESUME_JSON.resume_action.experiment_monitor.background_agent`，按其中的 `name` 和 `args`
     原样用 Agent tool 以 `run_in_background=true` 重启后台 experiment supervisor。不要等待完成。
   - 以上恢复动作只做一次；完成后继续进入 Ralph Loop。

4. **生成 Ralph Loop prompt 并启动持续迭代**：

   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_write_ralph_prompt; cli_write_ralph_prompt('$TARGET_WORKSPACE', '$PROJECT_NAME')"
   ```

   然后使用 Skill 工具调用 `ralph-loop:ralph-loop`，prompt 使用**单行 shell-safe 文本**：
   ```
   按照 $TARGET_WORKSPACE/.claude/ralph-prompt.txt 中的指令持续迭代西比拉研究项目 $PROJECT_NAME，工作目录 $TARGET_WORKSPACE，按编排循环章节执行每轮操作
   ```
   参数: `--max-iterations 30 --completion-promise 'SIBYL_PIPELINE_COMPLETE'`

   如果 Ralph Loop 不可用（插件错误），则手动执行编排循环。

5. **启动 Sentinel 看门狗**（在 tmux 的 sibling pane 中）：
   ```bash
   if [ -n "${TMUX:-}" ] && [ -n "${CURRENT_PANE:-}" ]; then
     SIBYL_ROOT="$(cd /Users/cwan0785/sibyl-system && pwd)"
     tmux split-window -h -l 60 \
       "bash $SIBYL_ROOT/sibyl/sentinel.sh $TARGET_WORKSPACE $CURRENT_PANE 120"
     tmux select-pane -t "$CURRENT_PANE"
     echo "Sentinel 已启动（右侧 pane）"
   else
     echo "未检测到 tmux，Sentinel 未启动。建议在 tmux session 中运行。"
   fi
   ```

## 编排循环

**动态渲染编排循环定义（运行时 prompt 以 Python builder 为准）：**
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import render_control_plane_prompt; print(render_control_plane_prompt('loop', workspace_path='$TARGET_WORKSPACE'))"
```

读取输出内容获取运行时 control-plane protocol，然后按其中的 LOOP 流程执行。
