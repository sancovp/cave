"""RemoteAgent Mixin.

Provides SDNA remote agent management for CAVEAgent.
"""
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import RemoteAgentHandle
    from ..config import CAVEConfig


class RemoteAgentMixin:
    """Mixin for SDNA remote agent management."""

    remote_agents: Dict[str, "RemoteAgentHandle"]
    config: "CAVEConfig"

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Override in CAVEAgent."""
        pass

    async def spawn_remote(
        self,
        name: str,
        system_prompt: str,
        goal_template: str,
        spawned_by: str,
        inputs: Optional[Dict] = None,
        **kwargs
    ) -> "RemoteAgentHandle":
        """Spawn a remote agent via SDNA."""
        from ..models import RemoteAgentHandle

        agent_id = f"{name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        handle = RemoteAgentHandle(
            agent_id=agent_id,
            config={
                "name": name,
                "system_prompt": system_prompt,
                "goal_template": goal_template,
                **kwargs
            },
            status="pending",
            spawned_by=spawned_by
        )
        self.remote_agents[agent_id] = handle
        self._emit_event("remote_agent_spawned", {"agent_id": agent_id, "spawned_by": spawned_by})

        # Only run if SDNA is available and enabled
        if self.config.sdna_enabled:
            try:
                from ..remote_agent import RemoteAgent, RemoteAgentConfig

                config = RemoteAgentConfig(
                    name=name,
                    system_prompt=system_prompt,
                    goal_template=goal_template,
                    **kwargs
                )
                agent = RemoteAgent(config)

                handle.status = "running"
                result = await agent.run(inputs or {})

                handle.status = "completed" if result.success else "failed"
                handle.result = result.__dict__
                self._emit_event("remote_agent_completed", {"agent_id": agent_id, "success": result.success})

            except ImportError:
                handle.status = "failed"
                handle.result = {"error": "SDNA not installed"}
            except Exception as e:
                handle.status = "failed"
                handle.result = {"error": str(e)}

        return handle

    def get_remote_status(self, agent_id: str) -> Optional["RemoteAgentHandle"]:
        """Get status of a remote agent."""
        return self.remote_agents.get(agent_id)

    def list_remote_agents(self) -> Dict[str, "RemoteAgentHandle"]:
        """List all remote agents."""
        return self.remote_agents.copy()

    def remote_agents_summary(self) -> Dict[str, Any]:
        """Get summary of remote agents."""
        by_status = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for handle in self.remote_agents.values():
            by_status[handle.status] = by_status.get(handle.status, 0) + 1
        return {
            "total": len(self.remote_agents),
            "by_status": by_status
        }
