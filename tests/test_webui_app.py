"""App factory smoke tests for the WebUI."""

from sibyl.config import Config
from sibyl.webui.app import create_webui_app


def test_create_webui_app_sets_workspace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SIBYL_WEBUI_DISABLE_THREADS", "1")
    config = Config(workspaces_dir=tmp_path / "workspaces")

    app = create_webui_app(config)

    assert app.config["SIBYL_WS_DIR"] == config.workspaces_dir.resolve()
    assert "sibyl_webui" in app.extensions
