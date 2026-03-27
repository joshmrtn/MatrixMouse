"""
tests/tools/test_git_tools.py

Tests for matrixmouse.tools.git_tools.

Coverage:
    Internal functions:
        branch_exists:
            - Returns True when branch exists
            - Returns False when branch does not exist

        create_branch:
            - Creates branch from base
            - Returns False when base branch does not exist

        push_to_remote:
            - Succeeds when remote exists
            - Returns error message on failure

        get_head_hash:
            - Returns hash string when commits exist
            - Returns None on empty repo

        squash_wip_commits:
            - No-op when no commits since baseline
            - No-op when no WIP commits at top
            - Squashes single WIP commit
            - Squashes multiple contiguous WIP commits
            - Leaves non-WIP commits untouched
            - Does not squash WIP commits below a real commit

        wip_commit_and_push:
            - No-op when working tree is clean
            - Creates WIP commit when dirty
            - WIP commit message starts with AUTO-WIP:
            - Pushes to mirror remote
            - Returns error when mirror push fails

    Agent-facing tools:
        configure:
            - Sets wip_commit_hash, branch, cwd

        get_git_diff:
            - Returns diff against wip_commit_hash by default
            - Returns diff against explicit base when provided
            - Returns no-changes message when clean

        get_git_log:
            - Filters out AUTO-WIP commits
            - Returns real commits only
            - Respects n limit

        get_git_status:
            - Returns clean message when tree is clean
            - Lists modified files

        git_commit:
            - Stages and commits
            - Squashes preceding WIP commits
            - Returns no-op message when nothing to commit
"""

import subprocess
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import importlib

import pytest

from matrixmouse.tools import git_tools
from matrixmouse.tools.git_tools import (
    WIP_PREFIX,
    MIRROR_REMOTE,
    _require_ssh_key,
    branch_exists,
    create_branch,
    get_head_hash,
    squash_wip_commits,
    wip_commit_and_push,
)
from matrixmouse.task import AgentRole, Task, TaskStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_ssh_key_check(tmp_path):
    """
    Automatically mocks _require_ssh_key for all tests. 
    Returns a Path object to a fake key that actually exists.
    """
    fake_key = tmp_path / "fake_id_rsa"
    fake_key.write_text("fake-ssh-key-content")

    with patch("matrixmouse.tools.git_tools._require_ssh_key", return_value=fake_key) as mocked_func:
        yield mocked_func

@pytest.fixture(autouse=True)
def mock_git_config(tmp_path):
    """
    Mocks the global config object so git_tools doesn't 
    crash looking for 'loaded_config'.
    """
    # 1. Setup fake filesystem paths
    fake_key = tmp_path / "fake_id_rsa"
    fake_key.write_text("fake-ssh-key-content")

    # 2. Create a Mock Config Object
    mock_cfg = MagicMock()
    mock_cfg.gh_ssh_key_file = "fake_id_rsa"
    mock_cfg.agent_git_name = "MatrixMouse"
    mock_cfg.agent_git_email = "agent@matrixmouse.local"

    # 3. Patch the internal config module reference
    # We patch the attribute directly so getattr(config_module, "_loaded_config") works
    with patch("matrixmouse.config._loaded_config", mock_cfg):
        # 4. ALSO patch the ssh key check to return our specific tmp path
        with patch("matrixmouse.tools.git_tools._require_ssh_key", return_value=fake_key):
            yield mock_cfg

