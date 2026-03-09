# Background Feishu Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert Feishu sync from a blocking pipeline stage to a non-blocking background agent, with lock-based mutual exclusion, append-only audit trail, and self-heal integration.

**Architecture:** Remove `lark_sync` as a pipeline stage entirely. Instead, `cli_record()` appends a sync trigger to `pending_sync.jsonl` and returns `sync_requested: true`. The main session launches `sibyl-lark-sync` as a background agent. Lock file prevents concurrent syncs; late arrivals wait then merge.

**Tech Stack:** Python 3.12, Claude Code Agent tool (`run_in_background`), JSONL append-only logs, file-based locking.

---

### Task 1: Write tests for pending_sync signal in cli_record

**Files:**
- Modify: `tests/test_orchestrate.py`

**Step 1: Write failing tests**

Add a new test class `TestBackgroundSync` in `tests/test_orchestrate.py` after the existing `TestRecordResult` class:

```python
class TestBackgroundSync:
    """Tests for background Feishu sync trigger in cli_record."""

    def test_cli_record_appends_pending_sync_when_lark_enabled(self, make_orchestrator):
        """cli_record should append a line to pending_sync.jsonl when lark_enabled."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.record_result("literature_search")
        pending_path = Path(o.ws.root) / o.ws.name / "lark_sync" / "pending_sync.jsonl"
        assert pending_path.exists()
        lines = pending_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["trigger_stage"] == "literature_search"
        assert "timestamp" in entry
        assert "iteration" in entry

    def test_cli_record_no_pending_sync_when_lark_disabled(self, make_orchestrator):
        """No pending_sync.jsonl written when lark_enabled=False."""
        o = make_orchestrator(stage="literature_search", lark_enabled=False)
        o.record_result("literature_search")
        pending_path = Path(o.ws.root) / o.ws.name / "lark_sync" / "pending_sync.jsonl"
        assert not pending_path.exists()

    def test_cli_record_appends_multiple_syncs(self, make_orchestrator):
        """Multiple stage completions append multiple lines."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        o.record_result("literature_search")
        o.record_result("idea_debate")
        pending_path = Path(o.ws.root) / o.ws.name / "lark_sync" / "pending_sync.jsonl"
        lines = pending_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["trigger_stage"] == "literature_search"
        assert json.loads(lines[1])["trigger_stage"] == "idea_debate"

    def test_cli_record_returns_sync_requested(self, make_orchestrator, capsys):
        """cli_record output includes sync_requested when lark_enabled."""
        o = make_orchestrator(stage="literature_search", lark_enabled=True)
        # Use cli_record to check printed output
        from sibyl.orchestrate import cli_record
        cli_record(str(Path(o.ws.root) / o.ws.name), "literature_search")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["sync_requested"] is True

    def test_cli_record_no_sync_requested_when_disabled(self, make_orchestrator, capsys):
        """cli_record output has no sync_requested when lark disabled."""
        o = make_orchestrator(stage="literature_search", lark_enabled=False)
        from sibyl.orchestrate import cli_record
        cli_record(str(Path(o.ws.root) / o.ws.name), "literature_search")
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output.get("sync_requested", False) is False

    def test_no_pending_sync_for_init_stage(self, make_orchestrator):
        """init stage should not trigger sync."""
        o = make_orchestrator(stage="init", lark_enabled=True)
        # init auto-advances, but shouldn't write sync trigger
        pending_path = Path(o.ws.root) / o.ws.name / "lark_sync" / "pending_sync.jsonl"
        assert not pending_path.exists()

    def test_no_pending_sync_for_quality_gate(self, make_orchestrator):
        """quality_gate should not trigger sync."""
        o = make_orchestrator(stage="quality_gate", lark_enabled=True, iteration=1)
        # quality_gate needs a score to proceed
        o.ws.write_file("logs/stage_review_score.txt", "9.0")
        o.record_result("quality_gate", score=9.0)
        pending_path = Path(o.ws.root) / o.ws.name / "lark_sync" / "pending_sync.jsonl"
        assert not pending_path.exists()
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_orchestrate.py::TestBackgroundSync -v`
Expected: FAIL — `pending_sync.jsonl` not created, `sync_requested` not in output.

**Step 3: Commit failing tests**

```bash
git add tests/test_orchestrate.py
git commit -m "test: add failing tests for background Feishu sync trigger"
```

---

### Task 2: Remove lark_sync stage from pipeline

**Files:**
- Modify: `sibyl/orchestrate.py:269-288` (STAGES list)
- Modify: `sibyl/orchestrate.py:464-538` (`_compute_action`, remove lark_sync branch)
- Modify: `sibyl/orchestrate.py:1319-1331` (delete `_action_lark_sync`)
- Modify: `sibyl/orchestrate.py:1551-1594` (`_get_next_stage`, remove interleaving logic)
- Modify: `sibyl/orchestrate.py:414-456` (`record_result`, remove lark_sync idempotent handling)

