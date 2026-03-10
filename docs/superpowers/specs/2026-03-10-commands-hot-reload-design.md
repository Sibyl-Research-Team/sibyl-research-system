# Commands Hot Reload Support

**Date:** 2026-03-10
**Status:** Approved

## Problem

Sibyl System's `plugin/commands/*.md` files don't support hot reloading in Claude Code. Two key issues:

1. `_orchestration-loop.md` contains hard-coded orchestration protocol (stage progression, action dispatch, polling, checkpoint recovery) referenced by 4 commands
2. Ralph Loop prompt is duplicated in `start.md` and `resume.md`

## Solution

Move all iterable logic from command files into `sibyl/prompts/` (hot-reloadable) and Python orchestrator, keeping commands as thin shells with comments + CLI calls.

## Changes

### 1. Orchestration Protocol Migration

- **From:** `plugin/commands/_orchestration-loop.md`
- **To:** `sibyl/prompts/orchestration_loop.md`
- Commands (`start`, `resume`, `continue`, `debug`) load via `load_prompt('orchestration_loop')`
- Delete or replace original with a one-line pointer

### 2. Ralph Loop Prompt Deduplication

- **New template:** `sibyl/prompts/ralph_loop.md` with `{project_name}`, `{workspace_path}`, `{iteration_num}` placeholders
- **New function:** `cli_write_ralph_prompt(project_name, workspace_path, iteration_num=None)` in `sibyl/orchestrate.py`
- `start.md` and `resume.md` replace inline prompt with one-line Python call

### 3. Command File Slimming

Each command retains:
1. YAML frontmatter (description, argument-hint)
2. Brief comment explaining purpose (2-3 lines)
3. Python CLI calls (all logic delegated)

## Files Affected

| File | Action |
|------|--------|
| `sibyl/prompts/orchestration_loop.md` | Create (migrate from `_orchestration-loop.md`) |
| `sibyl/prompts/ralph_loop.md` | Create (extract from `start.md`/`resume.md`) |
| `sibyl/orchestrate.py` | Add `cli_write_ralph_prompt()` |
| `plugin/commands/start.md` | Slim down |
| `plugin/commands/resume.md` | Slim down |
| `plugin/commands/continue.md` | Slim down |
| `plugin/commands/debug.md` | Slim down |
| `plugin/commands/_orchestration-loop.md` | Delete or replace with pointer |

## Constraints

- No changes to existing skills or agent prompts
- Python orchestrator CLI API (`cli_init`, `cli_next`, etc.) interface unchanged
- Only additive changes to `orchestrate.py`
