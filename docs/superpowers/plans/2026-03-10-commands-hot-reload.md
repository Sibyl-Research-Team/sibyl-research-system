# Commands Hot Reload Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move iterable orchestration logic from non-hot-reloadable `plugin/commands/` into hot-reloadable `sibyl/prompts/` and Python orchestrator.

**Architecture:** Three changes: (1) migrate `_orchestration-loop.md` to `sibyl/prompts/`, (2) create Ralph Loop prompt template + Python helper, (3) slim down 4 command files to thin shells. All changes are additive to `orchestrate.py` and use existing `load_prompt()` infrastructure.

**Tech Stack:** Python 3.12, Claude Code skills/commands, Markdown prompt templates

---

## Task 1: Migrate orchestration loop to prompts directory

**Files:**
- Create: `sibyl/prompts/orchestration_loop.md`
- Delete: `plugin/commands/_orchestration-loop.md`

- [ ] **Step 1: Copy `_orchestration-loop.md` content to `sibyl/prompts/orchestration_loop.md`**

Copy the full content of `plugin/commands/_orchestration-loop.md` (257 lines) to `sibyl/prompts/orchestration_loop.md`. No content changes needed — the file moves as-is.

```bash
cp /Users/cwan0785/sibyl-system/plugin/commands/_orchestration-loop.md \
   /Users/cwan0785/sibyl-system/sibyl/prompts/orchestration_loop.md
```

- [ ] **Step 2: Verify `load_prompt('orchestration_loop')` works**

```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "
from sibyl.orchestrate import load_prompt
content = load_prompt('orchestration_loop')
print(f'Loaded {len(content)} chars, first line: {content.splitlines()[0][:60]}')
"
```

Expected: prints char count and first line of orchestration loop content.

- [ ] **Step 3: Replace `_orchestration-loop.md` with a pointer**

Replace `plugin/commands/_orchestration-loop.md` with a minimal redirect:

```markdown
# 编排循环（已迁移）

本文档已迁移到 `sibyl/prompts/orchestration_loop.md`，通过 `load_prompt('orchestration_loop')` 动态加载，支持热重载。

请勿在此文件中添加内容。
```

- [ ] **Step 4: Commit**

```bash
cd /Users/cwan0785/sibyl-system && git add sibyl/prompts/orchestration_loop.md plugin/commands/_orchestration-loop.md && git commit -m "$(cat <<'EOF'
refactor: migrate orchestration loop to sibyl/prompts/ for hot reload

Move the shared orchestration protocol from plugin/commands/_orchestration-loop.md
to sibyl/prompts/orchestration_loop.md so it can be loaded via load_prompt()
and benefit from hot reloading. Original file replaced with redirect pointer.
EOF
)"
```

---

## Task 2: Create Ralph Loop prompt template and Python helper

**Files:**
- Create: `sibyl/prompts/ralph_loop.md`
- Modify: `sibyl/orchestrate.py` (add `cli_write_ralph_prompt` function)

- [ ] **Step 1: Create `sibyl/prompts/ralph_loop.md` template**

Extract the duplicated prompt from `start.md:67-85` and `resume.md:38-56` into a template with placeholders:

```markdown
你是西比拉研究系统，使命是探索学术 idea、写出高质量论文。
铁律：无论遇到任何错误或异常，永不停机，持续运行。

当前项目: {project_name}，工作目录: {workspace_path}

恢复上下文:
1. 读取 {workspace_path}/breadcrumb.json 了解当前 stage 和循环状态
2. 获取编排循环定义:
   .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
3. 读取 {workspace_path}/logs/research_diary.md 了解历史

执行循环:
1. 获取下一步: .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('{workspace_path}')"
2. 根据 action_type 执行操作（见编排循环定义）
3. 记录结果: .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('{workspace_path}', 'STAGE')"
4. 重复。遇到 done 后检查质量，如需改进则继续迭代。
5. 遇到任何错误：自行诊断修复，sleep 后重试，绝不暂停。

每次新迭代要基于上一次的结果和经验教训来改进。
```

Note: the template now references `load_prompt('orchestration_loop')` instead of reading `_orchestration-loop.md` directly, so the Ralph Loop agent also gets hot-reloadable orchestration protocol.

- [ ] **Step 2: Add `cli_write_ralph_prompt()` to `orchestrate.py`**