**Step 1: Remove `"lark_sync"` from STAGES list**

In `sibyl/orchestrate.py` line 285, delete the `"lark_sync",` line.

**Step 2: Remove `_action_lark_sync` method**

Delete lines 1319-1331 (the entire `_action_lark_sync` method).

**Step 3: Remove lark_sync branch in `_compute_action`**

Delete lines 528-529:
```python
elif stage == "lark_sync":
    return self._action_lark_sync(ws)
```

**Step 4: Simplify `_get_next_stage`**

Replace the entire method body (lines 1551-1594) with:
```python
def _get_next_stage(self, current_stage: str, result: str = "",
                    score: float | None = None) -> tuple[str, int | None]:
    """Determine the next stage based on current stage and result.

    Returns (next_stage, new_iteration). new_iteration is non-None only
    when the quality gate loops back for a new iteration.
    """
    return self._natural_next_stage(current_stage, result, score)
```

**Step 5: Remove lark_sync idempotent handling in `record_result`**

Delete lines 426-428 in `record_result`:
```python
# Tolerate duplicate lark_sync after it was auto-advanced earlier.
if stage == "lark_sync":
    return
```

**Step 6: Run existing tests**

Run: `.venv/bin/python3 -m pytest tests/test_orchestrate.py -v`
Expected: The old `lark_sync` tests will fail (they reference removed functionality). That's expected — we'll fix them in Task 3.

**Step 7: Commit**

```bash
git add sibyl/orchestrate.py
git commit -m "refactor: remove lark_sync as blocking pipeline stage"
```

---

### Task 3: Update old lark_sync tests to match new behavior

**Files:**
- Modify: `tests/test_orchestrate.py:64-133` (replace old lark_sync tests)

**Step 1: Replace old lark_sync tests**

Delete the following test methods (lines 64-133):
- `test_reflection_to_lark_sync_when_enabled`
- `test_reflection_skips_lark_when_disabled`
- `test_per_stage_lark_sync_interleaving`
- `test_lark_sync_not_interleaved_for_experiment_loop`
- `test_lark_sync_after_all_experiments_done`
- `test_reflection_natural_next_is_lark_sync_no_double`
- `test_lark_sync_description_shows_resume_target`
- `test_duplicate_lark_sync_is_idempotent_noop` (line 158-161)

Replace with direct-transition tests:
```python
def test_reflection_goes_to_quality_gate(self, make_orchestrator):
    """Without lark_sync stage, reflection goes directly to quality_gate."""
    o = make_orchestrator(stage="reflection", lark_enabled=True)
    o.record_result("reflection")
    assert o.ws.get_status().stage == "quality_gate"

def test_reflection_to_quality_gate_lark_disabled(self, make_orchestrator):
    o = make_orchestrator(stage="reflection", lark_enabled=False)
    o.record_result("reflection")
    assert o.ws.get_status().stage == "quality_gate"

def test_stages_advance_directly_without_lark_sync(self, make_orchestrator):
    """Stages advance directly without interleaved lark_sync."""
    o = make_orchestrator(stage="literature_search", lark_enabled=True)
    o.record_result("literature_search")
    assert o.ws.get_status().stage == "idea_debate"
```

**Step 2: Also remove `resume_after_sync` references from status JSON fixtures**

Search for `"resume_after_sync"` in test files and remove those fields from any fixture JSON (lines ~857, ~877 in test_orchestrate.py).

**Step 3: Run all tests**

Run: `.venv/bin/python3 -m pytest tests/test_orchestrate.py -v`
Expected: All old tests updated, new `TestBackgroundSync` tests still fail (implementation not yet done).

**Step 4: Commit**

```bash
git add tests/test_orchestrate.py
git commit -m "test: update lark_sync tests for background sync architecture"
```

---

### Task 4: Remove resume_after_sync from workspace

**Files:**
- Modify: `sibyl/workspace.py:19` (remove field from dataclass)
- Modify: `sibyl/workspace.py:228-232` (delete `set_resume_after_sync` method)

**Step 1: Remove `resume_after_sync` field from WorkspaceStatus**

In `sibyl/workspace.py` line 19, delete:
```python
resume_after_sync: str = ""  # stage to resume after mid-pipeline lark_sync
```

**Step 2: Delete `set_resume_after_sync` method**

Delete lines 228-232 (the entire `set_resume_after_sync` method).

**Step 3: Run tests**

Run: `.venv/bin/python3 -m pytest tests/ -x -q`
Expected: Any remaining references to `resume_after_sync` will fail. Fix any stragglers.

**Step 4: Commit**

