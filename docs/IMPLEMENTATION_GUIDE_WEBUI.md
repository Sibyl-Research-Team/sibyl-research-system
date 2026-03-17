# Sibyl WebUI 实施指南 (Codex 自主执行版)

> 本文档为 OpenAI Codex 自主实施设计，包含所有必要上下文。无需额外探索代码库。

## 项目概述

Sibyl 是一个全自动学术研究系统，运行在 Claude Code CLI 中。当前纯 CLI + 文件系统架构，需要添加 Web UI 层实现三路同时交互：

1. **Chat UI** — CUI 风格对话界面，从 Claude 的对话 JSONL 文件实时读取
2. **监控仪表盘** — 系统总览、Agent 活动、GPU 利用率、成本追踪
3. **终端访问** — 通过 ttyd 暴露真实 Claude Code 终端

三路指向同一个运行中的 Claude Code 进程。

## 核心架构

```
Claude Code Process (原生交互模式, tmux 中运行)
    │
    ├── ~/.claude/projects/<cwd>/<session>.jsonl  ← 实时增量写入
    │       │
    │       └── ConversationWatcher (Python, watchfiles)
    │               └── WebSocket → 浏览器 Chat UI
    │
    ├── workspaces/<project>/status.json, events.jsonl, gpu_progress.json
    │       │
    │       └── StateWatcher (Python, watchfiles)
    │               └── WebSocket → 浏览器 Monitor Dashboard
    │
    ├── tmux pane → ttyd → 浏览器 Terminal Tab
    │
    └── ← tmux send-keys ← MessageInjector ← 浏览器 Chat 输入
```

## 环境要求

- Python 3.12, venv 在 `.venv/`（所有 Python 调用必须用 `.venv/bin/python3`）
- Node.js >= 20
- macOS (Darwin), git repo, dev 分支
- 现有依赖: flask, gunicorn, pyyaml, rich

## 现有代码库关键文件（只读参考）

### `sibyl/dashboard/server.py` — 现有 Flask 服务器

已有功能：
- Cookie 认证 (`SIBYL_DASHBOARD_KEY` env var, `_AUTH_KEY`, `check_auth()` before_request)
- `GET /api/health` — 健康检查
- `GET /api/projects` — 项目列表
- `GET /api/system/status` — 系统状态
- `GET /api/projects/<name>/dashboard` — 项目仪表盘数据（调用 `collect_dashboard_data()`）
- `GET /api/projects/<name>/files` — 目录列表
- `GET /api/projects/<name>/file` — 文件内容
- `GET /api/projects/<name>/iterations` — 迭代列表
- `GET /api/projects/<name>/outputs` — 研究产出
- 路径遍历防护 (`_safe_resolve`)
- 错误处理 (400/403/404/500 → JSON)

`create_app(config)` 返回 Flask app。我们的 `create_webui_app()` 调用它并在其上注册新 Blueprint。

### `sibyl/event_logger.py` — 事件日志

追加写入到 `logs/events.jsonl`。事件类型: `stage_start`, `stage_end`, `agent_start`, `agent_end`, `project_init`, `error`, `task_dispatch` 等。

### `sibyl/_paths.py` — 路径常量

```python
REPO_ROOT = Path(__file__).resolve().parent.parent
def get_system_state_dir() -> Path:  # 可被 SIBYL_STATE_DIR env 覆盖
```

### `sibyl/config.py` — Config dataclass

`Config` 包含 `workspaces_dir`, `compute_backend`, `gpu_*`, `lark_enabled` 等 ~50 个字段。

### `sibyl/workspace.py` — Workspace 类

`Workspace.open_existing(ws_dir, name)`, `get_status()`, `get_project_metadata()`, `read_file()`, `active_root` 等。

### 测试模式 (`tests/conftest.py`)

```python
@pytest.fixture(autouse=True)
def isolated_system_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SIBYL_STATE_DIR", str(tmp_path / "system-state"))

@pytest.fixture
def tmp_ws(tmp_path):
    ws = Workspace(tmp_path, "test-proj")
    ws.write_file("topic.txt", "test research topic")
    ws.update_stage("init")
    return ws
```

Dashboard 测试通过 `monkeypatch.setattr(srv, "_AUTH_KEY", "")` 禁用认证。

### Claude 对话文件格式

位置: `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`

每行一个 JSON 对象，**实时增量追加**。关键类型：

```json
// assistant 消息
{"type": "assistant", "uuid": "...", "sessionId": "...", "timestamp": "...",
 "message": {"role": "assistant", "content": [
   {"type": "text", "text": "..."},
   {"type": "tool_use", "id": "toolu_...", "name": "Bash", "input": {"command": "..."}}
 ], "model": "claude-opus-4-6", "usage": {"input_tokens": N, "output_tokens": N}}}

// user 消息（含 tool_result）
{"type": "user", "uuid": "...", "message": {"role": "user", "content": [
   {"type": "tool_result", "tool_use_id": "toolu_...", "content": "..."}
]}}

// 不需要显示的类型（过滤掉）
{"type": "file-history-snapshot", ...}
{"type": "progress", ...}
{"type": "queue-operation", ...}
{"type": "last-prompt", ...}
```

### Sentinel Session 文件

位置: `<workspace>/sentinel_session.json`

```json
{"claude_session_id": "sess-abc-123", "tmux_pane": "sibyl:0.0"}
```

### Pipeline 阶段常量

```python
PIPELINE_STAGES = [
    "init", "literature_search", "idea_debate", "planning",
    "pilot_experiments", "idea_validation_decision", "experiment_cycle",
    "result_debate", "experiment_decision", "writing_outline",
    "writing_sections", "writing_integrate", "writing_final_review",
    "writing_latex", "review", "reflection", "quality_gate", "done"
]
```

---

## 实施任务清单

按顺序执行。每个任务遵循 TDD：写测试 → 跑失败 → 实现 → 跑通过 → commit。

**Git 规则**: commit 到 `dev` 分支，conventional commits 格式，每个任务完成后 commit + push。

---

## Task 1: WebSocket Hub (`sibyl/webui/ws_hub.py`)

### 创建文件

**`sibyl/webui/__init__.py`**
```python
"""Sibyl Web UI package."""
```

