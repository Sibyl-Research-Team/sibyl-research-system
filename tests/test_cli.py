"""Tests for the Sibyl CLI entrypoint."""

import pytest

import sibyl.cli as cli


class ExecveCalled(RuntimeError):
    """Sentinel exception for intercepted os.execve calls."""

    def __init__(self, executable: str, argv: list[str], env: dict[str, str]):
        super().__init__(executable)
        self.executable = executable
        self.argv = argv
        self.env = env


class TestEnsureRepoVenvPython:
    def test_noop_when_already_in_repo_venv(self, tmp_path, monkeypatch):
        repo_venv = tmp_path / ".venv"
        target_python = repo_venv / "bin" / "python"
        target_python.parent.mkdir(parents=True)
        target_python.write_text("", encoding="utf-8")

        monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cli.sys, "prefix", str(repo_venv))

        exec_calls = []
        monkeypatch.setattr(
            cli.os,
            "execve",
            lambda executable, argv, env: exec_calls.append((executable, argv, env)),
        )

        cli.ensure_repo_venv_python()

        assert exec_calls == []

    def test_reexecs_into_repo_venv_python(self, tmp_path, monkeypatch):
        repo_venv = tmp_path / ".venv"
        target_python = repo_venv / "bin" / "python"
        target_python.parent.mkdir(parents=True)
        target_python.write_text("", encoding="utf-8")

        monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cli.sys, "prefix", "/usr/local")
        monkeypatch.setattr(cli.sys, "argv", ["sibyl", "status", "demo"])

        def fake_execve(executable, argv, env):
            raise ExecveCalled(executable, argv, env)

        monkeypatch.setattr(cli.os, "execve", fake_execve)

        with pytest.raises(ExecveCalled) as exc_info:
            cli.ensure_repo_venv_python()

        assert exc_info.value.executable == str(target_python)
        assert exc_info.value.argv == [
            str(target_python),
            "-m",
            "sibyl.cli",
            "status",
            "demo",
        ]
        assert exc_info.value.env[cli._REEXEC_ENV_VAR] == "1"

    def test_raises_clear_error_when_repo_venv_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cli.sys, "prefix", "/usr/local")

        with pytest.raises(SystemExit, match="repo virtualenv"):
            cli.ensure_repo_venv_python()

    def test_raises_if_reexec_still_not_in_repo_venv(self, tmp_path, monkeypatch):
        repo_venv = tmp_path / ".venv"
        target_python = repo_venv / "bin" / "python"
        target_python.parent.mkdir(parents=True)
        target_python.write_text("", encoding="utf-8")

        monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cli.sys, "prefix", "/usr/local")
        monkeypatch.setenv(cli._REEXEC_ENV_VAR, "1")

        with pytest.raises(SystemExit, match="did not take effect"):
            cli.ensure_repo_venv_python()


class MainCalled(RuntimeError):
    """Sentinel exception for verifying main() bootstrapping."""


class TestMain:
    def test_main_enforces_repo_venv_before_cli_logic(self, monkeypatch):
        monkeypatch.setattr(cli.sys, "argv", ["sibyl", "status"])

        def fail_fast():
            raise MainCalled()

        monkeypatch.setattr(cli, "ensure_repo_venv_python", fail_fast)

        with pytest.raises(MainCalled):
            cli.main()
