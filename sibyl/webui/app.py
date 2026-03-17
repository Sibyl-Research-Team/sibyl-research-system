"""Flask app factory and background runtime for the Sibyl WebUI."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask

from sibyl.config import Config
from sibyl.webui.conversation_watcher import ConversationWatcher
from sibyl.webui.control_api import control_bp
from sibyl.webui.monitor_api import monitor_bp
from sibyl.webui.session_registry import SessionRegistry
from sibyl.webui.state_watcher import categorize_change, read_state_snapshot
from sibyl.webui.ws_hub import WSHub

logger = logging.getLogger(__name__)


def _start_conversation_runtime(runtime: dict[str, Any]) -> None:
    registry = SessionRegistry(runtime["ws_dir"])
    hub: WSHub = runtime["hub"]
    watchers: dict[str, tuple[str, ConversationWatcher]] = runtime["conversation_watchers"]

    while True:
        try:
            sessions = registry.list_sessions()
            active_projects = {session["project"] for session in sessions}
            for project, (path_str, _watcher) in list(watchers.items()):
                if project not in active_projects:
                    watchers.pop(project, None)

            for session in sessions:
                conversation_path = session.get("conversation_jsonl")
                if not conversation_path:
                    continue
                existing = watchers.get(session["project"])
                if existing is None or existing[0] != conversation_path:
                    watchers[session["project"]] = (
                        str(conversation_path),
                        ConversationWatcher(Path(conversation_path)),
                    )

                entries = watchers[session["project"]][1].read_new_entries()
                if entries:
                    hub.broadcast_sync(
                        f"conversation:{session['project']}",
                        {
                            "type": "conversation_append",
                            "project": session["project"],
                            "entries": entries,
                        },
                    )
        except Exception:
            logger.exception("Conversation runtime loop failed")
        time.sleep(0.5)


def _start_state_runtime(runtime: dict[str, Any]) -> None:
    try:
        from watchfiles import watch
    except ModuleNotFoundError:
        logger.warning("watchfiles not installed; state WebSocket runtime disabled")
        return

    hub: WSHub = runtime["hub"]
    ws_dir: Path = runtime["ws_dir"]

    while True:
        try:
            for changes in watch(str(ws_dir)):
                for _change_type, path_str in changes:
                    category = categorize_change(path_str)
                    if category is None:
                        continue
                    try:
                        project = Path(path_str).resolve().relative_to(ws_dir.resolve()).parts[0]
                    except (ValueError, IndexError):
                        continue
                    hub.broadcast_sync(
                        f"state:{project}",
                        {
                            "type": category,
                            "project": project,
                            "snapshot": read_state_snapshot(ws_dir / project),
                        },
                    )
        except Exception:
            logger.exception("State runtime loop failed")
            time.sleep(1.0)


def _register_websocket_routes(app: Flask, runtime: dict[str, Any]) -> None:
    try:
        from flask_sock import Sock
    except ModuleNotFoundError:
        logger.warning("flask-sock not installed; WebSocket routes disabled")
        return

    sock = Sock(app)
    hub: WSHub = runtime["hub"]
    runtime["sock"] = sock

    @sock.route("/ws/conversation/<project>")
    def ws_conversation(ws, project):  # type: ignore[no-untyped-def]
        hub.register(f"conversation:{project}", ws)
        try:
            while True:
                message = ws.receive(timeout=30)
                if message is None:
                    continue
        except Exception:
            pass
        finally:
            hub.unregister(f"conversation:{project}", ws)

    @sock.route("/ws/state/<project>")
    def ws_state(ws, project):  # type: ignore[no-untyped-def]
        hub.register(f"state:{project}", ws)
        try:
            while True:
                message = ws.receive(timeout=30)
                if message is None:
                    continue
        except Exception:
            pass
        finally:
            hub.unregister(f"state:{project}", ws)


def _ensure_runtime_threads(runtime: dict[str, Any]) -> None:
    if os.environ.get("SIBYL_WEBUI_DISABLE_THREADS"):
        return
    if runtime["threads_started"]:
        return

    with runtime["lock"]:
        if runtime["threads_started"]:
            return

        for target, name in [
            (_start_conversation_runtime, "sibyl-webui-conversation"),
            (_start_state_runtime, "sibyl-webui-state"),
        ]:
            thread = threading.Thread(target=target, args=(runtime,), daemon=True, name=name)
            thread.start()
            runtime["threads"].append(thread)
        runtime["threads_started"] = True


def create_webui_app(config: Config | None = None) -> Flask:
    """Create the WebUI Flask app by extending the dashboard app."""
    if config is None:
        from sibyl.orchestration.config_helpers import load_effective_config

        config = load_effective_config()

    from sibyl.dashboard.server import create_app as create_dashboard_app

    app = create_dashboard_app(config)
    ws_dir = config.workspaces_dir.resolve()
    app.config["SIBYL_WS_DIR"] = ws_dir

    runtime = {
        "hub": WSHub(),
        "ws_dir": ws_dir,
        "lock": threading.Lock(),
        "threads": [],
        "threads_started": False,
        "conversation_watchers": {},
    }
    app.extensions["sibyl_webui"] = runtime

    app.register_blueprint(monitor_bp)
    app.register_blueprint(control_bp)
    _register_websocket_routes(app, runtime)
    _ensure_runtime_threads(runtime)
    return app


def run(port: int = 7654, host: str = "127.0.0.1", config: Config | None = None) -> None:
    """Run the WebUI server."""
    app = create_webui_app(config)
    ws_dir = Path(app.config["SIBYL_WS_DIR"]).resolve()
    print(f"\n  Sibyl WebUI running at http://{host}:{port}")
    print(f"  Serving workspaces from: {ws_dir}")
    print("  Press Ctrl+C to stop.\n")
    app.run(host=host, port=port, debug=False)