**`tests/test_webui_ws_hub.py`**
```python
"""Tests for WebSocket connection hub."""
import pytest
from unittest.mock import MagicMock

from sibyl.webui.ws_hub import WSHub


class TestWSHub:
    def test_register_and_broadcast(self):
        hub = WSHub()
        ws = MagicMock()
        hub.register("proj-a", ws)
        assert hub.client_count("proj-a") == 1
        hub.broadcast_sync("proj-a", {"type": "test", "data": "hello"})
        ws.send.assert_called_once()

    def test_unregister(self):
        hub = WSHub()
        ws = MagicMock()
        hub.register("proj-a", ws)
        hub.unregister("proj-a", ws)
        assert hub.client_count("proj-a") == 0

    def test_broadcast_to_correct_project(self):
        hub = WSHub()
        ws_a, ws_b = MagicMock(), MagicMock()
        hub.register("proj-a", ws_a)
        hub.register("proj-b", ws_b)
        hub.broadcast_sync("proj-a", {"type": "test"})
        ws_a.send.assert_called_once()
        ws_b.send.assert_not_called()

    def test_broadcast_all(self):
        hub = WSHub()
        ws_a, ws_b = MagicMock(), MagicMock()
        hub.register("proj-a", ws_a)
        hub.register("proj-b", ws_b)
        hub.broadcast_all_sync({"type": "system"})
        ws_a.send.assert_called_once()
        ws_b.send.assert_called_once()

    def test_broadcast_skips_dead_connections(self):
        hub = WSHub()
        ws_good = MagicMock()
        ws_dead = MagicMock()
        ws_dead.send.side_effect = Exception("closed")
        hub.register("proj-a", ws_good)
        hub.register("proj-a", ws_dead)
        hub.broadcast_sync("proj-a", {"type": "test"})
        ws_good.send.assert_called_once()
        assert hub.client_count("proj-a") == 1
```

**`sibyl/webui/ws_hub.py`**
```python
"""Thread-safe WebSocket connection hub with per-project fan-out."""
import json
import logging
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


class WSHub:
    """Thread-safe WebSocket connection registry with per-project fan-out.

    flask-sock's ws.send() is synchronous, so all methods here are sync.
    Thread safety via threading.Lock for gunicorn/gevent workers.
    """

    def __init__(self):
        self._clients: dict[str, set] = defaultdict(set)
        self._lock = threading.Lock()

    def register(self, project: str, ws) -> None:
        with self._lock:
            self._clients[project].add(ws)

    def unregister(self, project: str, ws) -> None:
        with self._lock:
            self._clients[project].discard(ws)
            if not self._clients[project]:
                del self._clients[project]

    def client_count(self, project: str) -> int:
        with self._lock:
            return len(self._clients.get(project, set()))

    def broadcast_sync(self, project: str, message: dict) -> None:
        payload = json.dumps(message, ensure_ascii=False, default=str)
        with self._lock:
            clients = list(self._clients.get(project, set()))
        dead = []
        for ws in clients:
            try:
                ws.send(payload)
            except Exception:
                dead.append(ws)
        if dead:
            with self._lock:
                for ws in dead:
                    self._clients[project].discard(ws)
                    logger.debug("Removed dead WS connection for %s", project)

    def broadcast_all_sync(self, message: dict) -> None:
        with self._lock:
            projects = list(self._clients)
        for project in projects:
            self.broadcast_sync(project, message)
```

### 验证

```bash
.venv/bin/python3 -m pytest tests/test_webui_ws_hub.py -v
# 预期: 5 passed
```

### Commit

```bash
git add sibyl/webui/__init__.py sibyl/webui/ws_hub.py tests/test_webui_ws_hub.py
git commit -m "feat(webui): add WebSocket connection hub with per-project fan-out"
git push
```

---

## Task 2: Conversation Watcher (`sibyl/webui/conversation_watcher.py`)

### 创建文件

**`tests/test_webui_conversation_watcher.py`**
```python
"""Tests for Claude conversation JSONL watcher."""
import json
import pytest

from sibyl.webui.conversation_watcher import ConversationWatcher


@pytest.fixture
def jsonl_file(tmp_path):
    f = tmp_path / "session.jsonl"
    f.write_text("")
    return f


class TestConversationWatcher:
    def test_initial_read_empty(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        assert watcher.read_new_entries() == []

    def test_reads_appended_entries(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()  # initialize offset
        entry = {
            "type": "assistant", "uuid": "abc-123",
            "sessionId": "sess-1", "timestamp": "2026-03-17T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello"}],
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }
        with open(jsonl_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        entries = watcher.read_new_entries()
        assert len(entries) == 1
        assert entries[0]["type"] == "assistant"
        assert entries[0]["message"]["content"][0]["text"] == "Hello"

    def test_skips_non_displayable_types(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()
        lines = [
            json.dumps({"type": "assistant", "uuid": "1", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}}),
            json.dumps({"type": "file-history-snapshot", "uuid": "2", "snapshot": {}}),
            json.dumps({"type": "user", "uuid": "3", "message": {"role": "user", "content": [{"type": "text", "text": "bye"}]}}),
        ]
        with open(jsonl_file, "a") as f:
            f.write("\n".join(lines) + "\n")
        entries = watcher.read_new_entries()
        assert len(entries) == 2  # assistant + user, not file-history-snapshot

    def test_extracts_usage(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()
        entry = {
            "type": "assistant", "uuid": "abc",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}],
                        "usage": {"input_tokens": 500, "output_tokens": 200}},
        }
        with open(jsonl_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        entries = watcher.read_new_entries()
        assert entries[0]["message"]["usage"]["input_tokens"] == 500

    def test_handles_corrupt_lines(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()
        with open(jsonl_file, "a") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "user", "uuid": "ok", "message": {"role": "user", "content": []}}) + "\n")
        entries = watcher.read_new_entries()
        assert len(entries) == 1

    def test_tail_loads_recent(self, jsonl_file):
        entries = []
        for i in range(20):
            entries.append(json.dumps({
                "type": "assistant" if i % 2 == 0 else "user",
                "uuid": f"msg-{i}",
                "message": {"role": "assistant" if i % 2 == 0 else "user",
                             "content": [{"type": "text", "text": f"msg {i}"}]},
            }))
        jsonl_file.write_text("\n".join(entries) + "\n")
        watcher = ConversationWatcher(jsonl_file)
        recent = watcher.tail(5)
        assert len(recent) == 5
        assert recent[-1]["uuid"] == "msg-19"
```

