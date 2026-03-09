---
description: "手动恢复暂停的研究项目"
argument-hint: "<project>"
---

# /sibyl-research:resume

手动恢复暂停的项目并重新进入编排循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: `$SIBYL_ROOT`

参数: `$ARGUMENTS`（项目名称）

## 步骤

1. 恢复项目：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/$ARGUMENTS')"
```

2. 获取当前状态：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('workspaces/$ARGUMENTS')"
```

2.5. **更新 Session ID 供 Sentinel 使用**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('workspaces/$ARGUMENTS', '${CLAUDE_CODE_SESSION_ID:-}')"
   ```

3. **自动启动 Ralph Loop 持续迭代**：

   首先，将迭代指令写入临时文件：
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

4. **启动 Sentinel 看门狗**（在 tmux 的 sibling pane 中）：
   ```bash
   if [ -n "${TMUX:-}" ]; then
     SIBYL_ROOT="$(cd /Users/cwan0785/sibyl-system && pwd)"
     CURRENT_PANE=$(tmux display-message -p '#{pane_id}')
     tmux split-window -h -l 60 \
       "bash $SIBYL_ROOT/sibyl/sentinel.sh workspaces/$ARGUMENTS $CURRENT_PANE 120"
     tmux select-pane -t "$CURRENT_PANE"
     echo "Sentinel 已启动（右侧 pane）"
   else
     echo "未检测到 tmux，Sentinel 未启动。建议在 tmux session 中运行。"
   fi
   ```

## 编排循环

**读取 `plugin/commands/_orchestration-loop.md` 获取完整的 CLI API 参考、进度追踪和编排循环定义，然后按其中的 LOOP 流程执行。**

将 `_orchestration-loop.md` 中所有 `WORKSPACE_PATH` 替换为实际的 workspace 路径。