```bash
git add sibyl/workspace.py
git commit -m "refactor: remove resume_after_sync from WorkspaceStatus"
```

---

### Task 5: Implement pending_sync signal in record_result and cli_record

**Files:**
- Modify: `sibyl/orchestrate.py:414-456` (`record_result` — add pending_sync append)
- Modify: `sibyl/orchestrate.py:1851-1856` (`cli_record` — add sync_requested to output)

**Step 1: Add pending_sync append to `record_result`**

After the git commit line (line 456), add:
```python
# Trigger background Feishu sync if enabled
_NO_SYNC_TRIGGER = {"init", "quality_gate", "done", "lark_sync"}
if (self.config.lark_enabled
        and stage not in _NO_SYNC_TRIGGER):
    self._append_pending_sync(stage)
```

**Step 2: Add `_append_pending_sync` helper method**

Add near other private methods (after `_action_lark_sync` was removed):
```python
def _append_pending_sync(self, stage: str):
    """Append a sync trigger to lark_sync/pending_sync.jsonl."""
    import datetime
    entry = {
        "trigger_stage": stage,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "iteration": self.ws.get_status().iteration,
    }
    sync_dir = Path(self.ws.root) / self.ws.name / "lark_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    with open(sync_dir / "pending_sync.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
```

**Step 3: Update `cli_record` to return `sync_requested`**

Replace `cli_record` (lines 1851-1856) with:
```python
def cli_record(workspace_path: str, stage: str, result: str = "",
               score: float | None = None):
    """CLI: Record stage result."""
    o = FarsOrchestrator(workspace_path)
    o.record_result(stage, result, score)
    status = o.ws.get_status()
    output = {"status": "ok", "new_stage": status.stage}
    # Signal main session to launch background sync agent
    _NO_SYNC_TRIGGER = {"init", "quality_gate", "done", "lark_sync"}
    if o.config.lark_enabled and stage not in _NO_SYNC_TRIGGER:
        output["sync_requested"] = True
    print(json.dumps(output))
```

**Step 4: Run TestBackgroundSync tests**

Run: `.venv/bin/python3 -m pytest tests/test_orchestrate.py::TestBackgroundSync -v`
Expected: PASS for all pending_sync tests.

**Step 5: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -x -q`
Expected: All tests pass.

**Step 6: Commit**

```bash
git add sibyl/orchestrate.py
git commit -m "feat: add background sync trigger in cli_record with pending_sync.jsonl"
```

---

### Task 6: Add sync status to cli_status

**Files:**
- Modify: `sibyl/orchestrate.py:1873-1876` (`cli_status`)
- Modify: `tests/test_orchestrate.py` (add test)

**Step 1: Write failing test**

Add to `TestBackgroundSync`:
```python
def test_cli_status_includes_sync_status(self, make_orchestrator, tmp_path, capsys):
    """cli_status should include lark sync status when sync_status.json exists."""
    o = make_orchestrator(stage="idea_debate", lark_enabled=True)
    ws_path = Path(o.ws.root) / o.ws.name
    sync_dir = ws_path / "lark_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    status_data = {
        "last_sync_at": "2026-03-09T12:00:00Z",
        "last_sync_success": True,
        "last_synced_line": 1,
        "last_trigger_stage": "literature_search",
        "history": [],
    }
    (sync_dir / "sync_status.json").write_text(json.dumps(status_data))
    from sibyl.orchestrate import cli_status
    cli_status(str(ws_path))
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["lark_sync_status"]["last_sync_success"] is True

def test_cli_status_no_sync_status_when_missing(self, make_orchestrator, capsys):
    """cli_status should not include lark_sync_status when no sync_status.json."""
    o = make_orchestrator(stage="idea_debate", lark_enabled=False)
    ws_path = Path(o.ws.root) / o.ws.name
    from sibyl.orchestrate import cli_status
    cli_status(str(ws_path))
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "lark_sync_status" not in output
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_orchestrate.py::TestBackgroundSync::test_cli_status_includes_sync_status -v`
Expected: FAIL — `lark_sync_status` not in output.

**Step 3: Implement cli_status enhancement**

Replace `cli_status` with:
```python
def cli_status(workspace_path: str):
    """CLI: Get project status."""
    o = FarsOrchestrator(workspace_path)
    status = o.get_status()
    # Include Feishu sync status if available
    sync_status_path = Path(workspace_path) / "lark_sync" / "sync_status.json"
    if sync_status_path.exists():
        try:
            status["lark_sync_status"] = json.loads(sync_status_path.read_text())
        except (json.JSONDecodeError, OSError):
            status["lark_sync_status"] = {"error": "corrupted sync_status.json"}
    print(json.dumps(status, indent=2))
