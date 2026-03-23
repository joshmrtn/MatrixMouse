"""
tests/tools/test_task_tools.py

Tests for matrixmouse.tools.task_tools — all agent-facing task tools.

Coverage:
    configure:
        - Sets queue, active_task_id, and config
        - Falls back gracefully when config is None

    declare_complete:
        - Returns a string acknowledgement

    create_task:
        - Creates a READY task in the queue
        - Returns confirmation with task ID
        - Rejects empty title
        - Rejects empty description
        - Rejects empty repo list
        - Rejects invalid role
        - Rejects manager and critic roles
        - Clamps importance and urgency to [0, 1]

    split_task:
        - Creates subtasks under parent
        - Returns confirmation with all subtask IDs
        - Parent becomes BLOCKED_BY_TASK
        - Rejects RUNNING parent
        - Rejects terminal parent
        - Rejects empty subtasks list
        - Rejects missing task_id
        - Rejects subtask with invalid role
        - Validates all subtasks before creating any (atomic)
        - Depth limit triggers PENDING_CONFIRMATION when exceeded
        - Depth limit respects decomposition_confirmed_depth

    update_task:
        - Updates title
        - Updates description
        - Updates role
        - Updates importance and urgency (clamped)
        - Appends to notes
        - Adds blocked_by dependency and sets BLOCKED_BY_TASK
        - Removes blocked_by dependency
        - Unblocks task when last dependency removed
        - Rejects cycle on add_blocked_by
        - Rejects unknown task_id
        - Returns no-change message when nothing specified

    get_task_info:
        - Returns formatted details for active task
        - Returns formatted details for specified task_id
        - Returns error when task not found
        - Returns error when no active task and no id given
        - Includes branch, role, depth in output
        - Shows blocked_by and subtasks when present

    list_tasks:
        - Returns all non-terminal tasks by default
        - Filters by status
        - Filters by repo
        - Filters by role
        - Returns sorted by priority score (ascending)
        - Returns message when no tasks match

    approve:
        - Marks reviewed task COMPLETE
        - Marks Critic task COMPLETE
        - Returns error when not called from Critic task
        - Returns error when reviews_task_id not set

    deny:
        - Returns reviewed task to READY
        - Appends feedback to reviewed task context_messages
        - Marks Critic task COMPLETE
        - Returns error when feedback is empty
        - Returns error when not called from Critic task
"""

import copy
from unittest.mock import MagicMock, patch

import pytest

from matrixmouse.task import AgentRole, Task, TaskStatus
from matrixmouse.repository.memory_task_repository import InMemoryTaskRepository
from matrixmouse.tools import task_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_repo() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


def make_task(
    title: str = "Test task",
    description: str = "Do the thing carefully.",
    role: AgentRole = AgentRole.CODER,
    repo: list[str] | None = None,
    importance=0.5,
    urgency=0.5,
    branch="mm/feature/test",
    **kwargs,
) -> Task:
    return Task(
        title=title,
        description=description,
        role=role,
        repo=repo if repo is not None else ["repo"],
        importance=importance,
        urgency=urgency,
        branch=branch,
        **kwargs,
    )


def make_config(depth_limit=3):
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.decomposition_depth_limit = depth_limit
    cfg.agent_branch_prefix = "mm"
    return cfg


def setup_tools(
    active_task=None,
    config=None,
    cwd=None,
) -> InMemoryTaskRepository:
    """Configure task_tools with a fresh repository and optional active task."""
    q = make_repo()
    if active_task is not None:
        q.add(active_task)
    task_tools.configure(
        queue=q,
        active_task_id=active_task.id if active_task else None,
        config=config or make_config(),
        cwd=cwd,
    )
    return q


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_sets_queue(self):
        q = make_repo()
        task_tools.configure(q)
        assert task_tools._queue is q

    def test_sets_active_task_id(self):
        q = make_repo()
        task_tools.configure(q, active_task_id="abc123")
        assert task_tools._active_task_id == "abc123"

    def test_sets_config(self):
        q = make_repo()
        cfg = make_config()
        task_tools.configure(q, config=cfg)
        assert task_tools._config is cfg

    def test_defaults_active_task_id_to_none(self):
        q = make_repo()
        task_tools.configure(q)
        assert task_tools._active_task_id is None

    def test_defaults_config_to_none(self):
        q = make_repo()
        task_tools.configure(q)
        assert task_tools._config is None


# ---------------------------------------------------------------------------
# declare_complete
# ---------------------------------------------------------------------------

