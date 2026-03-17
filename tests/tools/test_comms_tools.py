"""
tests/tools/test_comms_tools.py

Tests for matrixmouse.tools.comms_tools — request_clarification.

The grace period polling loop uses time.sleep internally. All tests
mock time.sleep and control task status transitions via the queue mock
so the test suite runs instantly.

Coverage:
    configure:
        - Sets _config module-level variable

    request_clarification:
        - Returns error when question is empty
        - Returns error when question is whitespace
        - Marks task BLOCKED_BY_HUMAN
        - Sends ntfy notification
        - Emits clarification_requested event
        - Returns answer when task unblocked within grace period
        - Returns blocked message when grace period expires
        - Grace period length driven by config
        - Falls back to 10 minute default when config absent
        - Handles missing queue gracefully
        - Handles missing active_task_id gracefully

    _extract_latest_answer:
        - Returns last user message content
        - Skips operator-prefixed messages
        - Returns None when no user messages present
"""

from unittest.mock import MagicMock, patch, call
import pytest

from matrixmouse.tools import comms_tools, task_tools
from matrixmouse.task import AgentRole, Task, TaskQueue, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(**kwargs) -> Task:
    defaults = dict(
        title="Test task",
        description="desc",
        role=AgentRole.CODER,
        repo=["repo"],
    )
    defaults.update(kwargs)
    return Task(**defaults)


def make_config(grace_minutes=0.0) -> MagicMock:
    """Grace period of 0 means the polling loop exits immediately."""
    cfg = MagicMock()
    cfg.clarification_grace_period_minutes = grace_minutes
    return cfg


def setup(tmp_path, task=None, grace_minutes=0.0):
    """Wire up task_tools and comms_tools with a fresh queue."""
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("[]")
    q = TaskQueue(tasks_file)
    if task:
        q.add(task)

    cfg = make_config(grace_minutes)
    task_tools.configure(
        queue=q,
        active_task_id=task.id if task else None,
        config=cfg,
    )
    comms_tools.configure(cfg)
    return q


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_sets_config(self, tmp_path):
        cfg = make_config()
        comms_tools.configure(cfg)
        assert comms_tools._config is cfg

    def test_config_none_by_default_after_reset(self, tmp_path):
        comms_tools._config = None
        assert comms_tools._config is None


# ---------------------------------------------------------------------------
# request_clarification — input validation
# ---------------------------------------------------------------------------

