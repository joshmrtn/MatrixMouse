"""
matrixmouse/repository

Task and workspace state persistence layer.

Exports the abstract interfaces and the SQLite concrete implementations.
The in-memory implementation is for test use only — import directly
from matrixmouse.repository.memory_task_repository in test code.
"""

from matrixmouse.repository.task_repository import TaskRepository
from matrixmouse.repository.workspace_state_repository import (
    WorkspaceStateRepository,
)
from matrixmouse.repository.sqlite_task_repository import (
    SQLiteTaskRepository,
)
from matrixmouse.repository.sqlite_workspace_state_repository import (
    SQLiteWorkspaceStateRepository,
)

__all__ = [
    "TaskRepository",
    "WorkspaceStateRepository",
    "SQLiteTaskRepository",
    "SQLiteWorkspaceStateRepository",
]
