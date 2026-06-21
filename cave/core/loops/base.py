"""AgentInferenceLoop - Complete autonomous execution pattern.

An AgentInferenceLoop is:
- A prompt to inject via tmux to start the loop
- A set of hooks to activate (by name from registry)
- An exit condition to check when loop is complete
- A next loop to chain to (or None to stop/cycle)
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..cave_agent import CAVEAgent

logger = logging.getLogger(__name__)


@dataclass
class AgentInferenceLoop:
    """Complete autonomous execution pattern for a live Claude Code agent.

    Usage:
        loop = AgentInferenceLoop(
            name="autopoiesis",
            prompt="You are in autopoiesis mode. Make a promise and fulfill it.",
            active_hooks={"stop": ["autopoiesis_stop"]},
            exit_condition=lambda state: state.get("promise_fulfilled"),
            next="guru",  # or None to stop
        )

        # Activate: sets hooks AND sends prompt via tmux
        loop.activate(cave_agent)
    """
    name: str
    description: str = ""

    # Prompt to inject via tmux when loop starts
    prompt: str = ""

    # Optional delivery override for the prompt.
    # Default/None keeps legacy tmux behavior. Dict shape:
    # {"type": "agent_inbox", "to_agent": "conductor", "from_agent": "loop:name"}
    # Callable shape: output_override(cave_agent, loop) -> dict
    output_override: Optional[Any] = None

    # Which hooks from registry to activate, by type
    # Keys: "stop", "pretooluse", "posttooluse", etc.
    # Values: list of hook names from cave_hooks/
    active_hooks: Dict[str, List[str]] = field(default_factory=dict)

    # Exit condition - when True, loop is complete
    # Signature: (state: Dict) -> bool
    exit_condition: Optional[Callable[[Dict], bool]] = None

    # Next loop name to chain to, or None to stop/cycle
    next: Optional[str] = None

    # Lifecycle callbacks
    on_start: Optional[Callable[[Dict], None]] = None
    on_stop: Optional[Callable[[Dict], None]] = None

    # Arbitrary config for this loop
    config: Dict[str, Any] = field(default_factory=dict)

    def activate(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Activate this loop - set hooks AND send prompt via tmux.

        Args:
            cave_agent: The CAVEAgent instance

        Returns:
            Activation result with status
        """
        # 1. Activate hooks
        cave_agent.config.main_agent_config.active_hooks = self.active_hooks.copy()

        # 2. Deliver prompt through the selected output surface
        output_result = self.deliver_prompt(cave_agent)
        prompt_sent = bool(output_result.get("sent"))

        # 3. Run on_start callback
        if self.on_start:
            self.on_start(cave_agent._hook_state)

        return {
            "loop": self.name,
            "active_hooks": self.active_hooks,
            "prompt_sent": prompt_sent,
            "output": output_result,
            "status": "activated",
        }

    def deliver_prompt(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Deliver the loop prompt to tmux or an override target."""
        if not self.prompt:
            return {"sent": False, "type": "none", "reason": "empty prompt"}

        if callable(self.output_override):
            result = self.output_override(cave_agent, self)
            if isinstance(result, dict):
                return {"sent": True, "type": "callable", **result}
            return {"sent": True, "type": "callable", "result": result}

        if isinstance(self.output_override, dict):
            output_type = self.output_override.get("type", "agent_inbox")

            if output_type in ("agent_inbox", "inbox"):
                to_agent = (
                    self.output_override.get("to_agent")
                    or self.output_override.get("inbox")
                    or self.output_override.get("target")
                )
                if not to_agent:
                    return {
                        "sent": False,
                        "type": output_type,
                        "error": "output_override requires to_agent, inbox, or target",
                    }
                if not hasattr(cave_agent, "route_message"):
                    return {
                        "sent": False,
                        "type": output_type,
                        "to_agent": to_agent,
                        "error": "cave_agent has no route_message()",
                    }

                metadata = {
                    "loop": self.name,
                    "output_override": output_type,
                    **self.output_override.get("metadata", {}),
                }
                message_id = cave_agent.route_message(
                    from_agent=self.output_override.get("from_agent", f"loop:{self.name}"),
                    to_agent=to_agent,
                    content=self.prompt,
                    priority=self.output_override.get("priority", 0),
                    metadata=metadata,
                )
                return {
                    "sent": True,
                    "type": output_type,
                    "to_agent": to_agent,
                    "message_id": message_id,
                }

            if output_type == "tmux":
                return self._deliver_prompt_to_tmux(cave_agent)

            return {
                "sent": False,
                "type": output_type,
                "error": f"Unknown output_override type: {output_type}",
            }

        return self._deliver_prompt_to_tmux(cave_agent)

    def _deliver_prompt_to_tmux(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Legacy loop prompt delivery path for Claude/tmux-backed agents."""
        if getattr(cave_agent, "main_agent", None):
            cave_agent.main_agent.send_keys(self.prompt, 0.5, "Enter")
            return {"sent": True, "type": "tmux"}
        return {"sent": False, "type": "tmux", "reason": "no main_agent"}

    def deactivate(self, cave_agent: "CAVEAgent") -> Dict[str, Any]:
        """Deactivate this loop - clear active_hooks.

        Args:
            cave_agent: The CAVEAgent instance

        Returns:
            Deactivation result
        """
        # Clear active_hooks
        cave_agent.config.main_agent_config.active_hooks = {}

        # Run on_stop callback
        if self.on_stop:
            self.on_stop(cave_agent._hook_state)

        return {
            "loop": self.name,
            "status": "deactivated",
        }

    def check_exit(self, state: Dict[str, Any]) -> bool:
        """Check if exit condition is met."""
        if self.exit_condition is None:
            return False
        try:
            return self.exit_condition(state)
        except Exception:
            logger.exception(f"Exit condition check failed for loop {self.name}")
            return False


def create_loop(
    name: str,
    description: str = "",
    prompt: str = "",
    output_override: Any = None,
    active_hooks: Dict[str, List[str]] = None,
    exit_condition: Callable[[Dict], bool] = None,
    next: str = None,
    on_start: Callable = None,
    on_stop: Callable = None,
    config: Dict[str, Any] = None,
) -> AgentInferenceLoop:
    """Factory function to create a loop."""
    return AgentInferenceLoop(
        name=name,
        description=description,
        prompt=prompt,
        output_override=output_override,
        active_hooks=active_hooks or {},
        exit_condition=exit_condition,
        next=next,
        on_start=on_start,
        on_stop=on_stop,
        config=config or {},
    )