class TestDeclareComplete:
    def test_returns_string(self):
        result = task_tools.declare_complete("all done")
        assert isinstance(result, str)

    def test_includes_summary(self):
        result = task_tools.declare_complete("finished the foo module")
        assert "finished the foo module" in result


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

class TestCreateTask:
    def test_creates_ready_task(self):
        q = setup_tools()
        task_tools.create_task(
            title="New task",
            description="Do something",
            role="coder",
            repo=["my-repo"],
        )
        tasks = q.all_tasks()
        assert len(tasks) == 1
        assert tasks[0].status == TaskStatus.READY

    def test_returns_confirmation_with_id(self):
        q = setup_tools()
        result = task_tools.create_task(
            title="New task",
            description="Do something",
            role="coder",
            repo=["my-repo"],
        )
        assert "OK" in result
        task = q.all_tasks()[0]
        assert task.id in result

    def test_rejects_empty_title(self):
        setup_tools()
        result = task_tools.create_task(
            title="   ", description="desc",
            role="coder", repo=["repo"],
        )
        assert "ERROR" in result

    def test_rejects_empty_description(self):
        setup_tools()
        result = task_tools.create_task(
            title="title", description="",
            role="coder", repo=["repo"],
        )
        assert "ERROR" in result

    def test_rejects_empty_repo(self):
        setup_tools()
        result = task_tools.create_task(
            title="title", description="desc",
            role="coder", repo=[],
        )
        assert "ERROR" in result

    def test_rejects_invalid_role(self):
        setup_tools()
        result = task_tools.create_task(
            title="title", description="desc",
            role="superagent", repo=["repo"],
        )
        assert "ERROR" in result

    def test_rejects_manager_role(self):
        setup_tools()
        result = task_tools.create_task(
            title="title", description="desc",
            role="manager", repo=["repo"],
        )
        assert "ERROR" in result

    def test_rejects_critic_role(self):
        setup_tools()
        result = task_tools.create_task(
            title="title", description="desc",
            role="critic", repo=["repo"],
        )
        assert "ERROR" in result

    def test_clamps_importance_above_one(self):
        q = setup_tools()
        task_tools.create_task(
            title="title", description="desc",
            role="coder", repo=["repo"],
            importance=5.0,
        )
        assert q.all_tasks()[0].importance == 1.0

    def test_clamps_urgency_below_zero(self):
        q = setup_tools()
        task_tools.create_task(
            title="title", description="desc",
            role="coder", repo=["repo"],
            urgency=-1.0,
        )
        assert q.all_tasks()[0].urgency == 0.0

    def test_writer_role_accepted(self):
        q = setup_tools()
        result = task_tools.create_task(
            title="Write README",
            description="Update the README",
            role="writer",
            repo=["repo"],
        )
        assert "ERROR" not in result
        assert q.all_tasks()[0].role == AgentRole.WRITER


# ---------------------------------------------------------------------------
# set_branch
# ---------------------------------------------------------------------------


