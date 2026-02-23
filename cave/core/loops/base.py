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

        # 2. Send prompt via tmux
        prompt_sent = False
        if self.prompt and cave_agent.main_agent:
            cave_agent.main_agent.send_keys(self.prompt, 0.5, "Enter")
            prompt_sent = True

        # 3. Run on_start callback
        if self.on_start:
            self.on_start(cave_agent._hook_state)

        return {
            "loop": self.name,
            "active_hooks": self.active_hooks,
            "prompt_sent": prompt_sent,
            "status": "activated",
        }

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
        active_hooks=active_hooks or {},
        exit_condition=exit_condition,
        next=next,
        on_start=on_start,
        on_stop=on_stop,
        config=config or {},
    )