class TestRequestClarificationValidation:
    def test_empty_question_returns_error(self, tmp_path):
        task = make_task()
        setup(tmp_path, task=task)
        result = comms_tools.request_clarification("")
        assert "ERROR" in result

    def test_whitespace_question_returns_error(self, tmp_path):
        task = make_task()
        setup(tmp_path, task=task)
        result = comms_tools.request_clarification("   ")
        assert "ERROR" in result

    def test_missing_queue_returns_error(self, tmp_path):
        task_tools._queue = None
        task_tools._active_task_id = None
        result = comms_tools.request_clarification("What should I do?")
        assert "ERROR" in result

    def test_missing_active_task_id_returns_error(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")
        q = TaskQueue(tasks_file)
        task_tools.configure(queue=q, active_task_id=None)
        comms_tools.configure(make_config())
        result = comms_tools.request_clarification("What should I do?")
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# request_clarification — task state changes
# ---------------------------------------------------------------------------

class TestRequestClarificationTaskState:
    def test_marks_task_blocked_by_human(self, tmp_path):
        task = make_task()
        q = setup(tmp_path, task=task, grace_minutes=0.0)
        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            comms_tools.request_clarification("What should I do?")
        assert q.get(task.id).status == TaskStatus.BLOCKED_BY_HUMAN

    def test_blocked_reason_contains_question(self, tmp_path):
        task = make_task()
        q = setup(tmp_path, task=task, grace_minutes=0.0)
        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            comms_tools.request_clarification("Which approach is better?")
        notes = q.get(task.id).notes
        assert "Which approach is better?" in notes or \
               "clarification" in notes.lower()


# ---------------------------------------------------------------------------
# request_clarification — notifications
# ---------------------------------------------------------------------------

class TestRequestClarificationNotifications:
    def test_sends_ntfy_notification(self, tmp_path):
        task = make_task()
        setup(tmp_path, task=task, grace_minutes=0.0)
        mock_comms = MagicMock()
        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            comms_tools.request_clarification("What next?")
        mock_comms.notify.assert_called_once()
        notify_args = mock_comms.notify.call_args[0][0]
        assert "What next?" in notify_args or task.id in notify_args

    def test_emits_clarification_requested_event(self, tmp_path):
        task = make_task()
        setup(tmp_path, task=task, grace_minutes=0.0)
        mock_comms = MagicMock()
        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            comms_tools.request_clarification("Which module?")
        emitted_types = [c.args[0] for c in mock_comms.emit.call_args_list]
        assert "clarification_requested" in emitted_types

    def test_event_contains_task_id_and_question(self, tmp_path):
        task = make_task()
        setup(tmp_path, task=task, grace_minutes=0.0)
        mock_comms = MagicMock()
        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.comms.get_manager", return_value=mock_comms):
            comms_tools.request_clarification("Specific question here.")
        event_data = {
            c.args[0]: c.args[1]
            for c in mock_comms.emit.call_args_list
            if c.args[0] == "clarification_requested"
        }
        assert "clarification_requested" in event_data
        assert event_data["clarification_requested"]["task_id"] == task.id
        assert "Specific question here." in \
               event_data["clarification_requested"]["question"]


# ---------------------------------------------------------------------------
# request_clarification — grace period behaviour
# ---------------------------------------------------------------------------

class TestRequestClarificationGracePeriod:
    def test_returns_blocked_message_when_grace_expires(self, tmp_path):
        task = make_task()
        q = setup(tmp_path, task=task, grace_minutes=0.0)
        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            result = comms_tools.request_clarification("Hello?")
        # Grace period 0 — expires immediately, task stays blocked
        assert "BLOCKED_BY_HUMAN" in result or "grace" in result.lower() \
               or "operator" in result.lower()

    def test_returns_answer_when_task_unblocked_in_grace_period(self, tmp_path):
        task = make_task()
        q = setup(tmp_path, task=task, grace_minutes=1.0)

        # Simulate operator answering: after first sleep, task is READY
        # with an answer in context_messages
        call_count = 0

        def fake_sleep(_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Operator answers — update task status and inject message
                t = q.get(task.id)
                t.status = TaskStatus.READY
                t.context_messages.append({
                    "role": "user",
                    "content": "Use the second approach.",
                })
                q.update(t)

        with patch("matrixmouse.tools.comms_tools.time.sleep", fake_sleep), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            result = comms_tools.request_clarification("Which approach?")

        assert "Use the second approach." in result

    def test_grace_period_uses_config_value(self, tmp_path):
        """Grace period from config is used — loop runs rather than skipping."""
        task = make_task()
        q = setup(tmp_path, task=task, grace_minutes=1.0)

        import time as time_mod
        start = time_mod.monotonic()
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            # First few calls set the deadline and enter the loop
            if call_count <= 3:
                return start
            # Then jump past the 1-minute deadline
            return start + 100

        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
            patch("matrixmouse.tools.comms_tools.time.monotonic",
                fake_monotonic), \
            patch("matrixmouse.comms.get_manager", return_value=None):
            result = comms_tools.request_clarification("Test question.")

        # Task should be blocked — grace period ran and expired
        assert q.get(task.id).status == TaskStatus.BLOCKED_BY_HUMAN
        assert "ERROR" not in result

    def test_falls_back_to_10_minute_default_when_config_absent(self, tmp_path):
        task = make_task()
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")
        q = TaskQueue(tasks_file)
        q.add(task)
        task_tools.configure(queue=q, active_task_id=task.id, config=None)
        comms_tools.configure(None)  # no config

        import time as time_mod
        start = time_mod.monotonic()
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return start
            return start + 700  # past 10-minute default (600s)

        with patch("matrixmouse.tools.comms_tools.time.sleep"), \
             patch("matrixmouse.tools.comms_tools.time.monotonic",
                   fake_monotonic), \
             patch("matrixmouse.comms.get_manager", return_value=None):
            result = comms_tools.request_clarification("Hello?")

        # Should have attempted the grace period, then returned blocked message
        assert "ERROR" not in result


# ---------------------------------------------------------------------------
# _extract_latest_answer
# ---------------------------------------------------------------------------

class TestExtractLatestAnswer:
    def test_returns_last_user_message(self):
        messages = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user",      "content": "second answer"},
        ]
        result = comms_tools._extract_latest_answer(messages)
        assert result == "second answer"

    def test_skips_operator_prefixed_messages(self):
        messages = [
            {"role": "user",
             "content": "[Human operator note — please incorporate]: do x"},
            {"role": "user",
             "content": "Real answer here."},
        ]
        # Most recent non-prefixed message should be returned
        result = comms_tools._extract_latest_answer(messages)
        assert result == "Real answer here."

    def test_returns_none_when_no_user_messages(self):
        messages = [
            {"role": "system",    "content": "sys"},
            {"role": "assistant", "content": "response"},
        ]
        assert comms_tools._extract_latest_answer(messages) is None

    def test_returns_none_for_empty_list(self):
        assert comms_tools._extract_latest_answer([]) is None

    def test_returns_most_recent_when_multiple_user_messages(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "user", "content": "third"},
        ]
        assert comms_tools._extract_latest_answer(messages) == "third"