**`sibyl/webui/conversation_watcher.py`**
```python
"""Watches Claude Code conversation JSONL files for incremental updates.

Claude Code writes one JSON line per turn to:
  ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl

This watcher maintains a file offset and reads only new lines on each poll.
Displayable types: assistant, user, system, result.
Skipped types: file-history-snapshot, progress, queue-operation, last-prompt.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DISPLAYABLE_TYPES = {"assistant", "user", "system", "result"}


class ConversationWatcher:
    """Incremental reader for Claude conversation JSONL files."""

    def __init__(self, jsonl_path: Path):
        self.path = jsonl_path
        self._offset: int = 0

    def read_new_entries(self) -> list[dict]:
        """Read and return new JSONL entries since last call."""
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                f.seek(self._offset)
                new_data = f.read()
                self._offset = f.tell()
        except OSError:
            return []
        if not new_data:
            return []
        entries = []
        for line in new_data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Skipping corrupt JSONL line")
                continue
            if obj.get("type") in _DISPLAYABLE_TYPES:
                entries.append(obj)
        return entries

    def tail(self, n: int = 50) -> list[dict]:
        """Read the last N displayable entries. Sets offset to EOF."""
        if not self.path.exists():
            return []
        entries = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") in _DISPLAYABLE_TYPES:
                        entries.append(obj)
                self._offset = f.tell()
        except OSError:
            return []
        return entries[-n:]
```

### 验证 & Commit

```bash
.venv/bin/python3 -m pytest tests/test_webui_conversation_watcher.py -v
git add sibyl/webui/conversation_watcher.py tests/test_webui_conversation_watcher.py
git commit -m "feat(webui): add conversation JSONL watcher with incremental reads"
git push
```

---

## Task 3: Session Registry (`sibyl/webui/session_registry.py`)

### 创建文件

**`tests/test_webui_session_registry.py`**
```python
"""Tests for session registry."""
import json
import pytest

from sibyl.webui.session_registry import SessionRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    claude_dir = tmp_path / ".claude"
    (claude_dir / "projects" / "-tmp-workspaces").mkdir(parents=True)
    (claude_dir / "sessions").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    return SessionRegistry(ws_dir)


class TestSessionRegistry:
    def test_discover_from_sentinel(self, registry, tmp_path):
        proj = tmp_path / "workspaces" / "proj-a"
        proj.mkdir()
        (proj / "status.json").write_text('{"stage": "planning"}')
        (proj / "sentinel_session.json").write_text(json.dumps({
            "claude_session_id": "sess-abc-123",
            "tmux_pane": "sibyl:0.0",
        }))
        info = registry.get_session("proj-a")
        assert info is not None
        assert info["session_id"] == "sess-abc-123"
        assert info["tmux_pane"] == "sibyl:0.0"

    def test_no_session(self, registry, tmp_path):
        proj = tmp_path / "workspaces" / "proj-b"
        proj.mkdir()
        (proj / "status.json").write_text('{"stage": "init"}')
        assert registry.get_session("proj-b") is None

    def test_find_conversation_jsonl(self, registry, tmp_path):
        claude_proj_dir = tmp_path / ".claude" / "projects" / "-tmp-workspaces"
        (claude_proj_dir / "sess-abc-123.jsonl").write_text('{"type":"system"}\n')
        proj = tmp_path / "workspaces" / "proj-a"
        proj.mkdir()
        (proj / "status.json").write_text('{"stage": "planning"}')
        (proj / "sentinel_session.json").write_text(json.dumps({
            "claude_session_id": "sess-abc-123",
            "tmux_pane": "sibyl:0.0",
        }))
        info = registry.get_session("proj-a")
        assert info["conversation_jsonl"] is not None
        assert info["conversation_jsonl"].endswith(".jsonl")

    def test_list_sessions(self, registry, tmp_path):
        proj = tmp_path / "workspaces" / "proj-a"
        proj.mkdir()
        (proj / "status.json").write_text('{"stage": "planning"}')
        (proj / "sentinel_session.json").write_text(json.dumps({
            "claude_session_id": "sess-1", "tmux_pane": "s:0.0",
        }))
        sessions = registry.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["project"] == "proj-a"
```

**`sibyl/webui/session_registry.py`**
```python
"""Maps Sibyl projects to their active Claude Code sessions.

Sources:
  - <workspace>/sentinel_session.json -> session_id + tmux_pane
  - ~/.claude/projects/<encoded-cwd>/<session_id>.jsonl -> conversation file
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class SessionRegistry:
    """Discovers project -> Claude session mappings."""

    def __init__(self, workspaces_dir: Path):
        self.workspaces_dir = workspaces_dir
        self._claude_home = Path(os.environ.get("HOME", "~")).expanduser() / ".claude"

    def get_session(self, project_name: str) -> dict | None:
        """Return session info for a project, or None."""
        sentinel_path = self.workspaces_dir / project_name / "sentinel_session.json"
        if not sentinel_path.exists():
            return None
        try:
            data = json.loads(sentinel_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        session_id = data.get("claude_session_id")
        if not session_id:
            return None
        result = {
            "session_id": session_id,
            "tmux_pane": data.get("tmux_pane"),
            "conversation_jsonl": None,
        }
        jsonl_path = self._find_conversation_jsonl(session_id)
        if jsonl_path:
            result["conversation_jsonl"] = str(jsonl_path)
        return result

    def _find_conversation_jsonl(self, session_id: str) -> Path | None:
        projects_dir = self._claude_home / "projects"
        if not projects_dir.exists():
            return None
        for proj_dir in projects_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            candidate = proj_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
        return None

    def list_sessions(self) -> list[dict]:
        """Return session info for all projects with active sessions."""
        sessions = []
        if not self.workspaces_dir.exists():
            return sessions
        for d in sorted(self.workspaces_dir.iterdir()):
            if not d.is_dir() or not (d / "status.json").exists():
                continue
            info = self.get_session(d.name)
            if info:
                info["project"] = d.name
                sessions.append(info)
        return sessions
```

### 验证 & Commit

