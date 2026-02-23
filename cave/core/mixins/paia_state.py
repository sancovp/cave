"""PAIAState Mixin.

Provides PAIA state management for CAVEAgent.
"""
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import PAIAState


class PAIAStateMixin:
    """Mixin for PAIA state management."""

    paia_states: Dict[str, "PAIAState"]

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Override in CAVEAgent."""
        pass

    def update_paia_state(self, paia_id: str, **updates) -> "PAIAState":
        """Update a PAIA's state."""
        from ..models import PAIAState

        if paia_id not in self.paia_states:
            self.paia_states[paia_id] = PAIAState(paia_id=paia_id)

        state = self.paia_states[paia_id]
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
        state.last_heartbeat = datetime.utcnow()

        self._emit_event("paia_state_changed", {"paia_id": paia_id, "state": state.model_dump()})
        return state

    def get_paia_state(self, paia_id: str) -> Optional["PAIAState"]:
        """Get a PAIA's state."""
        return self.paia_states.get(paia_id)

    def list_paias(self) -> Dict[str, "PAIAState"]:
        """List all PAIAs and their states."""
        return self.paia_states.copy()

    def remove_paia(self, paia_id: str) -> bool:
        """Remove a PAIA from tracking."""
        if paia_id in self.paia_states:
            del self.paia_states[paia_id]
            self._emit_event("paia_removed", {"paia_id": paia_id})
            return True
        return False
