"""AgentRegistry Mixin.

Provides agent registration for CAVEAgent.
"""
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import AgentRegistration


class AgentRegistryMixin:
    """Mixin for agent registration."""

    agent_registry: Dict[str, "AgentRegistration"]

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Override in CAVEAgent."""
        pass

    def register_agent(self, agent_id: str, **kwargs) -> "AgentRegistration":
        """Register an agent with the runtime."""
        from ..models import AgentRegistration

        reg = AgentRegistration(agent_id=agent_id, **kwargs)
        self.agent_registry[agent_id] = reg
        self._emit_event("agent_registered", {"agent_id": agent_id})
        return reg

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent."""
        if agent_id in self.agent_registry:
            del self.agent_registry[agent_id]
            self._emit_event("agent_unregistered", {"agent_id": agent_id})
            return True
        return False

    def get_agent(self, agent_id: str) -> Optional["AgentRegistration"]:
        """Get agent registration."""
        return self.agent_registry.get(agent_id)

    def list_agents(self) -> Dict[str, "AgentRegistration"]:
        """List all registered agents."""
        return self.agent_registry.copy()
