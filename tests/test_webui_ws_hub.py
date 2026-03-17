"""Tests for WebSocket connection hub."""

from unittest.mock import MagicMock

from sibyl.webui.ws_hub import WSHub


class TestWSHub:
    def test_register_and_broadcast(self):
        hub = WSHub()
        ws = MagicMock()
        hub.register("proj-a", ws)

        assert hub.client_count("proj-a") == 1

        hub.broadcast_sync("proj-a", {"type": "test", "data": "hello"})
        ws.send.assert_called_once()

    def test_unregister(self):
        hub = WSHub()
        ws = MagicMock()
        hub.register("proj-a", ws)
        hub.unregister("proj-a", ws)

        assert hub.client_count("proj-a") == 0

    def test_broadcast_to_correct_project(self):
        hub = WSHub()
        ws_a = MagicMock()
        ws_b = MagicMock()
        hub.register("proj-a", ws_a)
        hub.register("proj-b", ws_b)

        hub.broadcast_sync("proj-a", {"type": "test"})

        ws_a.send.assert_called_once()
        ws_b.send.assert_not_called()

    def test_broadcast_all(self):
        hub = WSHub()
        ws_a = MagicMock()
        ws_b = MagicMock()
        hub.register("proj-a", ws_a)
        hub.register("proj-b", ws_b)

        hub.broadcast_all_sync({"type": "system"})

        ws_a.send.assert_called_once()
        ws_b.send.assert_called_once()

    def test_broadcast_skips_dead_connections(self):
        hub = WSHub()
        ws_good = MagicMock()
        ws_dead = MagicMock()
        ws_dead.send.side_effect = Exception("closed")
        hub.register("proj-a", ws_good)
        hub.register("proj-a", ws_dead)

        hub.broadcast_sync("proj-a", {"type": "test"})

        ws_good.send.assert_called_once()
        assert hub.client_count("proj-a") == 1