class TestSetBranch:
    """
    Tests for set_branch tool.

    Note: set_branch calls git operations internally (create_branch,
    branch_exists, get_head_hash, push_to_remote). We patch these so
    tests run without a real git repo.
    """

    def _setup(self, tmp_path, branch="") -> tuple:
        task = make_task(title="parent task", branch=branch)
        q = setup_tools(active_task=task, cwd=tmp_path)
        return q, task

    def _patch_git(
        self,
        branch_exists_return=False,
        create_branch_return=(True, ""),
        get_head_return="abc123def456abcd",
        push_return=(True, ""),
        current_branch="main",
    ):
        """Return a context manager that patches all git calls in set_branch."""
        import unittest.mock as mock
        return mock.patch.multiple(
            "matrixmouse.tools.task_tools",
            branch_exists=mock.MagicMock(return_value=branch_exists_return),
            create_branch=mock.MagicMock(return_value=create_branch_return),
            get_head_hash=mock.MagicMock(return_value=get_head_return),
            push_to_remote=mock.MagicMock(return_value=push_return),
        )

    def test_returns_full_branch_name_on_success(self, tmp_path):
        q, task = self._setup(tmp_path)
        with patch("matrixmouse.tools.task_tools.branch_exists", return_value=False), \
            patch.object(q, "set_task_branch", return_value="mm/refactor/foobar"), \
            patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            result = task_tools.set_branch(task.id, "refactor/foobar")
        assert "OK" in result
        assert "mm/refactor/foobar" in result

    def test_persists_branch_to_repository(self, tmp_path):
        q, task = self._setup(tmp_path)

        def fake_set_task_branch(task_id, full_branch_name, base_branch,
                                create_git_branch, delete_git_branch):
            t = q._tasks[task_id]
            t.branch = full_branch_name
            t.wip_commit_hash = "abc123"
            return full_branch_name

        with patch("matrixmouse.tools.task_tools.branch_exists", return_value=False), \
            patch.object(q, "set_task_branch", side_effect=fake_set_task_branch), \
            patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            task_tools.set_branch(task.id, "refactor/foobar")

        updated = q.get(task.id)
        assert updated is not None
        assert updated.branch == "mm/refactor/foobar"

    def test_rejects_empty_slug(self, tmp_path):
        q, task = self._setup(tmp_path)
        result = task_tools.set_branch(task.id, "")
        assert "ERROR" in result

    
    def test_rejects_invalid_slug(self, tmp_path):
        q, task = self._setup(tmp_path)
        result = task_tools.set_branch(task.id, "Invalid Slug!")
        assert "ERROR" in result

    def test_rejects_task_with_branch_already_set(self, tmp_path):
        q, task = self._setup(tmp_path, branch="mm/already/set")
        result = task_tools.set_branch(task.id, "new/slug")
        assert "ERROR" in result
        assert "permanent" in result.lower() or "already" in result.lower()

    def test_rejects_unknown_task_id(self, tmp_path):
        setup_tools(cwd=tmp_path)
        result = task_tools.set_branch("nonexistent", "fix/foo")
        assert "ERROR" in result

    def test_returns_error_when_cwd_not_configured(self):
        q = make_repo()
        task = make_task(title="t", branch="")
        q.add(task)
        task_tools.configure(queue=q, active_task_id=task.id,
                             config=make_config(), cwd=None)
        result = task_tools.set_branch(task.id, "fix/foo")
        assert "ERROR" in result
        assert "Working directory" in result

    def test_returns_error_when_empty_task_id(self, tmp_path):
        setup_tools(cwd=tmp_path)
        result = task_tools.set_branch("", "fix/foo")
        assert "ERROR" in result

    def test_git_failure_propagates_as_error(self, tmp_path):
        q, task = self._setup(tmp_path)
        with patch.object(q, "set_task_branch",
                          side_effect=ValueError("Failed to create git branch")):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
                result = task_tools.set_branch(task.id, "fix/foo")
        assert "ERROR" in result

    def test_uses_parent_branch_as_base(self, tmp_path):
        parent = make_task(title="parent", branch="mm/refactor/foo")
        child = make_task(title="child", branch="")
        child.parent_task_id = parent.id
        q = make_repo()
        q.add(parent)
        q.add(child)
        task_tools.configure(queue=q, active_task_id=child.id,
                             config=make_config(), cwd=tmp_path)

        captured_base = []

        def fake_set_task_branch(task_id, full_branch_name, base_branch,
                                  create_git_branch, delete_git_branch):
            captured_base.append(base_branch)
            return full_branch_name

        with patch.object(q, "set_task_branch",
                          side_effect=fake_set_task_branch):
            task_tools.set_branch(child.id, "child/work")

        assert captured_base == ["mm/refactor/foo"]

    def test_full_branch_name_uses_configured_prefix(self, tmp_path):
        q, task = self._setup(tmp_path)
        cfg = make_config()
        cfg.agent_branch_prefix = "bot"
        task_tools.configure(queue=q, active_task_id=task.id,
                            config=cfg, cwd=tmp_path)

        captured_name = []

        def fake_set_task_branch(task_id, full_branch_name, base_branch,
                                create_git_branch, delete_git_branch):
            captured_name.append(full_branch_name)
            return full_branch_name

        with patch("matrixmouse.tools.task_tools.branch_exists", return_value=False), \
            patch.object(q, "set_task_branch", side_effect=fake_set_task_branch), \
            patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            task_tools.set_branch(task.id, "fix/foo")

        assert captured_name == ["bot/fix/foo"]

    def test_persists_wip_commit_hash(self, tmp_path):
        q, task = self._setup(tmp_path)
        with self._patch_git(get_head_return="deadbeef12345678"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="main\n"
                )
                task_tools.set_branch(task.id, "fix/something")
        updated = q.get(task.id)
        assert updated is not None
        assert updated.wip_commit_hash == "deadbeef12345678"

    def test_rejects_slug_when_branch_exists_in_git(self, tmp_path):
        q, task = self._setup(tmp_path)
        with patch("matrixmouse.tools.task_tools.branch_exists", return_value=True), \
            patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            result = task_tools.set_branch(task.id, "refactor/foobar")
        assert "ERROR" in result
        assert "already exists" in result

    def test_returns_error_when_git_branch_creation_fails(self, tmp_path):
        q, task = self._setup(tmp_path)
        with self._patch_git(
            create_branch_return=(False, "fatal: some git error")
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="main\n"
                )
                result = task_tools.set_branch(task.id, "fix/foo")
        assert "ERROR" in result
        assert "fatal" in result

    def test_rolls_back_git_branch_on_db_failure(self, tmp_path):
        q, task = self._setup(tmp_path)
        with patch.object(q, "set_task_branch",
                        side_effect=ValueError("DB down. Git branch rolled back.")), \
            patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
            result = task_tools.set_branch(task.id, "fix/foo")
        assert "ERROR" in result
        updated = q.get(task.id)
        assert updated is not None
        assert updated.branch == ""

    def test_mirror_push_failure_does_not_block(self, tmp_path):
        """Mirror push failure is a warning — branch is still assigned."""
        q, task = self._setup(tmp_path)
        with self._patch_git(push_return=(False, "mirror unreachable")):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="main\n"
                )
                result = task_tools.set_branch(task.id, "fix/foo")
        assert "OK" in result
        updated = q.get(task.id)
        assert updated is not None
        assert updated.branch == "mm/fix/foo"

    def test_rejects_empty_task_id(self, tmp_path):
        setup_tools(cwd=tmp_path)
        result = task_tools.set_branch("", "fix/foo")
        assert "ERROR" in result

    def test_baseline_commit_hash_in_response(self, tmp_path):
        q, task = self._setup(tmp_path)
        with self._patch_git(get_head_return="deadbeef12345678abcd"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
                result = task_tools.set_branch(task.id, "fix/foo")
        assert "deadbeef" in result  # first 8 chars of hash shown

# ---------------------------------------------------------------------------
# split_task
# ---------------------------------------------------------------------------

class TestSplitTask:
    def _subtasks(self, n=2):
        return [
            {"title": f"Subtask {i}", "description": f"Do part {i}",
             "role": "coder"}
            for i in range(n)
        ]

    def _setup_with_cwd(self, tmp_path, active_task=None):
        task = active_task or make_task(title="parent")
        q = setup_tools(active_task=task, cwd=tmp_path)
        return q, task

    def _mock_add_subtasks(self, q, created_tasks):
        """Patch add_subtasks to return created_tasks without git ops."""
        def fake_add_subtasks(parent_id, subtasks, create_git_branch,
                               delete_git_branch):
            for t in subtasks:
                t.branch = f"mm/feature/test/{t.id}"
                t.wip_commit_hash = "abc123"
                q._tasks[t.id] = copy.copy(t)
                q._blocked_by.setdefault(t.id, set())
                q._blocking.setdefault(t.id, set())
                q._blocked_by.setdefault(parent_id, set()).add(t.id)
                q._blocking.setdefault(t.id, set()).add(parent_id)
            parent = q._tasks[parent_id]
            parent.status = TaskStatus.BLOCKED_BY_TASK
            return [copy.copy(t) for t in subtasks]
        return patch.object(q, "add_subtasks", side_effect=fake_add_subtasks)

    def test_creates_subtasks_under_parent(self, tmp_path):
        q, task = self._setup_with_cwd(tmp_path)
        with self._mock_add_subtasks(q, []):
            task_tools.split_task(task.id, self._subtasks(2))
        assert len(q.all_tasks()) == 3

    def test_parent_becomes_blocked(self, tmp_path):
        q, task = self._setup_with_cwd(tmp_path)
        with self._mock_add_subtasks(q, []):
            task_tools.split_task(task.id, self._subtasks(2))
        t = q.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_TASK

    def test_subtasks_block_parent(self, tmp_path):
        q, parent = self._setup_with_cwd(tmp_path)
        with self._mock_add_subtasks(q, []):
            task_tools.split_task(parent.id, self._subtasks(2))
        assert q.has_blockers(parent.id)

    def test_returns_confirmation_with_subtask_ids(self, tmp_path):
        q, parent = self._setup_with_cwd(tmp_path)
        with self._mock_add_subtasks(q, []):
            result = task_tools.split_task(parent.id, self._subtasks(2))
        assert "OK" in result
        subtasks = [t for t in q.all_tasks() if t.id != parent.id]
        for st in subtasks:
            assert st.id in result

    def test_rejects_running_parent(self, tmp_path):
        q, parent = self._setup_with_cwd(tmp_path)
        q.mark_running(parent.id)
        with self._mock_add_subtasks(q, []):
            result = task_tools.split_task(parent.id, self._subtasks(2))
        assert "ERROR" in result
        assert "RUNNING" in result

    def test_rejects_terminal_parent(self, tmp_path):
        q, parent = self._setup_with_cwd(tmp_path)
        q.mark_complete(parent.id)
        with self._mock_add_subtasks(q, []):
            result = task_tools.split_task(parent.id, self._subtasks(2))
        assert "ERROR" in result

    def test_rejects_empty_subtasks_list(self, tmp_path):
        q, parent = self._setup_with_cwd(tmp_path)
        with self._mock_add_subtasks(q, []):
            result = task_tools.split_task(parent.id, self._subtasks(0))
        assert "ERROR" in result

    def test_rejects_missing_task_id(self, tmp_path):
        q, task = self._setup_with_cwd(tmp_path)
        with self._mock_add_subtasks(q, []):
            result = task_tools.split_task("nonexistent", self._subtasks(2))
        assert "ERROR" in result

    def test_rejects_subtask_with_invalid_role(self, tmp_path):
        q, task = self._setup_with_cwd(tmp_path)
        bad_subtasks = [{"title": "t", "description": "d", "role": "invalid"}]
        with self._mock_add_subtasks(q, []):
            result = task_tools.split_task(task.id, bad_subtasks)
        assert "ERROR" in result

    def test_validates_all_before_creating_any(self, tmp_path):
        q, parent = self._setup_with_cwd(tmp_path)
        mixed = [
            {"title": "good", "description": "fine", "role": "coder"},
            {"title": "bad",  "description": "broken", "role": "invalid"},
        ]
        with self._mock_add_subtasks(q, []):
            task_tools.split_task(parent.id, mixed)
        assert len(q.all_tasks()) == 1

    def test_depth_limit_triggers_pending_confirmation(self, tmp_path):
        parent_task = make_task(title="parent", depth=3)
        q, parent = self._setup_with_cwd(tmp_path, parent_task)
        with self._mock_add_subtasks(q, []):
            with patch.object(task_tools, "_emit_decomposition_confirmation"):
                result = task_tools.split_task(parent.id, self._subtasks())
        assert "PENDING_CONFIRMATION" in result

    def test_depth_limit_respects_confirmed_depth(self, tmp_path):
        # depth=3, confirmed_depth=1 means allowed_depth = 3 + 3 = 6
        parent = make_task(
            title="parent", depth=3,
            decomposition_confirmed_depth=1,
        )
        q = setup_tools(active_task=parent, config=make_config(depth_limit=3), cwd=tmp_path)
        with patch.object(q, "add_subtasks", return_value=[]):
            result = task_tools.split_task(parent.id, self._subtasks())
        assert "OK" in result

    def test_subtask_branches_assigned_when_parent_has_branch(self, tmp_path):
        parent = make_task(title="parent")  # branch="mm/feature/test" from make_task
        q = setup_tools(active_task=parent, cwd=tmp_path)
        with patch.object(q, "add_subtasks", return_value=[]):
            result = task_tools.split_task(parent.id, self._subtasks(2))
        assert "OK" in result
        subtasks = [t for t in q.all_tasks() if t.id != parent.id]
        for st in subtasks:
            assert st.branch.startswith("mm/feature/test/")
            assert len(st.branch.split("/")[-1]) == 16  # full task ID

    def test_subtask_branch_shown_in_result(self, tmp_path):
        parent = make_task(title="parent")
        q = setup_tools(active_task=parent, cwd=tmp_path)

        expected_branch = f"mm/feature/test/abc123def456abcd"
        fake_subtask = make_task(title="Subtask 0")
        fake_subtask.branch = expected_branch

        with patch.object(q, "add_subtasks", return_value=[fake_subtask]):
            result = task_tools.split_task(parent.id, self._subtasks(1))

        assert "OK" in result
        assert expected_branch in result

    def test_git_rollback_on_partial_branch_creation_failure(self, tmp_path):
        """If the second git branch creation fails, the first is rolled back."""
        parent = make_task(title="parent")
        q = setup_tools(active_task=parent, cwd=tmp_path)

        call_count = 0
        def mock_add_subtasks(parent_id, subtasks, create_git_branch,
                            delete_git_branch):
            nonlocal call_count
            call_count += 1
            raise ValueError("Failed to create git branch: fatal error. "
                            "All git branches rolled back.")

        with patch.object(q, "add_subtasks", side_effect=mock_add_subtasks):
            result = task_tools.split_task(parent.id, self._subtasks(2))

        assert "ERROR" in result
        # No subtasks created
        assert len([t for t in q.all_tasks() if t.id != parent.id]) == 0

    def test_rejects_when_cwd_not_configured(self):
        parent = make_task(title="parent")
        setup_tools(active_task=parent, cwd=None)
        result = task_tools.split_task(parent.id, self._subtasks())
        assert "ERROR" in result
        assert "Working directory" in result

    def test_rejects_parent_with_no_branch(self, tmp_path):
        parent = make_task(title="parent", branch="")
        q = make_repo()
        q.add(parent)
        task_tools.configure(queue=q, active_task_id=parent.id,
                            config=make_config(), cwd=tmp_path)
        result = task_tools.split_task(parent.id, self._subtasks())
        assert "ERROR" in result
        assert "branch" in result.lower()


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------

class TestUpdateTask:
    def test_updates_title(self):
        task = make_task()
        q = setup_tools(active_task=task)
        task_tools.update_task(task.id, title="New title")
        t = q.get(task.id)
        assert t is not None
        assert t.title == "New title"

    def test_updates_description(self):
        task = make_task()
        q = setup_tools(active_task=task)
        task_tools.update_task(task.id, description="New description")
        t = q.get(task.id)
        assert t is not None
        assert t.description == "New description"

    def test_updates_role(self):
        task = make_task(role=AgentRole.CODER)
        q = setup_tools(active_task=task)
        task_tools.update_task(task.id, role="writer")
        t = q.get(task.id)
        assert t is not None
        assert t.role == AgentRole.WRITER

    def test_clamps_importance(self):
        task = make_task()
        q = setup_tools(active_task=task)
        task_tools.update_task(task.id, importance=99.0)
        t = q.get(task.id)
        assert t is not None
        assert t.importance == 1.0

    def test_clamps_urgency(self):
        task = make_task()
        q = setup_tools(active_task=task)
        task_tools.update_task(task.id, urgency=-5.0)
        t = q.get(task.id)
        assert t is not None
        assert t.urgency == 0.0

    def test_appends_to_notes(self):
        task = make_task()
        task.notes = "existing note"
        q = setup_tools(active_task=task)
        task_tools.update_task(task.id, notes="new note")
        updated = q.get(task.id)
        assert updated is not None
        assert "existing note" in updated.notes
        assert "new note" in updated.notes

    def test_adds_blocked_by_dependency(self):
        task = make_task(title="main")
        blocker = make_task(title="blocker")
        q = setup_tools(active_task=task)
        q.add(blocker)
        task_tools.update_task(task.id, add_blocked_by=[blocker.id])
        assert q.has_blockers(task.id)
        blockers = q.get_blocked_by(task.id)
        assert any(b.id == blocker.id for b in blockers)

    def test_add_blocked_by_sets_blocked_status(self):
        task = make_task(title="main")
        blocker = make_task(title="blocker")
        q = setup_tools(active_task=task)
        q.add(blocker)
        task_tools.update_task(task.id, add_blocked_by=[blocker.id])
        t = q.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.BLOCKED_BY_TASK

    def test_removes_blocked_by_dependency(self):
        blocker = make_task(title="blocker")
        task = make_task(title="main")
        q = setup_tools(active_task=task)
        q.add(blocker)
        q.add_dependency(blocker.id, task.id)
        task_tools.update_task(task.id, remove_blocked_by=[blocker.id])
        assert not q.has_blockers(task.id)

    def test_unblocks_task_when_last_dependency_removed(self):
        blocker = make_task(title="blocker")
        task = make_task(title="main")
        q = setup_tools(active_task=task)
        q.add(blocker)
        q.add_dependency(blocker.id, task.id)
        task_tools.update_task(task.id, remove_blocked_by=[blocker.id])
        t = q.get(task.id)
        assert t is not None
        assert t.status == TaskStatus.READY

    def test_rejects_cycle_on_add_blocked_by(self):
        task_a = make_task(title="A")
        task_b = make_task(title="B")
        q = setup_tools(active_task=task_a)
        q.add(task_b)
        # A blocks B via add_dependency
        q.add_dependency(task_a.id, task_b.id)
        # Now try to make A blocked by B — would create a cycle
        result = task_tools.update_task(task_a.id, add_blocked_by=[task_b.id])
        assert "ERROR" in result
        assert "cycle" in result.lower()

    def test_rejects_unknown_task_id(self):
        setup_tools()
        result = task_tools.update_task("nonexistent")
        assert "ERROR" in result

    def test_returns_no_change_message_when_nothing_specified(self):
        task = make_task()
        setup_tools(active_task=task)
        result = task_tools.update_task(task.id)
        assert "No changes" in result

    def test_field_and_dependency_change_together(self):
        """Title update and add_blocked_by in same call both take effect."""
        task = make_task(title="main", branch="")
        blocker = make_task(title="blocker")
        q = setup_tools(active_task=task)
        q.add(blocker)
        task_tools.update_task(task.id, title="new title",
                            add_blocked_by=[blocker.id])
        updated = q.get(task.id)
        assert updated is not None
        assert updated.title == "new title"
        assert updated.status == TaskStatus.BLOCKED_BY_TASK


# ---------------------------------------------------------------------------
# get_task_info
# ---------------------------------------------------------------------------

class TestGetTaskInfo:
    def test_returns_info_for_active_task(self):
        task = make_task(title="Active task")
        setup_tools(active_task=task)
        result = task_tools.get_task_info()
        assert "Active task" in result

    def test_returns_info_for_specified_task_id(self):
        task = make_task(title="Specific task")
        q = setup_tools()
        q.add(task)
        result = task_tools.get_task_info(task_id=task.id)
        assert "Specific task" in result

    def test_returns_error_when_task_not_found(self):
        setup_tools()
        result = task_tools.get_task_info(task_id="nonexistent")
        assert "ERROR" in result

    def test_returns_error_when_no_active_task_and_no_id(self):
        setup_tools()
        result = task_tools.get_task_info()
        assert "ERROR" in result

    def test_output_includes_role(self):
        task = make_task(role=AgentRole.WRITER)
        setup_tools(active_task=task)
        result = task_tools.get_task_info()
        assert "writer" in result.lower()

    def test_output_includes_branch_when_set(self):
        task = make_task()
        task.branch = "feature/my-branch"
        setup_tools(active_task=task)
        result = task_tools.get_task_info()
        assert "feature/my-branch" in result

    def test_output_includes_depth(self):
        task = make_task(depth=2)
        setup_tools(active_task=task)
        result = task_tools.get_task_info()
        assert "2" in result

    def test_output_includes_blocked_by_when_present(self):
        blocker = make_task(title="blocker")
        task = make_task(title="blocked")
        q = setup_tools(active_task=task)
        q.add(blocker)
        q.add_dependency(blocker.id, task.id)
        result = task_tools.get_task_info(task_id=task.id)
        assert blocker.id in result

    def test_output_includes_subtasks_when_present(self, tmp_path):
        parent = make_task(title="parent")
        q = setup_tools(active_task=parent, cwd=tmp_path)

        # Create a subtask directly so get_task_info can find it
        subtask = make_task(title="child")
        subtask.branch = f"mm/feature/test/{subtask.id}"
        subtask.parent_task_id = parent.id
        subtask.depth = 1
        q.add(subtask)
        q._blocked_by.setdefault(parent.id, set()).add(subtask.id)
        q._blocking.setdefault(subtask.id, set()).add(parent.id)

        result = task_tools.get_task_info(task_id=parent.id)
        assert subtask.id in result


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------

class TestListTasks:
    def test_returns_non_terminal_tasks_by_default(self):
        q = setup_tools()
        q.add(make_task(title="ready task"))
        q.add(make_task(title="done task", status=TaskStatus.COMPLETE))
        result = task_tools.list_tasks()
        assert "ready task" in result
        assert "done task" not in result

    def test_filters_by_status(self):
        q = setup_tools()
        q.add(make_task(title="ready"))
        blocked = make_task(title="blocked")
        q.add(blocked)
        q.mark_blocked_by_human(blocked.id, "needs input")
        result = task_tools.list_tasks(status="blocked_by_human")
        assert "blocked" in result
        assert "ready" not in result

    def test_filters_by_repo(self):
        q = setup_tools()
        q.add(make_task(title="in repo A", repo=["repo-a"]))
        q.add(make_task(title="in repo B", repo=["repo-b"]))
        result = task_tools.list_tasks(repo="repo-a")
        assert "in repo A" in result
        assert "in repo B" not in result

    def test_filters_by_role(self):
        q = setup_tools()
        q.add(make_task(title="coder task", role=AgentRole.CODER))
        q.add(make_task(title="writer task", role=AgentRole.WRITER))
        result = task_tools.list_tasks(role="writer")
        assert "writer task" in result
        assert "coder task" not in result

    def test_returns_message_when_no_tasks_match(self):
        setup_tools()
        result = task_tools.list_tasks(repo="nonexistent-repo")
        assert "No tasks" in result

    def test_invalid_status_returns_error(self):
        setup_tools()
        result = task_tools.list_tasks(status="flying")
        assert "ERROR" in result

    def test_invalid_role_returns_error(self):
        setup_tools()
        result = task_tools.list_tasks(role="overlord")
        assert "ERROR" in result

    def test_sorted_by_priority_ascending(self):
        q = setup_tools()
        high = make_task(title="high priority", importance=1.0, urgency=1.0)
        low  = make_task(title="low priority",  importance=0.0, urgency=0.0)
        q.add(low)
        q.add(high)
        result = task_tools.list_tasks()
        assert result.index("high priority") < result.index("low priority")


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

class TestApprove:
    def _setup_critic_review(self):
        reviewed = make_task(title="reviewed task", role=AgentRole.CODER)
        critic = make_task(title="critic task", role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id

        q = make_repo()
        q.add(reviewed)
        q.add(critic)
        q.add_dependency(critic.id, reviewed.id)
        task_tools.configure(queue=q, active_task_id=critic.id,
                             config=make_config())
        return q, reviewed, critic

    def test_approve_marks_reviewed_task_complete(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.approve()
        t = q.get(reviewed.id)
        assert t is not None
        assert t.status == TaskStatus.COMPLETE

    def test_approve_marks_critic_task_complete(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.approve()
        t = q.get(critic.id)
        assert t is not None
        assert t.status == TaskStatus.COMPLETE

    def test_approve_removes_dependency(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.approve()
        assert not q.has_blockers(reviewed.id)

    def test_approve_returns_ok(self):
        q, reviewed, critic = self._setup_critic_review()
        result = task_tools.approve()
        assert "OK" in result

    def test_approve_returns_error_when_no_active_task(self):
        q = make_repo()
        task_tools.configure(queue=q, active_task_id=None)
        result = task_tools.approve()
        assert "ERROR" in result

    def test_approve_returns_error_when_no_reviews_task_id(self):
        task = make_task(role=AgentRole.CRITIC)
        setup_tools(active_task=task)
        result = task_tools.approve()
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# deny
# ---------------------------------------------------------------------------

class TestDeny:
    def _setup_critic_review(self):
        reviewed = make_task(title="reviewed task", role=AgentRole.CODER)
        critic = make_task(title="critic task", role=AgentRole.CRITIC)
        critic.reviews_task_id = reviewed.id

        q = make_repo()
        q.add(reviewed)
        q.add(critic)
        q.add_dependency(critic.id, reviewed.id)
        task_tools.configure(queue=q, active_task_id=critic.id,
                             config=make_config())
        return q, reviewed, critic

    def test_deny_returns_reviewed_task_to_ready(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.deny("The tests are missing.")
        t = q.get(reviewed.id)
        assert t is not None
        assert t.status == TaskStatus.READY

    def test_deny_appends_feedback_to_context_messages(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.deny("Missing error handling in foo().")
        t = q.get(reviewed.id)
        assert t is not None
        messages = t.context_messages
        assert any(
            "Missing error handling in foo()." in m.get("content", "")
            for m in messages
        )

    def test_deny_marks_critic_task_complete(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.deny("Needs more tests.")
        t = q.get(critic.id)
        assert t is not None
        assert t.status == TaskStatus.COMPLETE

    def test_deny_returns_ok(self):
        q, reviewed, critic = self._setup_critic_review()
        result = task_tools.deny("Not done yet.")
        assert "OK" in result

    def test_deny_returns_error_for_empty_feedback(self):
        q, reviewed, critic = self._setup_critic_review()
        result = task_tools.deny("")
        assert "ERROR" in result

    def test_deny_returns_error_for_whitespace_feedback(self):
        q, reviewed, critic = self._setup_critic_review()
        result = task_tools.deny("   ")
        assert "ERROR" in result

    def test_deny_returns_error_when_no_active_task(self):
        q = make_repo()
        task_tools.configure(queue=q, active_task_id=None)
        result = task_tools.deny("feedback")
        assert "ERROR" in result

    def test_deny_returns_error_when_no_reviews_task_id(self):
        task = make_task(role=AgentRole.CRITIC)
        setup_tools(active_task=task)
        result = task_tools.deny("feedback")
        assert "ERROR" in result

    def test_deny_feedback_survives_refetch(self):
        q, reviewed, critic = self._setup_critic_review()
        task_tools.deny("Specific feedback that must survive.")
        updated = q.get(reviewed.id)
        assert updated is not None
        assert any(
            "Specific feedback that must survive." in m.get("content", "")
            for m in updated.context_messages
        )
        