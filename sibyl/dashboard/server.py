"""Sibyl Dashboard — lightweight Flask web server for monitoring.

Wraps existing orchestrator functions as JSON API endpoints and serves
a Vue 3 SPA for real-time project monitoring and artifact browsing.

Usage:
    sibyl dashboard [--port 7654] [--host 127.0.0.1]
"""

import hashlib
import hmac
import json
import mimetypes
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort

from sibyl._paths import REPO_ROOT, get_system_evolution_dir
from sibyl.config import Config
from sibyl.orchestration.dashboard_data import collect_dashboard_data

# Ensure common types are registered
mimetypes.add_type("application/pdf", ".pdf")
mimetypes.add_type("text/markdown", ".md")

# ── Auth ──────────────────────────────────────────────────────────────
_AUTH_KEY = os.environ.get("SIBYL_DASHBOARD_KEY", "").strip()
_AUTH_COOKIE = "sibyl_auth"
_AUTH_MAX_AGE = 30 * 86400  # 30 days


def _make_auth_token(key: str) -> str:
    return hashlib.sha256(f"sibyl-dashboard:{key}".encode()).hexdigest()


def create_app(config: Config | None = None) -> Flask:
    """Create and configure the Flask app."""
    if config is None:
        from sibyl.orchestration.config_helpers import load_effective_config

        config = load_effective_config()
    static_dir = Path(__file__).parent / "static"

    app = Flask(
        __name__,
        static_folder=str(static_dir),
        static_url_path="/static",
    )
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # no caching in dev

    ws_dir = config.workspaces_dir

    # ── Helper ────────────────────────────────────────────────────────

    def _get_workspace(project_name: str):
        """Return a Workspace instance, abort 404 if not found."""
        from sibyl.workspace import Workspace

        project_root = (ws_dir / project_name).resolve()
        if not project_root.is_relative_to(ws_dir.resolve()):
            abort(403, description="Path traversal not allowed")
        if not project_root.is_dir() or not (project_root / "status.json").exists():
            abort(404, description=f"Project not found: {project_name}")
        return Workspace.open_existing(ws_dir, project_name)

    def _safe_resolve(ws_root: Path, rel_path: str) -> Path:
        """Resolve a relative path within workspace, block traversal."""
        resolved = (ws_root / rel_path).resolve()
        if not resolved.is_relative_to(ws_root.resolve()):
            abort(403, description="Path traversal not allowed")
        if not resolved.exists():
            abort(404, description=f"File not found: {rel_path}")
        return resolved

    def _list_project_metadata() -> list[dict]:
        projects = []
        if not ws_dir.exists():
            return projects

        for d in sorted(ws_dir.iterdir()):
            if not d.is_dir() or not (d / "status.json").exists():
                continue
            try:
                ws = _get_workspace(d.name)
                meta = ws.get_project_metadata()
                meta["topic"] = ws.read_file("topic.txt") or ""
                projects.append(meta)
            except Exception:
                continue
        return projects

    def _list_repo_tools() -> list[str]:
        tools_root = REPO_ROOT / "tools"
        if not tools_root.exists():
            return []
        return sorted(
            item.name
            for item in tools_root.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )

    def _collect_system_status() -> dict:
        projects = _list_project_metadata()
        repo_tools = _list_repo_tools()
        evolution_dir = get_system_evolution_dir()
        outcomes_path = evolution_dir / "outcomes.jsonl"
        outcomes_count = 0
        if outcomes_path.exists():
            try:
                outcomes_count = sum(
                    1 for line in outcomes_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            except OSError:
                outcomes_count = 0

        return {
            "system_root": str(REPO_ROOT.resolve()),
            "workspaces_dir": str(ws_dir.resolve()),
            "tools_dir": str((REPO_ROOT / "tools").resolve()),
            "project_count": len(projects),
            "runtime_ready_count": sum(1 for p in projects if p.get("runtime_ready")),
            "scaffold_ready_count": sum(
                1 for p in projects if p.get("runtime", {}).get("scaffold_ready")
            ),
            "migration_needed_count": sum(1 for p in projects if p.get("migration_needed")),
            "legacy_status_count": sum(
                1 for p in projects if p.get("runtime", {}).get("legacy_status_schema")
            ),
            "prompt_count": len(list((REPO_ROOT / "sibyl" / "prompts").glob("*.md"))),
            "skill_count": len(list((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md"))),
            "agent_count": len(list((REPO_ROOT / ".claude" / "agents").glob("*.md"))),
            "tool_count": len(repo_tools),
            "tool_names": repo_tools,
            "evolution_dir": str(evolution_dir.resolve()),
            "evolution_lesson_count": len(list((evolution_dir / "lessons").glob("*.md"))),
            "evolution_outcome_count": outcomes_count,
            "ts": time.time(),
        }

    # ── Auth middleware ─────────────────────────────────────────────────

    @app.before_request
    def check_auth():
        if not _AUTH_KEY:
            return None
        if request.path.startswith("/api/auth") or \
           request.path in ("/", "/api/health") or \
           request.path.startswith("/static/"):
            return None
        token = request.cookies.get(_AUTH_COOKIE)
        if token and hmac.compare_digest(token, _make_auth_token(_AUTH_KEY)):
            return None
        return jsonify(error="Unauthorized"), 401

    # ── Routes ────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return send_file(static_dir / "index.html")

    @app.route("/api/health")
    def health():
        return jsonify(ok=True, ts=time.time())

    @app.route("/api/auth", methods=["POST"])
    def auth_login():
        if not _AUTH_KEY:
            return jsonify(ok=True)
        data = request.get_json(silent=True) or {}
        key = data.get("key", "")
        if key and hmac.compare_digest(key, _AUTH_KEY):
            resp = jsonify(ok=True)
            resp.set_cookie(
                _AUTH_COOKIE, _make_auth_token(_AUTH_KEY),
                max_age=_AUTH_MAX_AGE, httponly=True, samesite="Lax",
            )
            return resp
        return jsonify(error="Invalid key"), 403

    @app.route("/api/auth/check")
    def auth_check():
        if not _AUTH_KEY:
            return jsonify(ok=True, auth_required=False)
        token = request.cookies.get(_AUTH_COOKIE)
        if token and hmac.compare_digest(token, _make_auth_token(_AUTH_KEY)):
            return jsonify(ok=True, auth_required=True)
        return jsonify(ok=False, auth_required=True)

    @app.route("/api/projects")
    def list_projects():
        return jsonify(_list_project_metadata())

    @app.route("/api/system/status")
    def system_status():
        return jsonify(_collect_system_status())

    @app.route("/api/projects/<project_name>/dashboard")
    def project_dashboard(project_name: str):
        events_tail = request.args.get("events_tail", 50, type=int)
        ws = _get_workspace(project_name)

        dashboard = collect_dashboard_data(ws.root, events_tail=events_tail)
        return app.response_class(
            json.dumps(dashboard, ensure_ascii=False, default=str),
            mimetype="application/json",
        )

    @app.route("/api/projects/<project_name>/files")
    def list_files(project_name: str):
        ws = _get_workspace(project_name)
        rel_dir = request.args.get("dir", "")
        base = ws.root.resolve()

        if rel_dir:
            target = _safe_resolve(ws.root, rel_dir)
        else:
            target = base

        if not target.is_dir():
            abort(400, description="Not a directory")

        files = []
        dirs = []
        skip = {".git", "__pycache__", ".venv", "node_modules", ".claude"}
        allow_hidden = {".sibyl"}
        try:
            for item in sorted(target.iterdir()):
                if item.name in skip:
                    continue
                if item.name.startswith(".") and item.name not in allow_hidden:
                    continue
                # Use resolve() to handle symlinks before computing relative path
                try:
                    rel = str(item.resolve().relative_to(base))
                except ValueError:
                    # Symlink target outside workspace — use name from target dir
                    rel = str(item.relative_to(target))
                    if rel_dir:
                        rel = f"{rel_dir}/{rel}"
                if item.is_dir():
                    dirs.append({"name": item.name, "path": rel, "type": "dir"})
                elif item.is_file():
                    files.append({
                        "name": item.name,
                        "path": rel,
                        "type": "file",
                        "size": item.stat().st_size,
                        "ext": item.suffix.lower(),
                    })
        except PermissionError:
            pass

        return jsonify({"dirs": dirs, "files": files})

    @app.route("/api/projects/<project_name>/file")
    def get_file(project_name: str):
        ws = _get_workspace(project_name)
        rel_path = request.args.get("path", "")
        if not rel_path:
            abort(400, description="Missing path parameter")

        resolved = _safe_resolve(ws.root, rel_path)
        if not resolved.is_file():
            abort(400, description="Not a regular file")

        mime, _ = mimetypes.guess_type(str(resolved))
        if mime is None:
            mime = "application/octet-stream"

        # For text files, read and return as text
        text_types = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml",
                      ".py", ".sh", ".tex", ".bib", ".csv", ".log", ".marker"}
        if resolved.suffix.lower() in text_types:
            try:
                content = resolved.read_text(encoding="utf-8")
                return app.response_class(content, mimetype=f"{mime}; charset=utf-8")
            except UnicodeDecodeError:
                pass

        return send_file(resolved, mimetype=mime)

    @app.route("/api/projects/<project_name>/iterations")
    def list_iterations(project_name: str):
        """List available iterations for a project."""
        ws = _get_workspace(project_name)
        iterations = []
        for d in sorted(ws.root.iterdir()):
            if d.is_dir() and d.name.startswith("iter_"):
                try:
                    num = int(d.name.split("_")[1])
                    iterations.append({
                        "number": num,
                        "dir": d.name,
                        "is_current": d.resolve() == ws.active_root.resolve(),
                    })
                except (ValueError, IndexError):
                    continue
        # Also check if current symlink exists
        current_link = ws.root / "current"
        has_iteration_dirs = current_link.exists() or len(iterations) > 0
        return jsonify({
            "iterations": iterations,
            "iteration_dirs": has_iteration_dirs,
            "current_iteration": ws.get_status().iteration,
        })

    @app.route("/api/projects/<project_name>/outputs")
    def project_outputs(project_name: str):
        """Return research outputs (idea proposals + papers) per iteration."""
        ws = _get_workspace(project_name)
        iterations = []

        for d in sorted(ws.root.iterdir()):
            if not d.is_dir() or not d.name.startswith("iter_"):
                continue
            try:
                num = int(d.name.split("_")[1])
            except (ValueError, IndexError):
                continue

            entry = {"number": num, "dir": d.name}

            # Find idea file (prefer final_proposal.md)
            for name in ("final_proposal.md", "proposal.md"):
                p = d / "idea" / name
                if p.is_file():
                    entry["idea"] = {"path": f"{d.name}/idea/{name}", "name": name}
                    break

            # Find paper markdown
            paper_md = d / "writing" / "paper.md"
            if paper_md.is_file():
                entry["paper_md"] = {
                    "path": f"{d.name}/writing/paper.md", "name": "paper.md",
                }

            # Find paper PDF
            latex_dir = d / "writing" / "latex"
            if latex_dir.is_dir():
                for f in sorted(latex_dir.iterdir()):
                    if f.suffix.lower() == ".pdf" and f.is_file():
                        entry["paper_pdf"] = {
                            "path": f"{d.name}/writing/latex/{f.name}",
                            "name": f.name,
                        }
                        break

            iterations.append(entry)

        # Also check root-level files for non-iteration-dirs projects
        root = {}
        for name in ("final_proposal.md", "proposal.md"):
            p = ws.root / "idea" / name
            if p.is_file():
                root["idea"] = {"path": f"idea/{name}", "name": name}
                break
        paper_md = ws.root / "writing" / "paper.md"
        if paper_md.is_file():
            root["paper_md"] = {"path": "writing/paper.md", "name": "paper.md"}

        return jsonify({
            "iterations": sorted(
                iterations, key=lambda x: x["number"], reverse=True),
            "root": root,
        })

    # ── Error handlers ─────────────────────────────────────────────

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def handle_error(e):
        return jsonify(error=str(e.description if hasattr(e, 'description') else e)), \
            e.code if hasattr(e, 'code') else 500

    return app


def run(port: int = 7654, host: str = "127.0.0.1",
        config: Config | None = None, production: bool = False):
    """Start the dashboard server."""
    app = create_app(config)
    ws_dir = (config or Config()).workspaces_dir.resolve()
    print(f"\n  Sibyl Dashboard running at http://{host}:{port}")
    print(f"  Serving workspaces from: {ws_dir}")
    print("  Press Ctrl+C to stop.\n")

    if production:
        import gunicorn.app.base

        class StandaloneApp(gunicorn.app.base.BaseApplication):
            def __init__(self, flask_app, options=None):
                self.flask_app = flask_app
                self.options = options or {}
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    if key in self.cfg.settings and value is not None:
                        self.cfg.set(key.lower(), value)

            def load(self):
                return self.flask_app

        StandaloneApp(app, {
            "bind": f"{host}:{port}",
            "workers": 2,
            "accesslog": "-",
        }).run()
    else:
        app.run(host=host, port=port, debug=False)