Add this function near the end of `orchestrate.py`, after `load_common_prompt()`:

```python
def cli_write_ralph_prompt(
    workspace_path: str,
    project_name: str | None = None,
    output_path: str = "/tmp/sibyl-ralph-prompt.txt",
) -> None:
    """Load ralph_loop prompt template, inject parameters, write to file.

    Called by start.md and resume.md to generate the Ralph Loop prompt.
    """
    import json

    ws = Path(workspace_path)
    if project_name is None:
        project_name = ws.name

    template = load_prompt("ralph_loop")
    if not template:
        print(json.dumps({"error": "ralph_loop.md not found in prompts/"}))
        return

    content = template.replace("{project_name}", project_name)
    content = content.replace("{workspace_path}", str(workspace_path))

    Path(output_path).write_text(content, encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output_path": output_path,
        "project_name": project_name,
        "chars": len(content),
    }))
```

- [ ] **Step 3: Test the function**

```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "
from sibyl.orchestrate import cli_write_ralph_prompt
cli_write_ralph_prompt('workspaces/test-project', 'test-project', '/tmp/test-ralph-prompt.txt')
"
```

Expected: JSON with `status: "ok"` and char count.

```bash
head -5 /tmp/test-ralph-prompt.txt
```

Expected: first 5 lines showing "你是西比拉研究系统" with `test-project` substituted.

- [ ] **Step 4: Commit**

```bash
cd /Users/cwan0785/sibyl-system && git add sibyl/prompts/ralph_loop.md sibyl/orchestrate.py && git commit -m "$(cat <<'EOF'
feat: add ralph_loop prompt template and cli_write_ralph_prompt()

Create sibyl/prompts/ralph_loop.md with {project_name} and {workspace_path}
placeholders. Add cli_write_ralph_prompt() to orchestrate.py to load template,
inject parameters, and write to /tmp/sibyl-ralph-prompt.txt. This deduplicates
the prompt that was previously hard-coded in both start.md and resume.md.
EOF
)"
```

---

## Task 3: Slim down command files

**Files:**
- Modify: `plugin/commands/start.md`
- Modify: `plugin/commands/resume.md`
- Modify: `plugin/commands/continue.md`
- Modify: `plugin/commands/debug.md`

### Task 3a: Slim down `start.md`

- [ ] **Step 1: Replace inline Ralph Loop prompt with Python call**

In `start.md`, replace lines 64-92 (the `cat > /tmp/sibyl-ralph-prompt.txt` heredoc block + the note about replacement) with:

```markdown
3. **生成 Ralph Loop prompt 并启动持续迭代**：

   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_write_ralph_prompt; cli_write_ralph_prompt('WORKSPACE_PATH', 'PROJECT_NAME')"
   ```

   然后使用 Skill 工具调用 `ralph-loop:ralph-loop`，prompt 使用**单行 shell-safe 文本**：
   ```
   按照 /tmp/sibyl-ralph-prompt.txt 中的指令持续迭代西比拉研究项目 PROJECT_NAME，工作目录 WORKSPACE_PATH，按编排循环章节执行每轮操作
   ```
   参数: `--max-iterations 30 --completion-promise 'SIBYL_PIPELINE_COMPLETE'`

   如果 Ralph Loop 不可用（插件错误），则手动执行编排循环。
```

- [ ] **Step 2: Replace `_orchestration-loop.md` reference with `load_prompt` call**

Replace lines 115-119 (the "编排循环" section at the end) with:

```markdown
## 编排循环

**动态加载编排循环定义（支持热重载）：**
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
```

读取输出内容获取完整的 CLI API 参考、进度追踪和编排循环定义，然后按其中的 LOOP 流程执行。
将输出中所有 `WORKSPACE_PATH` 替换为实际的 workspace 路径。
```

### Task 3b: Slim down `resume.md`

- [ ] **Step 3: Replace inline Ralph Loop prompt with Python call**

In `resume.md`, replace lines 33-66 (the Ralph Loop section) with:

```markdown
3. **生成 Ralph Loop prompt 并启动持续迭代**：

   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_write_ralph_prompt; cli_write_ralph_prompt('workspaces/$ARGUMENTS', '$ARGUMENTS')"
   ```

   然后使用 Skill 工具调用 `ralph-loop:ralph-loop`，prompt 使用**单行 shell-safe 文本**：
   ```
   按照 /tmp/sibyl-ralph-prompt.txt 中的指令持续迭代西比拉研究项目 $ARGUMENTS，工作目录 workspaces/$ARGUMENTS，按编排循环章节执行每轮操作
   ```
   参数: `--max-iterations 30 --completion-promise 'SIBYL_PIPELINE_COMPLETE'`

   如果 Ralph Loop 不可用（插件错误），则手动执行编排循环。
