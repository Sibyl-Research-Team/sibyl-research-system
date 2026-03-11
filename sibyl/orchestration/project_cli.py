"""Project bootstrap/listing CLI helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from sibyl.workspace import Workspace

from .common_utils import slugify_project_name
from .config_helpers import load_effective_config, write_project_config
from .workspace_paths import load_workspace_iteration_dirs, resolve_workspace_root


def _build_post_init_guide(
    workspace_path: str,
    project_name: str,
    topic: str,
    config: Any,
    *,
    has_spec: bool = False,
) -> str:
    """Build the formatted post-init guide as a string.

    Returns the full guide text so the caller can embed it in JSON output.
    The plugin command is responsible for displaying it directly in the
    conversation (not via Bash), avoiding Claude Code's output folding.
    """
    ws = Path(workspace_path)
    repo_root = Path(__file__).resolve().parents[2]
    expected_sibyl_root = str(repo_root)
    current_sibyl_root = os.environ.get("SIBYL_ROOT")
    config_path = ws / "config.yaml"
    spec_path = ws / "spec.md"

    lines = [
        "",
        "╔══════════════════════════════════════════════════════════════╗",
        "║  项目初始化完成                                              ║",
        "╚══════════════════════════════════════════════════════════════╝",
        "",
        f"  项目名称:  {project_name}",
        f"  研究主题:  {topic}",
        f"  工作目录:  {workspace_path}",
        "",
        "── 项目结构 ──────────────────────────────────────────────────",
        "",
        f"  {ws.name}/",
        "  ├── config.yaml        ← 项目配置（GPU、模型、实验参数）",
        "  ├── spec.md            ← 研究规格书（主题、背景、约束）",
        "  ├── topic.txt          ← 研究主题（一行文本）",
        "  ├── status.json        ← 流水线状态（自动维护）",
        "  ├── .sibyl/project/",
        "  │   └── MEMORY.md      ← 项目记忆（长期约束、偏好）",
        "  └── .claude/           ← 系统资源 symlink（自动创建）",
        "",
        "── 下一步 ────────────────────────────────────────────────────",
        "",
    ]

    if current_sibyl_root == expected_sibyl_root:
        lines.append("  环境检查:")
        lines.append(f"     SIBYL_ROOT 已正确配置为 {expected_sibyl_root}")
        lines.append("")
    else:
        lines.append("  环境检查:")
        lines.append("     检测到当前 shell 的 SIBYL_ROOT 未设置，或指向了别的 Sibyl 仓库。")
        lines.append(f"     当前值: {current_sibyl_root or '<未设置>'}")
        lines.append(f"     期望值: {expected_sibyl_root}")
        lines.append("     建议先把下面这一行写入 ~/.zshrc 或 ~/.bashrc，然后重新打开一个 shell / tmux pane:")
        lines.append(f"       export SIBYL_ROOT={shlex.quote(expected_sibyl_root)}")
        lines.append("")

    step = 1

    needs_remote = (
        config.remote_base == "/home/user/sibyl_system"
        or config.ssh_server == "default"
    )
    if needs_remote:
        lines.append(f"  {step}. 编辑 config.yaml — 设置你的远程服务器:")
        lines.append(f"     {config_path}")
        lines.append("")
        lines.append("     必须修改的字段:")
        if config.remote_base == "/home/user/sibyl_system":
            lines.append("       remote_base: /home/your_username/sibyl_system")
        if config.ssh_server == "default":
            lines.append("       ssh_server: your-ssh-connection-name")
        lines.append("")
        step += 1

    if not has_spec:
        lines.append(f"  {step}. 编辑 spec.md — 描述你的研究:")
        lines.append(f"     {spec_path}")
        lines.append("")
        lines.append("     填写: 研究主题、背景动机、初始想法、参考文献、实验约束")
        lines.append("")
        step += 1

    lines.append(f"  {step}. (可选) 根据需要调整 config.yaml 中的其他参数:")
    lines.append("     - pilot_samples: 100      # pilot 样本数（建议 100+）")
    lines.append(f"     - max_gpus: {config.max_gpus}              # 最大 GPU 数")
    lines.append(f"     - writing_mode: {config.writing_mode}      # sequential | parallel | codex")
    lines.append(f"     - iteration_dirs: {'true' if config.iteration_dirs else 'false'}       # 长期项目建议开启")
    lines.append("")
    step += 1

    lines.append(f"  {step}. 启动研究循环:")
    lines.append("     建议先在新的 tmux pane / window 中，从该项目 workspace 根目录启动 Claude:")
    lines.append(f"       export SIBYL_ROOT={shlex.quote(expected_sibyl_root)}")
    lines.append(f"       cd {shlex.quote(str(ws))}")
    lines.append("       claude --plugin-dir \"$SIBYL_ROOT/plugin\" --dangerously-skip-permissions")
    lines.append("")
    lines.append("     然后在该 Claude 会话中执行:")
    lines.append("       /sibyl-research:start spec.md")
    lines.append("")
    lines.append("     如果要并行跑多个项目：每个项目各开一个 tmux pane/session，且都从各自的 workspace 根目录启动。")
    lines.append("")

    lines.append("─────────────────────────────────────────────────────────────")
    lines.append("")

    return "\n".join(lines)


def cli_list_projects(workspaces_dir: str | None = None) -> None:
    """List all known projects under a workspaces directory."""
    if workspaces_dir is None:
        ws_dir = load_effective_config().workspaces_dir
    else:
        ws_dir = Path(workspaces_dir)
    if not ws_dir.exists():
        print(json.dumps([]))
        return

    projects = []
    for path in sorted(ws_dir.iterdir()):
        if not path.is_dir() or not (path / "status.json").exists():
            continue
        try:
            ws = Workspace.open_existing(ws_dir, path.name)
            meta = ws.get_project_metadata()
            meta["topic"] = ws.read_file("topic.txt") or ""
            projects.append(meta)
        except Exception:
            continue

    print(json.dumps(projects, indent=2))


def _spec_template(project_name: str, config: Any) -> str:
    return f"""# 项目: {project_name}