```bash
.venv/bin/python3 -m pytest tests/test_webui_session_registry.py -v
git add sibyl/webui/session_registry.py tests/test_webui_session_registry.py
git commit -m "feat(webui): add session registry mapping projects to Claude sessions"
git push
```

---

## Task 4: Message Injector (`sibyl/webui/message_injector.py`)

### 创建文件

**`tests/test_webui_message_injector.py`**
```python
"""Tests for message injection via tmux."""
import pytest
from unittest.mock import patch, MagicMock

from sibyl.webui.message_injector import MessageInjector, sanitize_for_tmux


class TestSanitize:
    def test_strips_shell_metacharacters(self):
        assert sanitize_for_tmux("hello; rm -rf /") == "hello rm -rf /"

    def test_allows_slash_commands(self):
        assert sanitize_for_tmux("/sibyl-research:stop") == "/sibyl-research:stop"

    def test_allows_normal_text(self):
        assert sanitize_for_tmux("Please pivot") == "Please pivot"

    def test_strips_backticks(self):
        assert "`" not in sanitize_for_tmux("run `ls`")

    def test_strips_newlines(self):
        assert "\n" not in sanitize_for_tmux("line1\nline2")
        assert "\r" not in sanitize_for_tmux("line1\rline2")

    def test_strips_escape_chars(self):
        assert "\x1b" not in sanitize_for_tmux("test\x1b[31m")

    def test_strips_quotes(self):
        assert "'" not in sanitize_for_tmux("it's")
        assert '"' not in sanitize_for_tmux('say "hi"')

    def test_allows_chinese(self):
        msg = "请考虑 pivot 到 positional encoding"
        assert sanitize_for_tmux(msg) == msg


class TestMessageInjector:
    @patch("sibyl.webui.message_injector.subprocess")
    def test_send_to_tmux(self, mock_subprocess):
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        result = MessageInjector().send("sibyl:0.0", "hello world")
        assert result["ok"] is True
        cmd = mock_subprocess.run.call_args[0][0]
        assert cmd[0] == "tmux"
        assert "send-keys" in cmd

    @patch("sibyl.webui.message_injector.subprocess")
    def test_send_fails_gracefully(self, mock_subprocess):
        mock_subprocess.run.return_value = MagicMock(returncode=1, stderr="no pane")
        result = MessageInjector().send("bad:0.0", "hello")
        assert result["ok"] is False
        assert "error" in result

    def test_empty_after_sanitize(self):
        result = MessageInjector().send("s:0.0", "$()")
        assert result["ok"] is False
```

**`sibyl/webui/message_injector.py`**
```python
"""Sends messages to a running Claude Code session via tmux send-keys.

Security: allowlist-based sanitization — only safe characters permitted.
"""
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# Allowlist: alphanumeric, common punctuation, CJK, spaces
_ALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9 _.,:;!?/\-@#\u4e00-\u9fff\u3000-\u303f]")


def sanitize_for_tmux(message: str) -> str:
    """Allow only safe characters for tmux send-keys."""
    return _ALLOWED_CHARS.sub("", message).strip()