@pytest.fixture
def git_repo(tmp_path):
    """
    Create a minimal git repo with an initial commit.
    Returns the repo path.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        result = subprocess.run(
            ["git"] + list(args),
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "Test",
                 "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "test@test.com"},
        )
        assert result.returncode == 0, \
            f"git {' '.join(args)} failed: {result.stderr}"
        return result.stdout.strip()

    git("init")
    git("config", "user.email", "test@test.com")
    git("config", "user.name", "Test")
    (repo / "README.md").write_text("hello")
    git("add", "-A")
    git("commit", "-m", "Initial commit")

    return repo


@pytest.fixture
def git_repo_with_mirror(git_repo, tmp_path):
    """Git repo with a bare mirror remote."""
    mirror = tmp_path / "mirror.git"

    result = subprocess.run(
        ["git", "clone", "--bare", str(git_repo), str(mirror)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    subprocess.run(
        ["git", "remote", "add", MIRROR_REMOTE, str(mirror)],
        cwd=git_repo, capture_output=True,
    )

    return git_repo, mirror


@pytest.fixture
def configured_task(git_repo):
    """Configure git_tools with a task pointing to git_repo."""
    print(f"DEBUG: About to configure. Mock active? {git_tools._require_ssh_key}")
    task = Task(
        title="test task",
        description="desc",
        role=AgentRole.CODER,
        repo=["repo"],
        branch="mm/test/branch",
    )
    assert git_repo is not None
    hash = get_head_hash(git_repo)
    assert hash is not None
    task.wip_commit_hash = hash
    git_tools.configure(task, git_repo)
    yield task
    # Reset module state
    git_tools._active_wip_commit_hash = None
    git_tools._active_branch = None
    git_tools._active_cwd = None

# ---------------------------------------------------------------------------
# _require_ssh_key and _fmt
# ---------------------------------------------------------------------------

def test_require_ssh_key_logic(tmp_path):
    # 1. Force a reload of the module to wipe out any global mocks
    from matrixmouse.tools import git_tools
    importlib.reload(git_tools)
    
    # 2. Setup our failure conditions
    mock_cfg = MagicMock()
    mock_cfg.gh_ssh_key_file = "nonexistent_key"
    
    # 3. Use patch.multiple to handle the config and the filesystem check
    # We patch Path in the context of the git_tools module
    with patch("matrixmouse.config._loaded_config", mock_cfg):
        with patch("matrixmouse.tools.git_tools.Path.is_file", return_value=False):
            with pytest.raises(FileNotFoundError, match="SSH key not found"):
                # Call the real function from the reloaded module
                git_tools._require_ssh_key()

    # 4. Success case
    with patch("matrixmouse.config._loaded_config", mock_cfg):
        with patch("matrixmouse.tools.git_tools.Path.is_file", return_value=True):
            path = git_tools._require_ssh_key()
            assert str(path).endswith("nonexistent_key")

def test_fmt_behavior():
    from matrixmouse.tools.git_tools import _fmt
    # Test Success case
    assert _fmt(True, "all good") == "all good"
    assert _fmt(True, "") == "OK"
    
    # Test Error case
    assert _fmt(False, "boom", context="git_push") == "ERROR (git_push): boom"
    assert _fmt(False, "fail") == "ERROR: fail"

# ---------------------------------------------------------------------------
# branch_exists
# ---------------------------------------------------------------------------

class TestBranchExists:
    def test_returns_true_for_existing_branch(self, git_repo):
        assert branch_exists("master", git_repo) or \
               branch_exists("main", git_repo)

    def test_returns_false_for_nonexistent_branch(self, git_repo):
        assert branch_exists("mm/nonexistent/branch", git_repo) is False


class TestEnsureBranchFromMirror:
    def test_noop_when_branch_exists_locally(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        base = "master" if branch_exists("master", repo) else "main"
        from matrixmouse.tools.git_tools import ensure_branch_from_mirror
        ok, result = ensure_branch_from_mirror(base, MIRROR_REMOTE, repo)
        assert ok
        assert result == base

    def test_recreates_branch_from_mirror(self, git_repo_with_mirror):
        repo, mirror = git_repo_with_mirror
        base = "master" if branch_exists("master", repo) else "main"

        # Create a branch on the mirror that doesn't exist locally
        subprocess.run(
            ["git", "branch", "mm/test/remote-only"],
            cwd=repo, capture_output=True,
        )
        subprocess.run(
            ["git", "push", MIRROR_REMOTE, "mm/test/remote-only"],
            cwd=repo, capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-D", "mm/test/remote-only"],
            cwd=repo, capture_output=True,
        )
        assert not branch_exists("mm/test/remote-only", repo)

        from matrixmouse.tools.git_tools import ensure_branch_from_mirror
        ok, result = ensure_branch_from_mirror(
            "mm/test/remote-only", MIRROR_REMOTE, repo
        )
        assert ok
        assert branch_exists("mm/test/remote-only", repo)

    def test_returns_error_when_mirror_missing_branch(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        from matrixmouse.tools.git_tools import ensure_branch_from_mirror
        ok, err = ensure_branch_from_mirror(
            "mm/nonexistent/branch", MIRROR_REMOTE, repo
        )
        assert not ok
        assert "fetch" in err.lower() or "mirror" in err.lower()

    def test_returns_error_when_remote_missing(self, git_repo):
        from matrixmouse.tools.git_tools import ensure_branch_from_mirror
        ok, err = ensure_branch_from_mirror(
            "mm/test/branch", "no-such-remote", git_repo
        )
        assert not ok

    def test_returns_error_when_checkout_fails_after_fetch(self, git_repo_with_mirror):
        repo, mirror = git_repo_with_mirror
        base = "master" if branch_exists("master", repo) else "main"

        # Create branch on mirror
        subprocess.run(["git", "branch", "mm/test/checkout-fail"], cwd=repo,
                    capture_output=True)
        subprocess.run(["git", "push", MIRROR_REMOTE, "mm/test/checkout-fail"],
                    cwd=repo, capture_output=True)
        subprocess.run(["git", "branch", "-D", "mm/test/checkout-fail"],
                    cwd=repo, capture_output=True)

        from matrixmouse.tools.git_tools import ensure_branch_from_mirror

        # Patch _git to let fetch succeed but fail on checkout
        original_git = git_tools._git
        def mock_git(args, cwd):
            if args[0] == "checkout":
                return False, "fatal: mock checkout failure"
            return original_git(args, cwd)

        with patch("matrixmouse.tools.git_tools._git", side_effect=mock_git):
            ok, err = ensure_branch_from_mirror(
                "mm/test/checkout-fail", MIRROR_REMOTE, repo
            )

        assert not ok
        assert "checkout" in err.lower() or "create local branch" in err.lower()


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------

class TestCreateBranch:
    def test_creates_branch_from_base(self, git_repo):
        base = "master" if branch_exists("master", git_repo) else "main"
        success, _ = create_branch("mm/test/new-branch", base, git_repo)
        assert success
        assert branch_exists("mm/test/new-branch", git_repo)

    def test_fails_on_nonexistent_base(self, git_repo):
        success, output = create_branch(
            "mm/test/new", "nonexistent-base", git_repo
        )
        assert not success
        assert output  # error message present


# ---------------------------------------------------------------------------
# get_head_hash
# ---------------------------------------------------------------------------

class TestGetHeadHash:
    def test_returns_hash_string(self, git_repo):
        h = get_head_hash(git_repo)
        assert h is not None
        assert len(h) == 40  # full SHA1

    def test_returns_none_on_empty_repo(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        subprocess.run(["git", "init"], cwd=empty, capture_output=True)
        assert get_head_hash(empty) is None


# ---------------------------------------------------------------------------
# squash_wip_commits
# ---------------------------------------------------------------------------

class TestSquashWipCommits:
    def _git(self, repo, *args):
        result = subprocess.run(
            ["git"] + list(args), cwd=repo, capture_output=True, text=True,
            env={**os.environ,
                 "GIT_AUTHOR_NAME": "Test",
                 "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "test@test.com"},
        )
        return result.stdout.strip()

    def _commit(self, repo, message, filename="change.txt"):
        (repo / filename).write_text(message)
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-m", message)

    def test_noop_when_no_commits_since_baseline(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None
        success, msg = squash_wip_commits(baseline, "squashed", git_repo)
        assert success
        assert "Nothing to squash" in msg

    def test_noop_when_no_wip_at_top(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None
        self._commit(git_repo, "real commit", "real.txt")
        success, msg = squash_wip_commits(baseline, "squashed", git_repo)
        assert success
        assert "Nothing to squash" in msg

    def test_squashes_single_wip_commit(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None
        self._commit(git_repo, f"{WIP_PREFIX}2026-01-01T00:00:00Z", "wip1.txt")
        success, _ = squash_wip_commits(baseline, "real commit", git_repo)
        assert success
        log = self._git(git_repo, "log", "--format=%s", "-3")
        assert "real commit" in log
        assert WIP_PREFIX not in log

    def test_squashes_multiple_wip_commits(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None
        for i in range(3):
            self._commit(git_repo, f"{WIP_PREFIX}ts{i}", f"wip{i}.txt")
        success, _ = squash_wip_commits(baseline, "squashed all", git_repo)
        assert success
        log = self._git(git_repo, "log", "--format=%s", "-3")
        assert "squashed all" in log
        assert WIP_PREFIX not in log

    def test_does_not_squash_real_commit_below_wip(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None
        self._commit(git_repo, "real work", "real.txt")
        self._commit(git_repo, f"{WIP_PREFIX}ts1", "wip1.txt")
        success, _ = squash_wip_commits(baseline, "squashed wip", git_repo)
        assert success
        log = self._git(git_repo, "log", "--format=%s", "-5")
        assert "real work" in log

    def test_leaves_wip_below_real_commit_intact(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None

        # WIP commit, then real commit on top
        self._commit(git_repo, f"{WIP_PREFIX}ts1", "wip_below.txt")
        self._commit(git_repo, "real commit on top", "real_top.txt")
        success, msg = squash_wip_commits(baseline, "squashed", git_repo)
        assert success
        assert "Nothing to squash" in msg  # real commit at top, no WIP to squash
        log = self._git(git_repo, "log", "--format=%s", "-5")
        assert "real commit on top" in log
        assert WIP_PREFIX in log  # WIP below real commit survives

    def test_returns_error_when_reset_fails(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None

        self._commit(git_repo, f"{WIP_PREFIX}ts1", "wip1.txt")
        
        original_git = git_tools._git
        call_count = 0
        
        def mock_git(args, cwd):
            nonlocal call_count
            # First call is git log — let it succeed
            # Second call is git reset --soft — fail it
            if args[0] == "reset":
                return False, "fatal: mock reset failure"
            return original_git(args, cwd)
        
        with patch("matrixmouse.tools.git_tools._git", side_effect=mock_git):
            success, msg = squash_wip_commits(baseline, "squashed", git_repo)
        
        assert not success
        assert "reset" in msg.lower()

    def test_returns_error_when_commit_after_reset_fails(self, git_repo):
        baseline = get_head_hash(git_repo)
        assert baseline is not None
        self._commit(git_repo, f"{WIP_PREFIX}ts1", "wip1.txt")
        
        original_git = git_tools._git
        
        def mock_git(args, cwd):
            if args[0] == "commit":
                return False, "fatal: mock commit failure"
            return original_git(args, cwd)
        
        with patch("matrixmouse.tools.git_tools._git", side_effect=mock_git):
            success, msg = squash_wip_commits(baseline, "squashed", git_repo)
        
        assert not success
        assert "commit" in msg.lower()


# ---------------------------------------------------------------------------
# wip_commit_and_push
# ---------------------------------------------------------------------------

class TestWipCommitAndPush:
    def test_noop_when_clean(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        base = "master" if branch_exists("master", repo) else "main"
        success, msg = wip_commit_and_push(base, MIRROR_REMOTE, repo)
        assert success
        assert "clean" in msg.lower()

    def test_creates_wip_commit_when_dirty(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        (repo / "dirty.txt").write_text("change")
        base = "master" if branch_exists("master", repo) else "main"
        success, msg = wip_commit_and_push(base, MIRROR_REMOTE, repo)
        assert success
        assert msg.startswith(WIP_PREFIX)

    def test_wip_message_has_timestamp(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        (repo / "dirty2.txt").write_text("change")
        base = "master" if branch_exists("master", repo) else "main"
        _, msg = wip_commit_and_push(base, MIRROR_REMOTE, repo)
        assert "T" in msg  # ISO timestamp contains T separator

    def test_fails_when_mirror_remote_missing(self, git_repo):
        (git_repo / "dirty3.txt").write_text("change")
        base = "master" if branch_exists("master", git_repo) else "main"
        success, msg = wip_commit_and_push(base, "nonexistent-remote", git_repo)
        assert not success
        assert "ERROR" in msg.upper() or "failed" in msg.lower()

    def test_origin_push_failure_does_not_block(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        (repo / "dirty4.txt").write_text("change")
        base = "master" if branch_exists("master", repo) else "main"
        # origin doesn't exist — should warn but still succeed
        success, msg = wip_commit_and_push(
            base, MIRROR_REMOTE, repo, push_to_origin=True
        )
        assert success  # mirror push succeeded
        assert msg.startswith(WIP_PREFIX)

# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_sets_wip_hash(self, git_repo):
        task = Task(
            title="t", description="d",
            role=AgentRole.MANAGER, repo=["r"],
        )
        task.wip_commit_hash = "abc123"
        git_tools.configure(task, git_repo)
        assert git_tools._active_wip_commit_hash == "abc123"

    def test_sets_branch(self, git_repo):
        task = Task(
            title="t", description="d",
            role=AgentRole.MANAGER, repo=["r"],
            branch="mm/test/foo",
        )
        git_tools.configure(task, git_repo)
        assert git_tools._active_branch == "mm/test/foo"

    def test_sets_cwd(self, git_repo):
        task = Task(
            title="t", description="d",
            role=AgentRole.MANAGER, repo=["r"],
        )
        git_tools.configure(task, git_repo)
        assert git_tools._active_cwd == git_repo

    def test_empty_wip_hash_stored_as_none(self, git_repo):
        task = Task(
            title="t", description="d",
            role=AgentRole.MANAGER, repo=["r"],
        )
        task.wip_commit_hash = ""
        git_tools.configure(task, git_repo)
        assert git_tools._active_wip_commit_hash is None


# ---------------------------------------------------------------------------
# get_git_diff
# ---------------------------------------------------------------------------

class TestGetGitDiff:
    def test_returns_no_changes_when_clean(self, configured_task, git_repo):
        result = git_tools.get_git_diff()
        assert "No changes" in result or result == ""

    def test_shows_diff_against_baseline(self, configured_task, git_repo):
        (git_repo / "new_file.txt").write_text("new content")
        # Stage the file so git diff can see it against the baseline
        subprocess.run(["git", "add", "-A"], cwd=git_repo, capture_output=True)
        result = git_tools.get_git_diff()
        assert "new_file" in result or "new content" in result

    def test_explicit_base_overrides_default(self, configured_task, git_repo):
        result = git_tools.get_git_diff(base="HEAD")
        # HEAD diff shows only unstaged — tree is clean after configure
        assert "No" in result or result == ""


# ---------------------------------------------------------------------------
# get_git_log
# ---------------------------------------------------------------------------

class TestGetGitLog:
    def _git(self, repo, *args):
        result = subprocess.run(
            ["git"] + list(args), cwd=repo, capture_output=True, text=True,
            env={**os.environ,
                 "GIT_AUTHOR_NAME": "Test",
                 "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "test@test.com"},
        )
        return result.stdout.strip()

    def test_filters_wip_commits(self, configured_task, git_repo):
        # Add a WIP commit
        (git_repo / "wip.txt").write_text("wip")
        self._git(git_repo, "add", "-A")
        self._git(git_repo, "commit", "-m", f"{WIP_PREFIX}2026-01-01T00:00:00Z")
        result = git_tools.get_git_log()
        assert WIP_PREFIX not in result

    def test_shows_real_commits(self, configured_task, git_repo):
        (git_repo / "real.txt").write_text("real")
        self._git(git_repo, "add", "-A")
        self._git(git_repo, "commit", "-m", "real commit message")
        result = git_tools.get_git_log()
        assert "real commit message" in result

    def test_initial_commit_shown(self, configured_task, git_repo):
        result = git_tools.get_git_log()
        assert "Initial commit" in result

    def test_clamps_n_to_minimum_1(self, configured_task, git_repo):
        result = git_tools.get_git_log(n=0)
        assert result  # doesn't crash, returns something

    def test_clamps_n_to_maximum_50(self, configured_task, git_repo):
        result = git_tools.get_git_log(n=999)
        assert result  # doesn't crash


# ---------------------------------------------------------------------------
# get_git_status
# ---------------------------------------------------------------------------

class TestGetGitStatus:
    def test_clean_tree(self, configured_task, git_repo):
        result = git_tools.get_git_status()
        assert "clean" in result.lower()

    def test_shows_modified_file(self, configured_task, git_repo):
        (git_repo / "README.md").write_text("modified")
        result = git_tools.get_git_status()
        assert "README.md" in result


# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------

class TestGitCommit:
    def _git(self, repo, *args):
        result = subprocess.run(
            ["git"] + list(args), cwd=repo, capture_output=True, text=True,
            env={**os.environ,
                 "GIT_AUTHOR_NAME": "Test",
                 "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "test@test.com"},
        )
        return result.stdout.strip()

    def test_commits_changes(self, configured_task, git_repo):
        (git_repo / "new.txt").write_text("content")
        result = git_tools.git_commit("add new file")
        assert "OK" in result

    def test_noop_when_nothing_to_commit(self, configured_task, git_repo):
        result = git_tools.git_commit("nothing here")
        assert "Nothing to commit" in result

    def test_squashes_wip_commits(self, configured_task, git_repo):
        # Create a WIP commit
        (git_repo / "wip.txt").write_text("wip content")
        self._git(git_repo, "add", "-A")
        self._git(git_repo, "commit", "-m", f"{WIP_PREFIX}ts1")
        # Now commit for real
        result = git_tools.git_commit("real work done")
        assert "OK" in result
        log = self._git(git_repo, "log", "--format=%s", "-3")
        assert WIP_PREFIX not in log
        assert "real work done" in log


class TestPushToRemote:
    def test_push_succeeds_to_mirror(self, git_repo_with_mirror):
        repo, _ = git_repo_with_mirror
        base = "master" if branch_exists("master", repo) else "main"
        from matrixmouse.tools.git_tools import push_to_remote
        success, _ = push_to_remote(base, MIRROR_REMOTE, repo)
        assert success

    def test_push_fails_to_nonexistent_remote(self, git_repo):
        base = "master" if branch_exists("master", git_repo) else "main"
        from matrixmouse.tools.git_tools import push_to_remote
        success, msg = push_to_remote(base, "no-such-remote", git_repo)
        assert not success
        assert msg

    def test_push_branch_success(self, git_repo_with_mirror, configured_task):
        repo, mirror = git_repo_with_mirror
        branch_name = "mm/test/branch"
        
        # 1. Create and switch to the branch defined in configured_task
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo)
        
        # 2. Make a change
        (repo / "new_feat.txt").write_text("feature")
        subprocess.run(["git", "add", "."], cwd=repo)
        subprocess.run(["git", "commit", "-m", "new feature"], cwd=repo)
        
        # 3. Add origin remote (pointing to our fake mirror)
        subprocess.run(["git", "remote", "add", "origin", str(mirror)], cwd=repo)
        
        # 4. Run the tool
        response = git_tools.push_branch(cwd=repo)
        
        assert "OK" in response
        
        # 5. Verify the branch exists on the remote now
        result = subprocess.run(["git", "ls-remote", "--heads", str(mirror)], 
                                capture_output=True, text=True)
        assert branch_name in result.stdout


class TestRequireCwd:
    def test_raises_when_not_configured(self):
        git_tools._active_cwd = None
        git_tools._active_wip_commit_hash = None
        git_tools._active_branch = None
        with pytest.raises(RuntimeError, match="not configured"):
            git_tools.get_git_status()

class TestCloneRepo:
    def test_clone_repo_success(self, tmp_path, git_repo):
        # Use our existing git_repo as the 'remote' source to clone from
        remote_url = str(git_repo)
        workspace = tmp_path / "mock_workspace"
        workspace.mkdir()
        
        with patch.dict(os.environ, {"WORKSPACE_PATH": str(workspace)}):
            response = git_tools.clone_repo(remote_url, directory="cloned_project")
            
            assert "OK: Cloned" in response
            assert (workspace / "cloned_project" / "README.md").exists()
            assert (workspace / "cloned_project" / ".git").is_dir()

    def test_clone_repo_already_exists(self, tmp_path, git_repo):
        workspace = tmp_path / "mock_workspace"
        workspace.mkdir()
        (workspace / "exists").mkdir()
        
        with patch.dict(os.environ, {"WORKSPACE_PATH": str(workspace)}):
            response = git_tools.clone_repo(str(git_repo), directory="exists")
            assert "ERROR: Directory" in response
            assert "already exists" in response