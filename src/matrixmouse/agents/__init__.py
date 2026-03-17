"""
matrixmouse/agents/__init__.py

Agent package — maps AgentRole values to concrete agent classes.

Usage:
    from matrixmouse.agents import agent_for_role
    agent = agent_for_role(task.role)
    messages = agent.build_initial_messages(task)

Adding a new agent:
    1. Implement the concrete class in a new module under agents/.
    2. Import it here and add it to _AGENT_REGISTRY.
"""

from matrixmouse.agents.manager import ManagerAgent
from matrixmouse.agents.coder import CoderAgent
from matrixmouse.agents.writer import WriterAgent
from matrixmouse.agents.critic import CriticAgent
from matrixmouse.task import AgentRole

_AGENT_REGISTRY: dict[AgentRole, type] = {
    AgentRole.MANAGER: ManagerAgent,
    AgentRole.CODER:   CoderAgent,
    AgentRole.WRITER:  WriterAgent,
    AgentRole.CRITIC:  CriticAgent,
}


def agent_for_role(role: AgentRole) -> "BaseAgent":
    """
    Return a concrete agent instance for the given role.

    Args:
        role (AgentRole): The role to instantiate.

    Returns:
        BaseAgent: A concrete agent instance.

    Raises:
        KeyError: If the role has no registered agent class. This
            indicates a programming error — all roles in AgentRole
            must have a corresponding entry in _AGENT_REGISTRY.
    """
    cls = _AGENT_REGISTRY.get(role)
    if cls is None:
        raise KeyError(
            f"No agent registered for role {role!r}. "
            f"Add it to _AGENT_REGISTRY in agents/__init__.py."
        )
    return cls()
    