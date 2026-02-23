"""LoopManager Mixin.

Loads AgentInferenceLoop configs, manages lifecycle via active_hooks on config.
"""
import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import CAVEConfig

from ..loops import AVAILABLE_LOOPS, AgentInferenceLoop

logger = logging.getLogger(__name__)


class LoopManagerMixin:
    """Mixin for loading and managing AgentInferenceLoop configs."""

    config: "CAVEConfig"
    _loop_state: Dict[str, Any]
    _active_loop: Optional[AgentInferenceLoop]

    # These come from HookRouterMixin (must be mixed in first)
    _hook_state: Dict[str, Any]

    def _init_loop_manager(self) -> None:
        """Initialize loop manager state."""
        self._loop_state = {
            "active_loop": None,
            "mode": "idle",
            "started_at": None,
            "last_transition": None,
        }
        self._active_loop = None

    def get_loop_state(self) -> Dict[str, Any]:
        """Get current loop state."""
        return {
            **self._loop_state,
            "available_loops": list(AVAILABLE_LOOPS.keys()),
            "active_loop_config": {
                "name": self._active_loop.name,
                "description": self._active_loop.description,
                "active_hooks": self._active_loop.active_hooks,
            } if self._active_loop else None,
        }

    def start_loop(self, loop_type: str, config: Optional[Dict] = None) -> Dict[str, Any]:
        """Start an AgentInferenceLoop.

        1. Get loop config from AVAILABLE_LOOPS
        2. Call loop.activate(self.config) to set active_hooks
        3. Run on_start()
        """
        # Stop existing loop first
        if self._active_loop:
            self.stop_loop()

        # Get loop config
        if loop_type not in AVAILABLE_LOOPS:
            return {"error": f"Unknown loop type: {loop_type}", "available": list(AVAILABLE_LOOPS.keys())}

        loop = AVAILABLE_LOOPS[loop_type]
        self._active_loop = loop

        # Update loop state
        self._loop_state = {
            "active_loop": loop_type,
            "mode": "working",
            "started_at": time.time(),
            "last_transition": time.time(),
            "config": config or {},
        }

        # Activate loop - sets active_hooks and sends prompt via tmux
        activation_result = loop.activate(self)

        # Store loop config in hook_state so on_start can access it
        self._hook_state["_loop_config"] = config or {}

        # Run on_start callback
        if loop.on_start:
            try:
                loop.on_start(self._hook_state)
            except Exception as e:
                return {"error": f"on_start failed: {e}", "started": False}

        return {
            "started": loop_type,
            "activation": activation_result,
            "state": self._loop_state,
        }

    def stop_loop(self) -> Dict[str, Any]:
        """Stop current loop.

        1. Run on_stop()
        2. Call loop.deactivate(self.config) to clear active_hooks
        """
        if not self._active_loop:
            return {"error": "No active loop", "state": self._loop_state}

        loop = self._active_loop
        previous = loop.name

        # Run on_stop callback
        if loop.on_stop:
            try:
                loop.on_stop(self._hook_state)
            except Exception:
                pass  # Don't fail stop on callback error

        # Deactivate loop - clears active_hooks
        loop.deactivate(self)

        # Clear state
        self._active_loop = None
        self._loop_state = {
            "active_loop": None,
            "mode": "idle",
            "started_at": None,
            "last_transition": time.time(),
        }

        return {"stopped": previous, "state": self._loop_state}

    def trigger_transition(self, event: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Trigger a loop transition event."""
        if not self._active_loop:
            return {"error": "No active loop"}

        previous_mode = self._loop_state.get("mode")

        # Check conditions from the loop
        for condition_name, condition_fn in self._active_loop.conditions.items():
            try:
                if condition_fn(self._hook_state):
                    self._loop_state["triggered_condition"] = condition_name
            except Exception:
                pass

        # Simple state machine for common events
        transitions = {
            "blocked": "blocked",
            "unblocked": "working",
            "complete": "completing",
            "continue": "working",
            "reset": "idle",
        }

        new_mode = transitions.get(event, self._loop_state.get("mode"))
        self._loop_state["mode"] = new_mode
        self._loop_state["last_transition"] = time.time()
        self._loop_state["last_event"] = event

        return {
            "event": event,
            "previous_mode": previous_mode,
            "new_mode": new_mode,
            "state": self._loop_state,
        }

    def pause_loop(self) -> Dict[str, Any]:
        """Pause current loop (allows exit without meeting conditions)."""
        if not self._active_loop:
            return {"error": "No active loop"}

        self._hook_state.setdefault(self._active_loop.name, {})["paused"] = True
        self._loop_state["mode"] = "paused"

        return {"paused": self._active_loop.name, "state": self._loop_state}

    def resume_loop(self) -> Dict[str, Any]:
        """Resume paused loop."""
        if not self._active_loop:
            return {"error": "No active loop"}

        self._hook_state.setdefault(self._active_loop.name, {})["paused"] = False
        self._loop_state["mode"] = "working"

        return {"resumed": self._active_loop.name, "state": self._loop_state}

    def list_available_loops(self) -> Dict[str, Any]:
        """List all available loop configurations."""
        return {
            name: {
                "description": loop.description,
                "active_hooks": loop.active_hooks,
                "conditions": list(loop.conditions.keys()),
            }
            for name, loop in AVAILABLE_LOOPS.items()
        }
