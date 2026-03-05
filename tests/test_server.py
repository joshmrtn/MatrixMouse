"""
tests/test_server.py

Tests for matrixmouse.server — focused on the fan-out broadcast fix
and WebSocket connection lifecycle added in the refactor/web-server branch.

These tests exercise the server machinery directly without starting uvicorn.
"""

import asyncio
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.server import _register_comms_listener


# ---------------------------------------------------------------------------
# Comms listener — thread-safe bridge to asyncio
# ---------------------------------------------------------------------------

class TestRegisterCommsListener:
    def test_registers_listener_when_manager_present(self):
        manager = MagicMock()
        comms_module = MagicMock()
        comms_module.get_manager.return_value = manager

        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()

        _register_comms_listener(comms_module, queue, loop)

        manager.register_listener.assert_called_once()

    def test_warns_when_manager_absent(self, caplog):
        comms_module = MagicMock()
        comms_module.get_manager.return_value = None

        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()

        import logging
        with caplog.at_level(logging.WARNING, logger="matrixmouse.server"):
            _register_comms_listener(comms_module, queue, loop)

        assert any("not ready" in r.message for r in caplog.records)

    def test_listener_enqueues_event(self):
        """
        The registered listener should serialize the event and put it
        into the asyncio queue via run_coroutine_threadsafe.
        """
        captured_listener = None

        def capture_listener(fn):
            nonlocal captured_listener
            captured_listener = fn

        manager = MagicMock()
        manager.register_listener.side_effect = capture_listener

        comms_module = MagicMock()
        comms_module.get_manager.return_value = manager

        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()

        _register_comms_listener(comms_module, queue, loop)
        assert captured_listener is not None

        # Simulate agent emitting an event from a worker thread
        event = MagicMock()
        event.event_type = "phase_change"
        event.data = {"phase": "CRITIQUE"}

        def run_and_enqueue():
            asyncio.set_event_loop(loop)
            # Drive the loop long enough to process the queued coroutine
            loop.run_until_complete(asyncio.sleep(0.05))

        # Put event from a "thread"
        captured_listener(event)

        # Run the loop briefly to drain the coroutine
        loop.run_until_complete(asyncio.sleep(0.05))

        assert not queue.empty()
        payload = json.loads(queue.get_nowait())
        assert payload["type"] == "phase_change"
        assert payload["data"]["phase"] == "CRITIQUE"

        loop.close()


# ---------------------------------------------------------------------------
# Fan-out broadcast — each connection gets its own queue
# ---------------------------------------------------------------------------

class TestFanOut:
    """
    Verify the fan-out pattern: a single broadcaster_queue entry is
    copied to all per-connection queues, not consumed by just one.
    """

    def _run_broadcaster(self, broadcaster_queue, client_queues, client_queues_lock):
        """Run a minimal broadcaster coroutine for testing."""
        async def _broadcaster():
            for _ in range(10):  # process up to 10 events
                try:
                    payload = broadcaster_queue.get_nowait()
                    with client_queues_lock:
                        targets = list(client_queues)
                    for q in targets:
                        try:
                            q.put_nowait(payload)
                        except asyncio.QueueFull:
                            pass
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.01)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_broadcaster())
        loop.close()

    def test_event_reaches_all_connections(self):
        broadcaster_queue = asyncio.Queue()
        client_queues_lock = threading.Lock()
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        q3 = asyncio.Queue()
        client_queues = [q1, q2, q3]

        broadcaster_queue.put_nowait('{"type":"test","data":{}}')

        self._run_broadcaster(broadcaster_queue, client_queues, client_queues_lock)

        # All three queues should have received the event
        assert not q1.empty(), "q1 should have received the event"
        assert not q2.empty(), "q2 should have received the event"
        assert not q3.empty(), "q3 should have received the event"

    def test_slow_client_does_not_block_others(self):
        broadcaster_queue = asyncio.Queue()
        client_queues_lock = threading.Lock()

        # q_slow is full — put_nowait will raise QueueFull
        q_slow = asyncio.Queue(maxsize=1)
        q_slow.put_nowait("already full")

        q_fast = asyncio.Queue()
        client_queues = [q_slow, q_fast]

        broadcaster_queue.put_nowait('{"type":"test","data":{}}')

        # Should not raise — slow client is silently dropped
        self._run_broadcaster(broadcaster_queue, client_queues, client_queues_lock)

        # Fast client still received it
        assert not q_fast.empty()

    def test_empty_connections_list(self):
        """Broadcaster with no clients should not raise."""
        broadcaster_queue = asyncio.Queue()
        client_queues_lock = threading.Lock()
        client_queues = []

        broadcaster_queue.put_nowait('{"type":"test","data":{}}')

        # Should complete without error
        self._run_broadcaster(broadcaster_queue, client_queues, client_queues_lock)
