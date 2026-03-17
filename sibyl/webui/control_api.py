"""Flask Blueprint for WebUI control and project-specific helper APIs."""

from __future__ import annotations

import json
import logging
import os
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from flask import Blueprint, abort, current_app, jsonify, request

from sibyl.config import Config
from sibyl.orchestrate import cli_pause, cli_resume, cli_sentinel_session
from sibyl.workspace import Workspace
from sibyl.webui.conversation_watcher import ConversationWatcher
from sibyl.webui.message_injector import MessageInjector
from sibyl.webui.session_registry import SessionRegistry

logger = logging.getLogger(__name__)

control_bp = Blueprint("webui-control", __name__, url_prefix="/api/projects")


def _get_ws_dir() -> Path:
    return Path(current_app.config["SIBYL_WS_DIR"])


def _resolve_project_root(project_name: str) -> Path:
    ws_dir = _get_ws_dir().resolve()
    project_root = (ws_dir / project_name).resolve()
    if not project_root.is_relative_to(ws_dir):
        abort(403, description="Path traversal not allowed")
    if not project_root.is_dir() or not (project_root / "status.json").exists():
        abort(404, description=f"Project not found: {project_name}")
    return project_root


def _open_workspace(project_name: str) -> Workspace:
    _resolve_project_root(project_name)
    return Workspace.open_existing(_get_ws_dir(), project_name)


def _registry() -> SessionRegistry:
    return SessionRegistry(_get_ws_dir())


def _validate_config_content(project_root: Path, content: str) -> None:
    try:
        payload = yaml.safe_load(content) if content.strip() else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Config YAML must decode to a mapping")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".yaml",
            prefix="sibyl-webui-",
            dir=project_root,
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        Config.from_yaml(str(temp_path))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminal_meta_path(project_name: str) -> Path:
    state_dir = Path(os.environ.get("SIBYL_TTYD_STATE_DIR", "/tmp"))
    return state_dir / f"sibyl_ttyd_{project_name}.json"


def _read_terminal_meta(project_name: str) -> dict[str, Any]:
    meta_path = _terminal_meta_path(project_name)
    if not meta_path.exists():
        return {"running": False, "project": project_name}

    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"running": False, "project": project_name}

    pid = int(payload.get("pid", 0) or 0)
    running = _pid_is_alive(pid)
    if not running:
        return {"running": False, "project": project_name}

    port = int(payload.get("port", 0) or 0)
    return {
        "running": True,
        "project": project_name,
        "pid": pid,
        "port": port,
        "url": payload.get("url") or (f"http://127.0.0.1:{port}" if port else ""),
    }


@control_bp.get("/<project_name>/conversation")
def conversation_history(project_name: str):
    _resolve_project_root(project_name)
    limit = request.args.get("limit", 50, type=int) or 50
    session = _registry().get_session(project_name)
    if not session or not session.get("conversation_jsonl"):
        return jsonify({"entries": [], "session": session})

    watcher = ConversationWatcher(Path(session["conversation_jsonl"]))
    return jsonify({"entries": watcher.tail(limit), "session": session})


@control_bp.post("/<project_name>/send-message")
def send_message(project_name: str):
    _resolve_project_root(project_name)
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify(error="Missing 'text' field"), 400

    session = _registry().get_session(project_name)
    if not session or not session.get("tmux_pane"):
        return jsonify(error="No active Claude session"), 409

    result = MessageInjector().send(str(session["tmux_pane"]), text)
    return jsonify(result), 200 if result.get("ok") else 502


@control_bp.post("/<project_name>/stop")
def stop_project(project_name: str):
    project_root = _resolve_project_root(project_name)
    session = _registry().get_session(project_name)

    if session and session.get("tmux_pane"):
        result = MessageInjector().send(str(session["tmux_pane"]), f"/sibyl-research:stop {project_name}")
        return jsonify({"ok": bool(result.get("ok")), "mode": "tmux", "result": result}), 200

    stop_file = project_root / "sentinel_stop.json"
    stop_file.write_text(json.dumps({"stop": True, "timestamp": time.time()}), encoding="utf-8")
    pause_payload = cli_pause(str(project_root), "user_stop")
    cli_sentinel_session(str(project_root), "", "")
    return jsonify({"ok": True, "mode": "fallback", "result": pause_payload})


@control_bp.post("/<project_name>/resume")
def resume_project(project_name: str):
    project_root = _resolve_project_root(project_name)
    session = _registry().get_session(project_name)

    if session and session.get("tmux_pane"):
        result = MessageInjector().send(str(session["tmux_pane"]), f"/sibyl-research:resume {project_name}")
        return jsonify({"ok": bool(result.get("ok")), "mode": "tmux", "result": result}), 200

    (project_root / "sentinel_stop.json").unlink(missing_ok=True)
    result = cli_resume(str(project_root))
    return jsonify({"ok": True, "mode": "fallback", "result": result})


@control_bp.get("/<project_name>/config")
def get_project_config(project_name: str):
    workspace = _open_workspace(project_name)
    content = workspace.read_file("config.yaml") or ""
    return jsonify({"content": content})


@control_bp.put("/<project_name>/config")
def update_project_config(project_name: str):
    project_root = _resolve_project_root(project_name)
    workspace = _open_workspace(project_name)
    payload = request.get_json(silent=True) or {}
    content = payload.get("content")
    if not isinstance(content, str):
        return jsonify(error="Missing 'content' field"), 400

    try:
        _validate_config_content(project_root, content)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    workspace.write_file("config.yaml", content)
    return jsonify({"ok": True})


@control_bp.get("/<project_name>/terminal-info")
def terminal_info(project_name: str):
    _resolve_project_root(project_name)
    return jsonify(_read_terminal_meta(project_name))
