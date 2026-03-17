"""Tests for Claude conversation JSONL watcher."""

import json

import pytest

from sibyl.webui.conversation_watcher import ConversationWatcher


@pytest.fixture
def jsonl_file(tmp_path):
    file_path = tmp_path / "session.jsonl"
    file_path.write_text("", encoding="utf-8")
    return file_path


class TestConversationWatcher:
    def test_initial_read_empty(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        assert watcher.read_new_entries() == []

    def test_reads_appended_entries(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()
        entry = {
            "type": "assistant",
            "uuid": "abc-123",
            "sessionId": "sess-1",
            "timestamp": "2026-03-17T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello"}],
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }
        with open(jsonl_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

        entries = watcher.read_new_entries()

        assert len(entries) == 1
        assert entries[0]["type"] == "assistant"
        assert entries[0]["message"]["content"][0]["text"] == "Hello"

    def test_skips_non_displayable_types(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()
        lines = [
            json.dumps({
                "type": "assistant",
                "uuid": "1",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            }),
            json.dumps({"type": "file-history-snapshot", "uuid": "2", "snapshot": {}}),
            json.dumps({
                "type": "user",
                "uuid": "3",
                "message": {"role": "user", "content": [{"type": "text", "text": "bye"}]},
            }),
        ]
        with open(jsonl_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

        entries = watcher.read_new_entries()

        assert len(entries) == 2

    def test_handles_corrupt_lines(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        watcher.read_new_entries()
        with open(jsonl_file, "a", encoding="utf-8") as handle:
            handle.write("not json\n")
            handle.write(json.dumps({
                "type": "user",
                "uuid": "ok",
                "message": {"role": "user", "content": []},
            }) + "\n")

        entries = watcher.read_new_entries()

        assert len(entries) == 1

    def test_tail_loads_recent(self, jsonl_file):
        entries = []
        for index in range(20):
            entries.append(json.dumps({
                "type": "assistant" if index % 2 == 0 else "user",
                "uuid": f"msg-{index}",
                "message": {
                    "role": "assistant" if index % 2 == 0 else "user",
                    "content": [{"type": "text", "text": f"msg {index}"}],
                },
            }))
        jsonl_file.write_text("\n".join(entries) + "\n", encoding="utf-8")
        watcher = ConversationWatcher(jsonl_file)

        recent = watcher.tail(5)

        assert len(recent) == 5
        assert recent[-1]["uuid"] == "msg-19"

    def test_resets_offset_if_file_truncated(self, jsonl_file):
        watcher = ConversationWatcher(jsonl_file)
        with open(jsonl_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "assistant", "uuid": "1", "message": {"content": []}}) + "\n")
        watcher.read_new_entries()
        jsonl_file.write_text(json.dumps({"type": "assistant", "uuid": "2", "message": {"content": []}}) + "\n", encoding="utf-8")

        entries = watcher.read_new_entries()

        assert [entry["uuid"] for entry in entries] == ["2"]