## 研究主题
<!-- 一句话描述研究主题 -->

## 背景与动机
<!-- 为什么要研究这个？有什么已知的相关工作？ -->

## 初始想法
<!-- 你已有的想法或方向（可选） -->

## 关键参考文献
<!-- 论文 URL、arXiv ID 等 -->
-

## 可用资源
- GPU: {config.max_gpus}x on {config.ssh_server}
- 服务器: {config.ssh_server}
- 远程路径: {config.remote_base}

## 实验约束
- 实验类型: training-free / 轻量训练 / 不限
- 模型规模: 小 (GPT-2, BERT-base, Qwen-0.5B)
- 时间预算:

## 目标产出
- 论文 / 技术报告 / 实验验证

## 特殊需求
<!-- 任何特殊需求 -->
"""


def cli_init_spec(
    project_name: str,
    *,
    config_path: str | None = None,
) -> None:
    """Initialize a project directory for spec editing."""
    config = load_effective_config(config_path=config_path)
    ws = Workspace(
        config.workspaces_dir,
        project_name,
        iteration_dirs=config.iteration_dirs,
    )
    write_project_config(ws, config)
    ws.write_file("spec.md", _spec_template(project_name, config))

    guide = _build_post_init_guide(
        str(ws.root), project_name, project_name, config, has_spec=False,
    )
    result = {
        "project_name": project_name,
        "workspace_path": str(ws.root),
        "spec_path": str(ws.root / "spec.md"),
        "guide": guide,
    }
    print(json.dumps(result, indent=2))


def _extract_topic(spec_content: str, default_topic: str) -> str:
    topic_match = re.search(r"##\s*(?:Topic|研究主题)\s*\n+(.+?)(?:\n\n|\n##)", spec_content, re.DOTALL)
    topic = topic_match.group(1).strip() if topic_match else default_topic
    return re.sub(r"<!--.*?-->", "", topic).strip()


def _extract_optional_section(spec_content: str, pattern: str) -> str:
    match = re.search(pattern, spec_content, re.DOTALL)
    if not match:
        return ""
    content = re.sub(r"<!--.*?-->", "", match.group(1)).strip()
    return content


def cli_init_from_spec(
    spec_path: str,
    *,
    config_path: str | None = None,
) -> None:
    """Initialize or refresh a project from a spec markdown file."""
    spec_file = Path(spec_path)
    if not spec_file.exists():
        print(json.dumps({"error": f"Spec file not found: {spec_path}"}))
        return

    spec_content = spec_file.read_text(encoding="utf-8")
    existing_workspace_root = resolve_workspace_root(spec_file.parent)
    if spec_file.name == "spec.md" and (existing_workspace_root / "status.json").exists():
        project_name = existing_workspace_root.name
        config = load_effective_config(
            workspace_path=existing_workspace_root,
            config_path=config_path,
        )
        iteration_dirs = load_workspace_iteration_dirs(
            existing_workspace_root,
            config.iteration_dirs,
        )
        ws = Workspace(
            existing_workspace_root.parent,
            existing_workspace_root.name,
            iteration_dirs=iteration_dirs,
        )
    else:
        match = re.search(r"^#\s*(?:Project|项目):\s*(.+)", spec_content, re.MULTILINE)
        project_name = match.group(1).strip() if match else spec_file.stem
        project_name = slugify_project_name(project_name)
        config = load_effective_config(config_path=config_path)
        ws = Workspace(
            config.workspaces_dir,
            project_name,
            iteration_dirs=config.iteration_dirs,
        )

    write_project_config(ws, config)

    topic = _extract_topic(spec_content, project_name)
    ws.write_file("spec.md", spec_content)
    ws.write_file("topic.txt", topic)
    ws.update_stage("init")
    ws.git_init()

    references = _extract_optional_section(
        spec_content,
        r"##\s*(?:Key References|关键参考文献)\s*\n(.+?)(?:\n##|\Z)",
    )
    if references:
        ws.write_file("idea/references_seed.md", references)

    initial_ideas = _extract_optional_section(
        spec_content,
        r"##\s*(?:Initial Ideas|初始想法)\s*\n(.+?)(?:\n##|\Z)",
    )
    if initial_ideas:
        ws.write_file("idea/initial_ideas.md", initial_ideas)

    guide = _build_post_init_guide(
        str(ws.root), project_name, topic, config, has_spec=True,
    )
    result = {
        "project_name": project_name,
        "workspace_path": str(ws.root),
        "topic": topic,
        "spec_path": str(ws.root / "spec.md"),
        "config": {
            "ssh_server": config.ssh_server,
            "remote_base": config.remote_base,
            "max_gpus": config.max_gpus,
            "pilot_samples": config.pilot_samples,
            "full_seeds": config.full_seeds,
            "lark_enabled": config.lark_enabled,
        },
        "guide": guide,
    }
    print(json.dumps(result, indent=2))
