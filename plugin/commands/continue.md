---
description: "恢复已有研究项目"
argument-hint: "<project_or_workspace>"
---

# /sibyl-research:continue

恢复已有项目并进入编排循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

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

1. **读取 breadcrumb 恢复上下文**：
   读取 `TARGET_WORKSPACE/breadcrumb.json`，了解中断前的状态：
   - `stage`: 当前所在阶段
   - `action_type`: 中断前正在执行的操作类型
   - `in_loop`: 是否在轮询循环中（experiment_wait / gpu_poll）
   - `loop_type`: 循环类型（用于恢复轮询）
   - `iteration`: 当前迭代编号
   - `description`: 操作描述

2. **查看项目状态**：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('$TARGET_WORKSPACE')"
```

2.5. **统一执行 `cli_resume`，既清理状态也拿到恢复提示**：
   ```bash
   RESUME_JSON=$(cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('$TARGET_WORKSPACE')")
   echo "$RESUME_JSON"
   ```
   - 这一步即使项目本来没有 stop / pause 也安全，作用是统一拿到“恢复哪些后台 hook / agent”的提示。

3. **更新 Session / Pane 归属供 Sentinel 使用，并先检查是否和其他项目冲突**：
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

4. **动态渲染编排循环定义（运行时 prompt 以 Python builder 为准）**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import render_control_plane_prompt; print(render_control_plane_prompt('loop', workspace_path='$TARGET_WORKSPACE'))"
   ```
   读取输出内容获取运行时 control-plane protocol。

5. **先恢复中断前的后台 hook / agent**：
   - 优先读取 `RESUME_JSON.recovery`；如果 shell 变量丢失，可重新运行 `cli_status` 并读取 `status.recovery`。
   - 如果 `RESUME_JSON` 里的 `pending_sync_count > 0`，立刻用 Agent tool 以 `run_in_background=true`
     启动 Skill `sibyl-lark-sync`，参数为 `TARGET_WORKSPACE`。不要等待完成。
   - 如果 `RESUME_JSON.background_agent_required == true`，读取
     `RESUME_JSON.resume_action.experiment_monitor.background_agent`，按其中的 `name` 和 `args`
     原样用 Agent tool 以 `run_in_background=true` 重启后台 experiment supervisor。不要等待完成。
   - 以上恢复动作只做一次；完成后再进入编排循环。

6. **进入编排循环**：
   按加载的编排循环定义中的 LOOP 流程执行，将所有 `WORKSPACE_PATH` 替换为 `TARGET_WORKSPACE`。

   如果 breadcrumb 显示 `in_loop == true`（中断前在轮询循环中），直接调用 `cli_next` 获取最新状态并恢复轮询，不需要重新执行已完成的阶段。