class MessageInjector:
    """Injects text into a Claude Code tmux session."""

    def send(self, tmux_pane: str, message: str) -> dict:
        """Send a message to a tmux pane. Returns {"ok": bool, "error"?: str}."""
        clean = sanitize_for_tmux(message)
        if not clean:
            return {"ok": False, "error": "Message empty after sanitization"}
        try:
            result = subprocess.run(
                ["tmux", "send-keys", "-t", tmux_pane, clean, "Enter"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or f"tmux exit code {result.returncode}"
                logger.warning("tmux send-keys failed for %s: %s", tmux_pane, err)
                return {"ok": False, "error": err}
            return {"ok": True}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "tmux send-keys timed out"}
        except FileNotFoundError:
            return {"ok": False, "error": "tmux not found"}
```

### 验证 & Commit

```bash
.venv/bin/python3 -m pytest tests/test_webui_message_injector.py -v
git add sibyl/webui/message_injector.py tests/test_webui_message_injector.py
git commit -m "feat(webui): add message injector with tmux send-keys + allowlist sanitization"
git push
```

---

## Task 5: State Watcher (`sibyl/webui/state_watcher.py`)

### 创建文件

**`tests/test_webui_state_watcher.py`**
```python
"""Tests for Sibyl state file watcher."""
import json
import pytest

from sibyl.webui.state_watcher import categorize_change, read_state_snapshot


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspaces" / "proj-a"
    ws.mkdir(parents=True)
    (ws / "logs").mkdir()
    (ws / "status.json").write_text(json.dumps({
        "stage": "planning", "iteration": 1,
        "paused": False, "stop_requested": False,
    }))
    (ws / "logs" / "events.jsonl").write_text("")
    return ws


class TestCategorizeChange:
    def test_status(self):
        assert categorize_change("/ws/proj/status.json") == "status_changed"

    def test_events(self):
        assert categorize_change("/ws/proj/logs/events.jsonl") == "event_logged"

    def test_gpu(self):
        assert categorize_change("/ws/proj/exp/gpu_progress.json") == "experiment_updated"

    def test_experiment(self):
        assert categorize_change("/ws/proj/exp/experiment_state.json") == "experiment_updated"

    def test_unknown(self):
        assert categorize_change("/ws/proj/other.txt") is None


class TestReadStateSnapshot:
    def test_reads_status(self, workspace):
        snap = read_state_snapshot(workspace)
        assert snap["status"]["stage"] == "planning"

    def test_handles_missing(self, tmp_path):
        ws = tmp_path / "empty"
        ws.mkdir()
        (ws / "status.json").write_text('{"stage": "init"}')
        snap = read_state_snapshot(ws)
        assert snap["status"]["stage"] == "init"
```

**`sibyl/webui/state_watcher.py`**
```python
"""Watches Sibyl workspace state files and categorizes changes.

Monitored: status.json, events.jsonl, gpu_progress.json, experiment_state.json.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FILE_CATEGORIES = {
    "status.json": "status_changed",
    "events.jsonl": "event_logged",
    "gpu_progress.json": "experiment_updated",
    "experiment_state.json": "experiment_updated",
    "sentinel_heartbeat.json": "heartbeat_updated",
}


def categorize_change(path_str: str) -> str | None:
    """Return the event category for a changed file, or None if not monitored."""
    return _FILE_CATEGORIES.get(Path(path_str).name)


def read_state_snapshot(workspace_root: Path) -> dict:
    """Read a minimal state snapshot from workspace files."""
    status = {}
    status_path = workspace_root / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    gpu_progress = {}
    gpu_path = workspace_root / "exp" / "gpu_progress.json"
    if gpu_path.exists():
        try:
            gpu_progress = json.loads(gpu_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": status, "gpu_progress": gpu_progress}
```

### 验证 & Commit

```bash
.venv/bin/python3 -m pytest tests/test_webui_state_watcher.py -v
git add sibyl/webui/state_watcher.py tests/test_webui_state_watcher.py
git commit -m "feat(webui): add state file watcher with change categorization"
git push
```

---

## Task 6: Monitor API + App Factory

### 创建文件

**`sibyl/webui/monitor_api.py`**
```python
"""Flask Blueprint for system monitoring endpoints."""
import json
import logging
from pathlib import Path

from flask import Blueprint, jsonify

from sibyl._paths import get_system_state_dir

logger = logging.getLogger(__name__)
monitor_bp = Blueprint("monitor", __name__, url_prefix="/api/monitor")


def _read_gpu_leases() -> dict:
    lease_path = get_system_state_dir() / "scheduler" / "gpu_leases.json"
    if not lease_path.exists():
        return {"leases": {}, "updated_at": None}
    try:
        return json.loads(lease_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"leases": {}, "updated_at": None}


@monitor_bp.route("/gpu")
def gpu_overview():
    return jsonify(_read_gpu_leases())


@monitor_bp.route("/agents")
def active_agents():
    """Active agents across all projects (from events.jsonl)."""
    return jsonify({"agents": []})
```

**`sibyl/webui/app.py`**
```python
"""Flask app factory for Sibyl Web UI.

Extends the existing dashboard server with new endpoints.
Auth is inherited from sibyl.dashboard.server — no duplication here.
Tests should patch sibyl.dashboard.server._AUTH_KEY, not this module.
"""
from flask import Flask

from sibyl.config import Config
from sibyl.webui.monitor_api import monitor_bp


def create_webui_app(config: Config | None = None) -> Flask:
    """Create the Sibyl Web UI Flask app."""
    if config is None:
        from sibyl.orchestration.config_helpers import load_effective_config
        config = load_effective_config()

    from sibyl.dashboard.server import create_app as create_dashboard_app
    app = create_dashboard_app(config)

    # Store ws_dir for control API
    app.config["SIBYL_WS_DIR"] = config.workspaces_dir

    # Register new blueprints
    app.register_blueprint(monitor_bp)

    return app
```

**`tests/test_webui_monitor_api.py`**
```python
"""Tests for monitor API endpoints."""
import json
import pytest

from sibyl.config import Config
from sibyl.webui.app import create_webui_app


@pytest.fixture
def workspace(tmp_path):
    ws_dir = tmp_path / "workspaces"
    proj = ws_dir / "proj-a"
    proj.mkdir(parents=True)
    (proj / "status.json").write_text(json.dumps({
        "stage": "experiment_cycle", "iteration": 1,
        "paused": False, "stop_requested": False,
        "started_at": 1000.0, "updated_at": 2000.0,
        "iteration_dirs": False, "stage_started_at": 1500.0, "errors": [],
    }))
    (proj / "topic.txt").write_text("attention sinks")
    (proj / "config.yaml").write_text("language: zh\n")
    (proj / "spec.md").write_text("# spec")
    (proj / ".git").mkdir()
    for d in ["logs", "exp", "context", "idea", "plan", "writing"]:
        (proj / d).mkdir()
    (proj / "logs" / "events.jsonl").write_text("")
    return ws_dir


@pytest.fixture
def client(workspace, monkeypatch):
    import sibyl.dashboard.server as srv
    monkeypatch.setattr(srv, "_AUTH_KEY", "")
    config = Config(workspaces_dir=workspace)
    app = create_webui_app(config)
    app.config["TESTING"] = True
    return app.test_client()


class TestGPUOverview:
    def test_empty(self, client):
        r = client.get("/api/monitor/gpu")
        assert r.status_code == 200
        assert "leases" in r.get_json()

    def test_with_leases(self, client, tmp_path, monkeypatch):
        lease_dir = tmp_path / "state" / "scheduler"
        lease_dir.mkdir(parents=True)
        (lease_dir / "gpu_leases.json").write_text(json.dumps({
            "leases": {"0": {"project_name": "proj-a", "task_ids": ["t1"]}},
            "updated_at": 1000.0,
        }))
        monkeypatch.setenv("SIBYL_STATE_DIR", str(tmp_path / "state"))
        r = client.get("/api/monitor/gpu")
        assert "0" in r.get_json()["leases"]


class TestActiveAgents:
    def test_no_agents(self, client):
        r = client.get("/api/monitor/agents")
        assert r.status_code == 200
        assert r.get_json()["agents"] == []


class TestInheritsDashboard:
    def test_health(self, client):
        assert client.get("/api/health").status_code == 200

    def test_projects(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert r.get_json()[0]["name"] == "proj-a"

    def test_dashboard(self, client):
        r = client.get("/api/projects/proj-a/dashboard")
        assert r.status_code == 200
        assert r.get_json()["status"]["stage"] == "experiment_cycle"
```

### 验证 & Commit

```bash
.venv/bin/python3 -m pytest tests/test_webui_monitor_api.py -v
git add sibyl/webui/app.py sibyl/webui/monitor_api.py tests/test_webui_monitor_api.py
git commit -m "feat(webui): add monitor API with GPU overview and app factory"
git push
```

---

## Task 7: Control API (`sibyl/webui/control_api.py`)

### 创建文件

**`sibyl/webui/control_api.py`**
```python
"""Flask Blueprint for project control endpoints."""
import json
import logging
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, abort

from sibyl.webui.message_injector import MessageInjector
from sibyl.webui.session_registry import SessionRegistry

logger = logging.getLogger(__name__)
control_bp = Blueprint("control", __name__, url_prefix="/api/projects")


def _get_ws_dir() -> Path:
    return current_app.config["SIBYL_WS_DIR"]


def _get_project_dir(project_name: str) -> Path:
    ws_dir = _get_ws_dir()
    proj = (ws_dir / project_name).resolve()
    if not proj.is_relative_to(ws_dir.resolve()):
        abort(403, description="Path traversal")
    if not proj.is_dir() or not (proj / "status.json").exists():
        abort(404, description=f"Project not found: {project_name}")
    return proj


@control_bp.route("/<project_name>/send-message", methods=["POST"])
def send_message(project_name: str):
    _get_project_dir(project_name)  # validate exists
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify(error="Missing 'text' field"), 400

    registry = SessionRegistry(_get_ws_dir())
    session = registry.get_session(project_name)
    if not session or not session.get("tmux_pane"):
        return jsonify(error="No active Claude session"), 409

    result = MessageInjector().send(session["tmux_pane"], text)
    return jsonify(result), 200 if result["ok"] else 502


@control_bp.route("/<project_name>/stop", methods=["POST"])
def stop_project(project_name: str):
    proj = _get_project_dir(project_name)
    (proj / "sentinel_stop.json").write_text(
        json.dumps({"stop": True, "timestamp": time.time()}), encoding="utf-8",
    )
    registry = SessionRegistry(_get_ws_dir())
    session = registry.get_session(project_name)
    if session and session.get("tmux_pane"):
        MessageInjector().send(session["tmux_pane"], "/sibyl-research:stop")
    return jsonify(ok=True, message=f"Stop signal sent to {project_name}")


@control_bp.route("/<project_name>/resume", methods=["POST"])
def resume_project(project_name: str):
    proj = _get_project_dir(project_name)
    stop_file = proj / "sentinel_stop.json"
    if stop_file.exists():
        stop_file.unlink()
    registry = SessionRegistry(_get_ws_dir())
    session = registry.get_session(project_name)
    if session and session.get("tmux_pane"):
        MessageInjector().send(session["tmux_pane"], "/sibyl-research:resume")
        return jsonify(ok=True, message="Resume signal sent")
    return jsonify(ok=True, message="Stop signal cleared (no active session)")
```

### 修改文件

**`sibyl/webui/app.py`** — 添加 control_bp 注册:

在 `from sibyl.webui.monitor_api import monitor_bp` 下方添加:
```python
from sibyl.webui.control_api import control_bp
```

在 `app.register_blueprint(monitor_bp)` 下方添加:
```python
    app.register_blueprint(control_bp)
```

**`tests/test_webui_control_api.py`**
```python
"""Tests for control API endpoints."""
import json
import pytest
from unittest.mock import patch, MagicMock

from sibyl.config import Config
from sibyl.webui.app import create_webui_app


@pytest.fixture
def workspace(tmp_path):
    ws_dir = tmp_path / "workspaces"
    proj = ws_dir / "proj-a"
    proj.mkdir(parents=True)
    (proj / "status.json").write_text(json.dumps({
        "stage": "planning", "iteration": 1,
        "paused": False, "stop_requested": False,
        "started_at": 1000.0, "updated_at": 2000.0,
        "iteration_dirs": False, "stage_started_at": 1500.0, "errors": [],
    }))
    (proj / "topic.txt").write_text("test topic")
    (proj / "config.yaml").write_text("language: zh\n")
    (proj / "spec.md").write_text("# spec")
    (proj / ".git").mkdir()
    (proj / "sentinel_session.json").write_text(json.dumps({
        "claude_session_id": "sess-123", "tmux_pane": "sibyl:0.0",
    }))
    for d in ["logs", "context", "idea", "plan", "exp", "writing"]:
        (proj / d).mkdir()
    (proj / "logs" / "events.jsonl").write_text("")
    return ws_dir


@pytest.fixture
def client(workspace, monkeypatch):
    import sibyl.dashboard.server as srv
    monkeypatch.setattr(srv, "_AUTH_KEY", "")
    config = Config(workspaces_dir=workspace)
    app = create_webui_app(config)
    app.config["TESTING"] = True
    return app.test_client()


class TestSendMessage:
    @patch("sibyl.webui.control_api.MessageInjector")
    def test_success(self, MockInjector, client):
        MockInjector.return_value.send.return_value = {"ok": True}
        r = client.post("/api/projects/proj-a/send-message", json={"text": "pivot"})
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_no_session(self, client, workspace):
        (workspace / "proj-a" / "sentinel_session.json").unlink()
        r = client.post("/api/projects/proj-a/send-message", json={"text": "hi"})
        assert r.status_code == 409

    def test_missing_text(self, client):
        r = client.post("/api/projects/proj-a/send-message", json={})
        assert r.status_code == 400


class TestStop:
    def test_writes_stop_file(self, client, workspace):
        r = client.post("/api/projects/proj-a/stop")
        assert r.status_code == 200
        assert (workspace / "proj-a" / "sentinel_stop.json").exists()

    def test_404(self, client):
        assert client.post("/api/projects/nonexistent/stop").status_code == 404


class TestResume:
    def test_removes_stop_file(self, client, workspace):
        (workspace / "proj-a" / "sentinel_stop.json").write_text('{"stop":true}')
        r = client.post("/api/projects/proj-a/resume")
        assert r.status_code == 200
        assert not (workspace / "proj-a" / "sentinel_stop.json").exists()

    def test_404(self, client):
        assert client.post("/api/projects/nonexistent/resume").status_code == 404
```

### 验证 & Commit

```bash
.venv/bin/python3 -m pytest tests/test_webui_control_api.py -v
git add sibyl/webui/control_api.py sibyl/webui/app.py tests/test_webui_control_api.py
git commit -m "feat(webui): add control API with send-message, stop, resume"
git push
```

---

## Task 8: 添加依赖 + CLI 入口

### 修改 `pyproject.toml`

在 `dependencies` 列表中添加:
```
    "flask-sock>=0.7",
    "watchfiles>=0.21",
```

### 安装

```bash
.venv/bin/pip install -e .
```

### 修改 `sibyl/cli.py`

在 `dashboard_p = sub.add_parser(...)` 之后添加:
```python
    webui_p = sub.add_parser("webui", help="Web UI with chat + monitoring + terminal")
    webui_p.add_argument("--port", type=int, default=7654, help="Server port")
    webui_p.add_argument("--host", default="127.0.0.1", help="Server host")
    webui_p.add_argument("--config", help="Config YAML path")
```

在 `if args.command == "dashboard":` 块之前添加:
```python
    if args.command == "webui":
        from sibyl.webui.app import create_webui_app
        from sibyl.orchestration.config_helpers import load_effective_config
        cfg = load_effective_config(config_path=getattr(args, "config", None))
        app = create_webui_app(cfg)
        ws_dir = cfg.workspaces_dir.resolve()
        print(f"\n  Sibyl WebUI running at http://{args.host}:{args.port}")
        print(f"  Serving workspaces from: {ws_dir}")
        print("  Press Ctrl+C to stop.\n")
        app.run(host=args.host, port=args.port, debug=False)
        return
```

### 验证

```bash
.venv/bin/python3 -m pytest tests/test_webui_monitor_api.py tests/test_webui_control_api.py -v
.venv/bin/python3 -m sibyl.cli webui --help  # 应显示 --port --host --config 选项
```

### Commit

```bash
git add pyproject.toml sibyl/cli.py
git commit -m "feat(webui): add flask-sock, watchfiles deps and CLI entry point"
git push
```

---

## Task 9: ttyd 部署脚本

### 创建 `deploy/ttyd-manager.sh`

```bash
#!/usr/bin/env bash
# Manages ttyd instances for Sibyl project terminal access.
set -euo pipefail

PORT_BASE=7681

case "${1:-}" in
  start)
    PROJECT="${2:?project_name required}"
    TMUX_TARGET="${3:-sibyl}"
    PORT=$PORT_BASE
    while lsof -i ":$PORT" &>/dev/null && [ $PORT -lt 7699 ]; do
      PORT=$((PORT + 1))
    done
    if [ $PORT -ge 7699 ]; then
      echo "ERROR: No free ports in range $PORT_BASE-7699" >&2; exit 1
    fi
    ttyd --port "$PORT" --interface 127.0.0.1 --writable \
         tmux attach-session -t "$TMUX_TARGET" &
    PID=$!
    echo "$PID" > "/tmp/sibyl_ttyd_${PROJECT}.pid"
    echo "{\"project\": \"$PROJECT\", \"port\": $PORT, \"pid\": $PID}"
    ;;
  stop)
    PROJECT="${2:?project_name required}"
    PID_FILE="/tmp/sibyl_ttyd_${PROJECT}.pid"
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Stopped ttyd for $PROJECT"
    else
      echo "No ttyd PID file for $PROJECT"
    fi
    ;;
  status)
    pgrep -af ttyd || echo "No ttyd processes running"
    ;;
  *) echo "Usage: $0 start|stop|status [project] [tmux_target]"; exit 1 ;;
esac
```

### 创建 `deploy/nginx.conf`

```nginx
upstream sibyl_backend { server 127.0.0.1:7654; }
upstream sibyl_terminal { server 127.0.0.1:7681; }

server {
    listen 80;
    server_name _;

    location /api/ {
        proxy_pass http://sibyl_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
    }

    location /ws/ {
        proxy_pass http://sibyl_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    location /terminal/ {
        proxy_pass http://sibyl_terminal/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    location / {
        proxy_pass http://sibyl_backend;
    }
}
```

### Commit

```bash
chmod +x deploy/ttyd-manager.sh
git add deploy/ttyd-manager.sh deploy/nginx.conf
git commit -m "feat(deploy): add ttyd manager and nginx config"
git push
```

---

## Task 10-15: 前端实现

> 以下任务描述前端实现。由于前端代码量大且组件间耦合低，以下提供架构规格而非逐行代码。

### Task 10: Next.js 脚手架

```bash
cd /path/to/sibyl-system
npx create-next-app@latest webui --typescript --tailwind --eslint --app --src-dir --no-import-alias --use-npm
cd webui
npm install zustand recharts @radix-ui/react-collapsible @radix-ui/react-tabs @radix-ui/react-dialog lucide-react react-markdown react-diff-viewer-continued prism-react-renderer @xterm/xterm @xterm/addon-fit
```

**`webui/next.config.ts`**:
```typescript
import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
  output: 'export',
  async rewrites() {
    return [
      { source: '/api/:path*', destination: 'http://localhost:7654/api/:path*' },
    ];
  },
};
export default nextConfig;
```

**`webui/.env.development`**:
```
NEXT_PUBLIC_WS_URL=ws://localhost:7654
```

**`webui/src/lib/api.ts`** — REST 客户端，封装所有 `/api/` 端点调用。

**`webui/src/stores/system.ts`** — Zustand store: projects[], setProjects()

**`webui/src/stores/project.ts`** — Zustand store: per-project dashboard + messages[]

### Task 11: Chat 组件

**核心文件**:
- `src/lib/parse-message.ts` — 解析 Claude JSONL 条目为 `ChatMessage` 类型
- `src/components/chat/MessageItem.tsx` — 渲染单条消息
- `src/components/chat/ToolBlock.tsx` — 渲染 tool_use 区块
- `src/components/chat/MessageList.tsx` — 可滚动消息容器
- `src/components/chat/MessageInput.tsx` — 用户输入框 + 发送/停止按钮
- `src/hooks/useConversationStream.ts` — WebSocket 连接管理

**ChatMessage 类型**:
```typescript
type ContentBlock =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; id: string; name: string; input: Record<string, any> }
  | { type: 'tool_result'; tool_use_id: string; content: string; is_error?: boolean }
  | { type: 'thinking'; text: string };

interface ChatMessage {
  id: string;          // uuid from JSONL
  role: 'user' | 'assistant' | 'system';
  blocks: ContentBlock[];
  model?: string;
  usage?: { input_tokens: number; output_tokens: number };
  timestamp?: string;
}
```

**ToolBlock 渲染规则**:
| tool name | 图标 (lucide) | 显示 |
|-----------|-------------|------|
| Bash | Terminal | 命令 + 折叠输出 (暗色代码块) |
| Read | FileText | 路径 + 折叠内容 (行号 + 高亮) |
| Edit | Pencil | 路径 + diff 视图 (react-diff-viewer) |
| Write | FilePlus | 路径 + 折叠内容 |
| Grep/Glob | Search | 搜索模式 + 折叠结果 |
| Skill | Zap | skill 名称 |
| Agent | Users | agent 类型 + 折叠子消息 |
| 其他 | Code | JSON 展示 |

**WebSocket hook** (`useConversationStream`):
```typescript
const wsUrl = process.env.NEXT_PUBLIC_WS_URL || '';
// 连接: `${wsUrl}/ws/conversation/${projectName}`
// 接收消息: 追加到 Zustand store messages[]
// 重连: 指数退避 (500ms → 1s → 2s → 4s, cap 30s)
// 挂载时: GET /api/projects/${name}/conversation → 初始消息列表
```

### Task 12: 监控组件

- `SystemOverview.tsx` — 活跃项目数, GPU 使用率 (from /api/monitor/gpu), 总 Agent 数
- `PipelineProgress.tsx` — 18 个 PIPELINE_STAGES 水平时间轴, 当前阶段高亮
- `ExperimentGrid.tsx` — GPU 卡片网格 (GPU index, project, task, status, elapsed)
- `AgentActivity.tsx` — Agent 活动时间线 (from events.jsonl agent_start/agent_end)
- `CostChart.tsx` — Recharts 折线图: token 使用量按时间

### Task 13: 项目视图

- `src/app/projects/[name]/page.tsx` — Radix Tabs: Chat | Monitor | Files | Config
- `FileBrowser.tsx` — 基于 `react-arborist` 的树形文件浏览器，支持目录懒加载、面包屑定位、文本预览与 PDF 内嵌预览，右侧 Preview 面板固定高度并在内部滚动 (GET /api/projects/{name}/files, GET /api/projects/{name}/file)
- `ConfigEditor.tsx` — config.yaml 编辑器 (textarea + 保存按钮)
- `useProjectState.ts` — WebSocket hook for `/ws/state/${project}`

### Task 14: WebSocket 服务端路由

在 `sibyl/webui/app.py` 中添加 flask-sock WebSocket 路由:

```python
from flask_sock import Sock

sock = Sock(app)

@sock.route("/ws/conversation/<project>")
def ws_conversation(ws, project):
    """Stream conversation JSONL updates to connected clients."""
    hub.register(project, ws)
    try:
        while True:
            ws.receive(timeout=30)  # keep alive
    except Exception:
        pass
    finally:
        hub.unregister(project, ws)

@sock.route("/ws/state/<project>")
def ws_state(ws, project):
    """Stream Sibyl state updates."""
    hub.register(f"state:{project}", ws)
    try:
        while True:
            ws.receive(timeout=30)
    except Exception:
        pass
    finally:
        hub.unregister(f"state:{project}", ws)
```

启动后台 watcher 线程:
```python
import threading
from watchfiles import watch

def _start_watcher(app, hub, ws_dir):
    def _watch_loop():
        for changes in watch(str(ws_dir)):
            for change_type, path in changes:
                category = categorize_change(path)
                if category:
                    project = Path(path).relative_to(ws_dir).parts[0]
                    snapshot = read_state_snapshot(ws_dir / project)
                    hub.broadcast_sync(f"state:{project}",
                        {"type": category, "data": snapshot})
    t = threading.Thread(target=_watch_loop, daemon=True)
    t.start()
```

### Task 15: 部署

**`deploy/sibyl-webui.service`**:
```ini
[Unit]
Description=Sibyl WebUI Server
After=network.target

[Service]
Type=simple
User=cwan0785
WorkingDirectory=/Users/cwan0785/sibyl-system
ExecStart=/Users/cwan0785/sibyl-system/.venv/bin/python3 -m sibyl.cli webui --port 7654
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 全量测试

```bash
cd /path/to/sibyl-system
.venv/bin/python3 -m pytest tests/test_webui_*.py -v
```

预期: 所有后端测试通过。前端需手动验证:
1. 推荐直接执行 `./scripts/dev-webui.sh`
2. 浏览器访问 `http://127.0.0.1:3000`
3. Chat Tab: 消息实时流入
4. Monitor Tab: Pipeline 进度显示
5. Terminal: `deploy/ttyd-manager.sh start proj sibyl` → iframe 可用
6. 如果后端启用了 `SIBYL_DASHBOARD_KEY`，首页应先显示解锁页，而不是空白项目列表
7. 右上角语言切换应可在 `EN / 中文` 间实时切换

## 开发启动

推荐使用仓库根目录下的一键脚本:

```bash
./scripts/dev-webui.sh
```

它会同时启动:

- Flask WebUI API: `http://127.0.0.1:7654`
- Next.js 前端: `http://127.0.0.1:3000`

按 `Ctrl+C` 会同时停止两边。脚本默认会对后端进程执行 `env -u SIBYL_DASHBOARD_KEY`，避免本地开发时因为 dashboard 鉴权导致前端 API 请求返回 `401`。

如果你需要保留鉴权环境变量:

```bash
./scripts/dev-webui.sh --with-auth
```

这时 WebUI 会先进入登录门页。输入 `SIBYL_DASHBOARD_KEY` 后端实际值后，才会继续加载项目列表和项目页。

手动启动方式仍然可用:

```bash
cd /path/to/sibyl-system
env -u SIBYL_DASHBOARD_KEY .venv/bin/python3 -m sibyl.cli webui --host 127.0.0.1 --port 7654

cd /path/to/sibyl-system/webui
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## 当前前端行为说明

- 首页和登录门页都带有 `EN / 中文` 语言切换，选择会保存在浏览器本地存储中。
- 如果 `SIBYL_DASHBOARD_KEY` 已开启，前端会优先调用 `/api/auth/check`，未登录时显示解锁页，避免用户把 `401` 误判为“没有项目”。
- 首页会显示当前后端扫描的 `workspaces_dir`。
- 只有包含 `status.json` 的目录会被识别为项目并显示在列表里；普通目录不会出现在项目卡片中。

## 设计约束提醒

1. **所有 Python 调用必须用 `.venv/bin/python3`**
2. **Git commit 到 `dev` 分支**, conventional commits 格式
3. **不修改现有 `sibyl/dashboard/server.py`** — 只通过 `create_webui_app()` 继承和扩展
4. **Auth 使用 `sibyl.dashboard.server` 的机制** — 不在 webui 模块中重复
5. **tmux 消息注入使用 allowlist 安全过滤** — 只允许安全字符
6. **WSHub 必须线程安全** — 使用 `threading.Lock`
7. **前端 WebSocket 在开发模式下直连 Flask** — 使用 `NEXT_PUBLIC_WS_URL`