```

**Step 4: Run tests**

Run: `.venv/bin/python3 -m pytest tests/test_orchestrate.py::TestBackgroundSync -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add sibyl/orchestrate.py tests/test_orchestrate.py
git commit -m "feat: add lark sync status display in cli_status"
```

---

### Task 7: Update sibyl-lark-sync SKILL.md with lock and error handling

**Files:**
- Modify: `.claude/skills/sibyl-lark-sync/SKILL.md`

**Step 1: Add lock acquisition section at the top of the execution flow**

After the `$ARGUMENTS` section and before the existing Step 1, insert a new preamble:

```markdown
## Pre-Flight: Lock Acquisition

Before syncing, acquire the lock to prevent concurrent sync operations:

1. Check if `lark_sync/sync.lock` exists in the workspace
2. If lock exists:
   - Read the lock file and check `started_at`
   - If older than 10 minutes → expired, take over (delete and recreate)
   - If fresh → wait 10 seconds, re-check (up to 30 retries = 5 minutes)
   - If still locked after 5 minutes → abort, write error to `sync_status.json`
3. Create `sync.lock` with content: `{"pid": <process_id>, "started_at": "<ISO timestamp>", "stage": "<trigger_stage>"}`
4. ALL subsequent steps MUST be wrapped in try/finally to ensure lock release

## Post-Sync: Result Recording

After sync completes (success or failure):

### On Success:
1. Read current `sync_status.json` (or create empty `{"history": []}`)
2. Count lines in `pending_sync.jsonl` to determine `last_synced_line`
3. Append to history: `{"at": "<ISO>", "success": true, "stages_synced": [...], "duration_sec": N}`
4. Update `last_sync_at`, `last_sync_success: true`, `last_synced_line`, `last_trigger_stage`
5. Write updated `sync_status.json`
6. Delete `sync.lock`
7. Report: "Feishu sync completed successfully for stages: [...]"

### On Failure:
1. Write error to `logs/errors.jsonl` using ErrorCollector format:
   ```json
   {"error_type": "<exception>", "category": "config", "message": "<error>", "context": {"source": "lark_sync", "stage": "<stage>"}, ...}
   ```
2. Update `sync_status.json` with `last_sync_success: false` and error in history
3. Delete `sync.lock`
4. Report: "Feishu sync FAILED: <error message>"
```

**Step 2: Verify SKILL.md is syntactically valid**

Read the updated file to confirm no markdown formatting issues.

**Step 3: Commit**

```bash
git add .claude/skills/sibyl-lark-sync/SKILL.md
git commit -m "feat: add lock mechanism and error handling to lark-sync skill"
```

---

### Task 8: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update the 飞书同步 section**

Replace the existing lark_sync documentation in CLAUDE.md. Key changes:
- Remove references to `lark_sync` as a pipeline stage
- Remove `resume_after_sync` references
- Document the new background sync mechanism:
  - `cli_record()` appends to `pending_sync.jsonl` and returns `sync_requested: true`
  - Main session launches `sibyl-lark-sync` as background agent
  - Lock file mechanism (`sync.lock`)
  - Result tracking (`sync_status.json`)
  - Error integration with self-heal system
- Document `cli_status()` now shows sync status

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for background Feishu sync architecture"
```

---

### Task 9: Run full test suite and final verification

**Files:**
- All modified files

**Step 1: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -x -q`
Expected: ALL tests pass.

**Step 2: Verify no stale references**

Run: `grep -rn "resume_after_sync" sibyl/ tests/ --include="*.py"`
Expected: No matches (all references removed).

Run: `grep -rn "_action_lark_sync" sibyl/ tests/ --include="*.py"`
Expected: No matches.

**Step 3: Verify pending_sync works end-to-end**

```bash
.venv/bin/python3 -c "
from sibyl.orchestrate import FarsOrchestrator
from sibyl.config import Config
from pathlib import Path
import tempfile, json

with tempfile.TemporaryDirectory() as tmp:
    ws_path = Path(tmp) / 'test-project'
    ws_path.mkdir()
    (ws_path / 'topic.txt').write_text('test')
    (ws_path / 'status.json').write_text(json.dumps({'stage': 'literature_search', 'started_at': 1, 'updated_at': 1, 'iteration': 1, 'errors': [], 'paused_at': 0, 'iteration_dirs': False}))
    (ws_path / 'lark_sync').mkdir()
    config = Config(lark_enabled=True, gpu_poll_enabled=False)
    o = FarsOrchestrator(str(ws_path), config=config)
    o.record_result('literature_search')
    pending = (ws_path / 'lark_sync' / 'pending_sync.jsonl').read_text()
    print('pending_sync.jsonl:', pending)
    print('new stage:', o.ws.get_status().stage)
    print('SUCCESS: background sync trigger works')
"
```

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found in final verification"
```

**Step 5: Push to dev**

```bash
git push origin dev
```
