"""Tests for message injection via tmux."""

from unittest.mock import MagicMock, patch

from sibyl.webui.message_injector import MessageInjector, sanitize_for_tmux


class TestSanitize:
    def test_strips_shell_metacharacters(self):
        assert sanitize_for_tmux("hello; rm -rf /") == "hello rm -rf /"

    def test_allows_slash_commands(self):
        assert sanitize_for_tmux("/sibyl-research:stop proj-a") == "/sibyl-research:stop proj-a"

    def test_strips_backticks_and_quotes(self):
        result = sanitize_for_tmux("""run `ls` and say "hi" it's ok""")
        assert "`" not in result
        assert '"' not in result
        assert "'" not in result

    def test_strips_newlines_and_escape_chars(self):
        result = sanitize_for_tmux("line1\nline2\x1b[31m")
        assert "\n" not in result
        assert "\x1b" not in result

    def test_allows_chinese(self):
        message = "请考虑 pivot 到 positional encoding"
        assert sanitize_for_tmux(message) == message


class TestMessageInjector:
    @patch("sibyl.webui.message_injector.subprocess")
    def test_send_to_tmux(self, mock_subprocess):
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        result = MessageInjector().send("sibyl:0.0", "hello world")

        assert result["ok"] is True
        command = mock_subprocess.run.call_args[0][0]
        assert command[0] == "tmux"
        assert "send-keys" in command

    @patch("sibyl.webui.message_injector.subprocess")
    def test_send_fails_gracefully(self, mock_subprocess):
        mock_subprocess.run.return_value = MagicMock(returncode=1, stderr="no pane")

        result = MessageInjector().send("bad:0.0", "hello")

        assert result["ok"] is False
        assert "error" in result

    def test_empty_after_sanitize(self):
        result = MessageInjector().send("s:0.0", "$()")
        assert result["ok"] is False
