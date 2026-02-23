"""Transition Functions for DNA System.

Transition functions resolve which loop to go to next based on PAIA state.
Each PAIA implementation defines its own transition functions.

Usage:
    # Define transition functions
    def home_transition(paia) -> str:
        if paia.mode == "NIGHT":
            return "HOME_NIGHT"
        if paia.omnisanc_zone == "STARPORT":
            return "STARPORT"
        return "HOME_DAY"

    # Register them
    TRANSITIONS.register("home_next", home_transition)

    # In AgentInferenceLoop, `next` refers to transition function name
    loop = AgentInferenceLoop(
        name="HOME_DAY",
        next="home_next",  # calls home_transition(paia) to get next loop
    )
"""
import logging
import traceback
from typing import Callable, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import PAIAState

logger = logging.getLogger(__name__)

# Type alias for transition functions
# Takes PAIAState, returns next loop name (or None to stay/stop)
TransitionFn = Callable[["PAIAState"], Optional[str]]


class TransitionRegistry:
    """Registry of transition functions for DNA system."""

    def __init__(self):
        self._transitions: Dict[str, TransitionFn] = {}

    def register(self, name: str, fn: TransitionFn) -> None:
        """Register a transition function."""
        self._transitions[name] = fn
        logger.debug(f"Registered transition: {name}")

    def get(self, name: str) -> Optional[TransitionFn]:
        """Get transition function by name."""
        return self._transitions.get(name)

    def resolve(self, name: str, paia: "PAIAState") -> Optional[str]:
        """Resolve transition - call function and return next loop name."""
        fn = self.get(name)
        if fn is None:
            logger.warning(f"Transition function not found: {name}")
            return None
        try:
            return fn(paia)
        except Exception as e:
            logger.error(f"Transition function {name} failed: {e}\n{traceback.format_exc()}")
            return None

    def list(self) -> list:
        """List all registered transition names."""
        return list(self._transitions.keys())


# Global registry - PAIA implementations register their transitions here
TRANSITIONS = TransitionRegistry()


# ============================================================================
# OMNISANC Transition Functions (Isaac's DNA implementation)
# ============================================================================
# Zones: HOME → STARPORT → LAUNCH → SESSION → LANDING → STARPORT (loop)
# HOME has DAY/NIGHT sub-modes, LANDING has 3 sub-phases

def omnisanc_home_transition(paia: "PAIAState") -> Optional[str]:
    """HOME loop transition - check mode and zone changes."""
    # Check if we've left HOME
    if paia.omnisanc_zone != "HOME":
        return f"OMNISANC_{paia.omnisanc_zone}"

    # Still in HOME - check DAY/NIGHT
    if paia.mode == "NIGHT":
        return "OMNISANC_HOME_NIGHT"
    return "OMNISANC_HOME_DAY"


def omnisanc_starport_transition(paia: "PAIAState") -> Optional[str]:
    """STARPORT loop transition (course plotted, !fly_called)."""
    zone = paia.omnisanc_zone
    if zone == "LAUNCH":
        return "OMNISANC_LAUNCH"
    if zone == "HOME":
        return omnisanc_home_transition(paia)
    return "OMNISANC_STARPORT"  # stay


def omnisanc_launch_transition(paia: "PAIAState") -> Optional[str]:
    """LAUNCH loop transition (fly_called, !flight_selected)."""
    zone = paia.omnisanc_zone
    if zone == "SESSION":
        return "OMNISANC_SESSION"
    if zone == "STARPORT":
        return "OMNISANC_STARPORT"
    if zone == "HOME":
        return omnisanc_home_transition(paia)
    return "OMNISANC_LAUNCH"  # stay


def omnisanc_session_transition(paia: "PAIAState") -> Optional[str]:
    """SESSION loop transition (flight_selected, session_active)."""
    zone = paia.omnisanc_zone
    if zone == "LANDING":
        return "OMNISANC_LANDING"
    if zone == "HOME":
        return omnisanc_home_transition(paia)
    return "OMNISANC_SESSION"  # stay


def omnisanc_landing_transition(paia: "PAIAState") -> Optional[str]:
    """LANDING loop transition (needs_review, 3 sub-phases)."""
    zone = paia.omnisanc_zone
    if zone == "STARPORT":
        return "OMNISANC_STARPORT"  # Back to starport for next flight
    if zone == "HOME":
        return omnisanc_home_transition(paia)
    return "OMNISANC_LANDING"  # stay


# Register OMNISANC transitions
def register_omnisanc_transitions():
    """Register all OMNISANC transition functions."""
    TRANSITIONS.register("omnisanc_home_next", omnisanc_home_transition)
    TRANSITIONS.register("omnisanc_starport_next", omnisanc_starport_transition)
    TRANSITIONS.register("omnisanc_launch_next", omnisanc_launch_transition)
    TRANSITIONS.register("omnisanc_session_next", omnisanc_session_transition)
    TRANSITIONS.register("omnisanc_landing_next", omnisanc_landing_transition)


# Auto-register on import
register_omnisanc_transitions()
