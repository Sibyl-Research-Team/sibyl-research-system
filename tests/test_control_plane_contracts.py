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


def test_plugin_language_defaults_use_zh():
    for rel_path in (
        "plugin/commands/start.md",
        "plugin/commands/resume.md",
    ):
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert '默认 "zh"' in text
        assert '默认 "en"' not in text


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


def test_gpu_poll_docs_describe_timeout_contract():
    required = {
        "CLAUDE.md": ("action.gpu_poll.max_attempts", "cli_pause", "action.gpu_poll.script"),
        "plugin/commands/start.md": ("action.gpu_poll.max_attempts", "cli_pause", "gpu_poll_timeout"),
        "plugin/commands/resume.md": ("action.gpu_poll.max_attempts", "cli_pause", "gpu_poll_timeout"),
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
