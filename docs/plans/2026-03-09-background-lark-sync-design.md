# Background Feishu Sync Design

**Date**: 2026-03-09
**Status**: Approved

## Problem

Current `lark_sync` is a blocking pipeline stage inserted by `_get_next_stage()` after every substantive stage. This blocks the main research flow until sync completes (~10-30s per sync). Feishu sync failures also block pipeline progression.

## Design Decision

Convert Feishu sync from a blocking pipeline stage to a background agent triggered after each `cli_record()`. Uses lock-based mutual exclusion with automatic merging of concurrent sync requests.

## Architecture

```
Stage N completes
    ↓
cli_record(workspace, stage_N)
    ↓  advance state → stage N+1
    ↓  append to lark_sync/pending_sync.jsonl
    ↓  return sync_requested=true
    ↓
Main session detects sync_requested
    ↓
Agent(sibyl-lark-sync, run_in_background=true)
    ↓                              ↓
Main flow continues            Background sync agent:
cli_next() → stage N+1          1. Check sync.lock
    ...                          2. Lock exists → wait (10s interval, 5min max)
                                 3. Acquire lock → sync all pending content
                                 4. Write sync_status.json
                                 5. On failure → also write errors.jsonl
                                 6. Release lock
                                 7. Return message (success or failure)
```

## File Layout

```
lark_sync/
├── pending_sync.jsonl    # Append-only sync trigger log
├── sync.lock             # Mutex lock file (PID + timestamp)
├── sync_status.json      # Latest sync result + history
└── registry.json         # Existing: Feishu resource tokens
```

## Lock & Merge Mechanism

### Lock File Format (`sync.lock`)
```json
{"pid": 12345, "started_at": "2026-03-09T12:00:00Z", "stage": "literature_search"}
```

### Merge Logic
1. Agent B starts, finds `sync.lock` exists
2. Polls every 10s, up to 5min
3. After lock releases, Agent B reads latest workspace state and syncs everything since last `registry.json` position
4. Incremental sync naturally merges — only content after registry's last position is synced

### Dead Lock Protection
- Lock older than 10min is considered expired, taken over
- Agent uses `try/finally` to ensure lock release on exceptions

### Pending Sync Log (`pending_sync.jsonl`)
```jsonl
{"trigger_stage": "literature_search", "timestamp": "2026-03-09T12:00:00Z", "iteration": 1}
{"trigger_stage": "idea_debate", "timestamp": "2026-03-09T12:05:00Z", "iteration": 1}
```
- Each `cli_record` **appends** one line (never overwrites)
- Sync agent records `last_synced_line` in `sync_status.json`
- Full history preserved for traceability

## Error Handling & Self-Heal Integration

### Two-Layer Error Chain

**Layer 1 — ErrorCollector**: Sync failures written to `logs/errors.jsonl` with `context.source = "lark_sync"`. Categorized as `config` (token/API) or `state` (data issues).

**Layer 2 — sync_status.json**: Records failure details for `cli_status()` visibility.

Both success and failure trigger an agent return message visible to the main session.

### Self-Heal Route
- No changes to `SKILL_ROUTE_TABLE` — Feishu errors are `config`/`state`, already routed to `systematic-debugging`
- `context.source` field lets self-healer know the error origin
- After fix, self-healer appends a retry record to `pending_sync.jsonl`

### sync_status.json Format
```json
{
  "last_sync_at": "2026-03-09T12:05:30Z",
  "last_sync_success": true,
  "last_synced_line": 2,
  "last_trigger_stage": "idea_debate",
  "history": [
    {"at": "...", "success": true, "stages_synced": ["literature_search", "idea_debate"], "duration_sec": 12},
    {"at": "...", "success": false, "error": "token expired", "stages_synced": []}
  ]
}
```

## Code Changes

### Remove
- `STAGES` list: `"lark_sync"` entry
- `_action_lark_sync()` method
- `_get_next_stage()`: `lark_sync` insertion logic (~20 lines involving `resume_after_sync`)
- `_compute_action()`: `"lark_sync"` branch
- `WorkspaceStatus.resume_after_sync` field and `set_resume_after_sync()` method

### Modify
- **`cli_record()`**: After stage advance, if `lark_enabled`, append to `pending_sync.jsonl`, add `sync_requested: true` to return value
- **`sibyl-lark-sync` SKILL.md**: Add lock detection (~10 lines), result writing, error collection
- **`cli_status()`**: Read and display `sync_status.json`

### No Changes
- Feishu sync core logic (registry, incremental sync, block conversion)
- `self_heal.py` route table
- `error_collector.py`
- `config.py` (reuses existing `lark_enabled`)

## Estimated Impact
- Remove ~40 lines (old lark_sync stage logic)
- Add ~30 lines (cli_record signal + cli_status display)
- Modify SKILL.md ~20 lines (lock + result writing)