```

- [ ] **Step 4: Replace `_orchestration-loop.md` reference**

Replace lines 82-86 (the "编排循环" section at the end) with:

```markdown
## 编排循环

**动态加载编排循环定义（支持热重载）：**
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
```

读取输出内容获取完整的 CLI API 参考、进度追踪和编排循环定义，然后按其中的 LOOP 流程执行。
将输出中所有 `WORKSPACE_PATH` 替换为实际的 workspace 路径。
```

### Task 3c: Slim down `continue.md`

- [ ] **Step 5: Replace `_orchestration-loop.md` reference in `continue.md`**

Replace lines 44-48 (steps 4-5) with:

```markdown
4. **动态加载编排循环定义（支持热重载）**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
   ```
   读取输出内容获取完整的 CLI API 参考、进度追踪和编排循环定义。

5. **进入编排循环**：
   按加载的编排循环定义中的 LOOP 流程执行，将所有 `WORKSPACE_PATH` 替换为 `workspaces/$ARGUMENTS`。

   如果 breadcrumb 显示 `in_loop == true`（中断前在轮询循环中），直接调用 `cli_next` 获取最新状态并恢复轮询，不需要重新执行已完成的阶段。
```

### Task 3d: Slim down `debug.md`

- [ ] **Step 6: Replace inline action dispatch in `debug.md`**

In `debug.md`, replace lines 88-127 (the inline action_type dispatch block in step 5) with:

```markdown
5. **执行该 action**：

   动态加载编排循环定义获取 action dispatch 规则：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
   ```

   按编排循环定义中对应 action_type 的规则执行该 action。
   如果检测到遗留 `paused_at` / 手动 stop 标记，先自动 resume，再重新获取 action。
```

### Commit all command changes

- [ ] **Step 7: Commit**

```bash
cd /Users/cwan0785/sibyl-system && git add plugin/commands/start.md plugin/commands/resume.md plugin/commands/continue.md plugin/commands/debug.md && git commit -m "$(cat <<'EOF'
refactor: slim down command files for hot reload support

Replace inline orchestration logic and duplicated Ralph Loop prompts
with dynamic load_prompt() calls and cli_write_ralph_prompt(). Commands
now delegate all iterable logic to sibyl/prompts/ (hot-reloadable).

Changes:
- start.md: use cli_write_ralph_prompt(), load_prompt('orchestration_loop')
- resume.md: use cli_write_ralph_prompt(), load_prompt('orchestration_loop')
- continue.md: use load_prompt('orchestration_loop')
- debug.md: use load_prompt('orchestration_loop')
EOF
)"
```

---

## Task 4: Final verification and push

- [ ] **Step 1: Verify all prompts load correctly**

```bash
cd /Users/cwan0785/sibyl-system && .venv/bin/python3 -c "
from sibyl.orchestrate import load_prompt, cli_write_ralph_prompt
# Test orchestration loop
orch = load_prompt('orchestration_loop')
assert len(orch) > 1000, f'orchestration_loop too short: {len(orch)}'
print(f'orchestration_loop: {len(orch)} chars OK')
# Test ralph loop
cli_write_ralph_prompt('workspaces/test', 'test', '/tmp/test-ralph.txt')
import pathlib
ralph = pathlib.Path('/tmp/test-ralph.txt').read_text()
assert 'test' in ralph, 'placeholder not substituted'
assert '{project_name}' not in ralph, 'raw placeholder remains'
print(f'ralph_loop: {len(ralph)} chars OK')
print('All checks passed')
"
```

Expected: "All checks passed"

- [ ] **Step 2: Verify no remaining references to `_orchestration-loop.md` as source of truth**

```bash
cd /Users/cwan0785/sibyl-system && grep -r "读取.*_orchestration-loop" plugin/commands/ --include="*.md" || echo "No stale references found"
```

Expected: "No stale references found"

- [ ] **Step 3: Push to remote**

```bash
cd /Users/cwan0785/sibyl-system && git push
```
