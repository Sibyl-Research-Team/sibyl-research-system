"""Repo-level control plane contract tests.

These guard cross-layer drift between the Python orchestrator, plugin docs,
prompt files, and Claude runtime assets.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_is_ignored(rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_required_claude_agents_exist():
    for rel_path in (
        ".claude/agents/sibyl-heavy.md",
        ".claude/agents/sibyl-standard.md",
        ".claude/agents/sibyl-light.md",
    ):
        assert (REPO_ROOT / rel_path).is_file(), rel_path


def test_orchestrator_skills_have_backing_skill_files():
    orchestrate = (REPO_ROOT / "sibyl/orchestrate.py").read_text(encoding="utf-8")
    skill_names = sorted(
        skill_name
        for skill_name in set(re.findall(r'"(?:name|skill)":\s*"(sibyl-[^"]+)"', orchestrate))
        if skill_name != "sibyl-xxx"
    )

    missing = [
        skill_name
        for skill_name in skill_names
        if not (REPO_ROOT / ".claude" / "skills" / skill_name / "SKILL.md").is_file()
    ]

    assert not missing, missing


def test_claude_runtime_assets_are_not_gitignored():
    assert not _git_is_ignored(".claude/agents/sibyl-standard.md")
    assert not _git_is_ignored(".claude/skills/sibyl-planner/SKILL.md")
    assert _git_is_ignored(".claude/settings.local.json")


def test_sibyl_skill_prompt_loaders_are_workspace_aware():
    skill_files = sorted((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    checked = 0
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        if "load_common_prompt" not in text:
            continue
        checked += 1
        assert 'SIBYL_WORKSPACE="' in text, path
        assert "ws = os.environ.get('SIBYL_WORKSPACE', '')" in text, path
        assert "load_common_prompt(ws)" in text, path
        assert "workspace_path=ws" in text, path

    assert checked > 0


def test_no_stale_user_home_evolution_paths_in_skills():
    checked = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "README_CN.md",
        REPO_ROOT / "plugin" / "commands" / "evolve.md",
        *sorted((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md")),
        *sorted((REPO_ROOT / "docs").glob("*.md")),
    ]
    offending = []
    for path in checked:
        text = path.read_text(encoding="utf-8")
        if "~/.claude/sibyl_evolution" in text:
            offending.append(str(path.relative_to(REPO_ROOT)))
    assert not offending, offending


def test_plugin_language_defaults_use_zh():
    """Language default 'zh' must appear in orchestration loop or command files."""
    # The language default is in the orchestration loop prompt (migrated to sibyl/prompts/)
    checked_files = [
        "sibyl/prompts/orchestration_loop.md",
        "plugin/commands/start.md",
        "plugin/commands/resume.md",
    ]
    found_zh = any(
        '默认 "zh"' in (REPO_ROOT / f).read_text(encoding="utf-8")
        for f in checked_files
    )
    assert found_zh, "No file contains language default 'zh'"


def test_no_stale_hardcoded_language_clauses():
    banned = (
        "All output in Chinese",
        "All writing in Chinese",
    )
    checked_paths = [
        REPO_ROOT / "sibyl/orchestrate.py",
        *sorted((REPO_ROOT / "sibyl/prompts").glob("*.md")),
        *sorted((REPO_ROOT / "plugin/commands").glob("*.md")),
    ]
    offending = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        for phrase in banned:
            if phrase in text:
                offending.append(f"{path.relative_to(REPO_ROOT)}: {phrase}")
    assert not offending, offending


def test_writing_prompts_fix_paper_language_contract():
    codex_prompt = (REPO_ROOT / "sibyl/prompts/codex_writer.md").read_text(encoding="utf-8")
    latex_prompt = (REPO_ROOT / "sibyl/prompts/latex_writer.md").read_text(encoding="utf-8")

    assert "English academic section draft" in codex_prompt
    assert "All paper sections must remain in English" in codex_prompt
    assert "已有英文论文草稿" in latex_prompt
    assert "翻译成英文" not in latex_prompt


def test_architecture_docs_describe_project_scoped_gpu_marker():
    architecture_doc = (REPO_ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    assert "/tmp/sibyl_<project>_gpu_free.json" in architecture_doc


def test_background_lark_sync_docs_match_runtime_contract():
    loop_doc = (REPO_ROOT / "sibyl/prompts/orchestration_loop.md").read_text(encoding="utf-8")
    debug_doc = (REPO_ROOT / "plugin/commands/debug.md").read_text(encoding="utf-8")
    architecture_doc = (REPO_ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    setup_doc = (REPO_ROOT / "docs/feishu-lark-setup.md").read_text(encoding="utf-8")

    assert "sync_requested" in loop_doc
    assert "pending_sync.jsonl" in loop_doc
    assert "run_in_background" in loop_doc
    assert "lark_sync → quality_gate" not in loop_doc
    assert "完整同步在 lark_sync 阶段" not in loop_doc

    assert "sync_requested" in debug_doc
    assert "后台启动 `sibyl-lark-sync" in debug_doc
    assert '"lark_sync": 由 sibyl-lark-sync skill 自动执行飞书同步。' not in debug_doc

    assert "18-stage state machine" in architecture_doc
    assert "pending_sync.jsonl" in architecture_doc
    assert "lark_sync → quality_gate" not in architecture_doc
    assert "inserts a `lark_sync` stage" not in architecture_doc

    assert "sync_requested: true" in setup_doc
    assert "pending_sync.jsonl" in setup_doc
    assert "background" in setup_doc.lower()
    assert "lark_sync` is automatically triggered" not in setup_doc


def test_gpu_poll_docs_describe_never_stop_contract():
    """GPU poll docs must describe never-stop behavior (no pause on timeout)."""
    required = {
        "CLAUDE.md": ("action.gpu_poll.script", "永不放弃"),
        "sibyl/prompts/orchestration_loop.md": ("gpu_poll", "永不放弃"),
    }

    for rel_path, snippets in required.items():
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"{rel_path} missing {snippet}"

    # Verify no file tells the system to pause on GPU poll timeout
    for rel_path in ("sibyl/prompts/orchestration_loop.md",):
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "gpu_poll_timeout" not in text, f"{rel_path} still references gpu_poll_timeout pause"


def test_experiment_wait_docs_match_runtime_contract():
    """experiment_wait polling cadence should stay aligned across docs/runtime."""
    required = {
        "CLAUDE.md": ("<30min→2min", "30-120min→5min", ">120min→10min"),
        "sibyl/prompts/orchestration_loop.md": ("剩余 ≤30min: 每 2min", "剩余 30-120min: 每 5min", "剩余 >120min: 每 10min"),
    }

    for rel_path, snippets in required.items():
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"{rel_path} missing {snippet}"


def test_codex_integration_is_explicit_opt_in_everywhere():
    required = {
        "config.example.yaml": ("codex_enabled: false",),
        "setup.sh": ("codex_enabled: false", "Codex stays disabled by default"),
        "docs/configuration.md": (
            "| `codex_enabled` | bool | `false` |",
            "Requires `codex_enabled: true`; otherwise Sibyl falls back to `parallel`.",
        ),
        "docs/codex-integration.md": ("Default: false",),
        "docs/mcp-servers.md": ("default is `false`",),
    }

    for rel_path, snippets in required.items():
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"{rel_path} missing {snippet}"


def test_setup_docs_prefer_claude_cli_mcp_registration():
    required = {
        "docs/setup-guide.md": (
            "claude mcp add --scope local ssh-mcp-server",
            "claude mcp add --scope local arxiv-mcp-server",
            ".venv/bin/python3",
        ),
        "docs/mcp-servers.md": (
            "claude mcp add --scope local ssh-mcp-server",
            "claude mcp add --scope local arxiv-mcp-server",
            "Manual JSON fallback",
        ),
        "docs/getting-started.md": (
            "claude mcp add --scope local",
            ".venv/bin/pip install -e .",
        ),
    }

    for rel_path, snippets in required.items():
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"{rel_path} missing {snippet}"


def test_config_docs_match_runtime_defaults():
    config_ref = (REPO_ROOT / "docs/configuration.md").read_text(encoding="utf-8")
    config_example = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")

    assert '| `ssh_server` | string | `"default"` |' in config_ref
    assert 'language: zh' in config_example
    assert 'ssh_server: "default"' in config_example
    assert 'language: en' not in config_example


def test_no_unresolved_env_or_pilot_placeholders_in_prompts():
    checked = (
        REPO_ROOT / "sibyl/prompts/_common.md",
        REPO_ROOT / "sibyl/prompts/_common_zh.md",
        REPO_ROOT / "sibyl/prompts/planner.md",
        REPO_ROOT / "sibyl/prompts/experimenter.md",
        REPO_ROOT / "sibyl/prompts/server_experimenter.md",
    )
    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert "{env_cmd}" not in text, path
        assert "{pilot_samples}" not in text, path
        assert "{pilot_timeout}" not in text, path
