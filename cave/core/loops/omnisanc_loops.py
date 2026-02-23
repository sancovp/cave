"""OMNISANC AgentInferenceLoop Definitions.

These are Isaac's DNA loop definitions for the OMNISANC state machine.
Each loop activates its corresponding hook and uses transition functions
to determine the next loop.

Zone flow: HOME → STARPORT → LAUNCH → SESSION → LANDING → STARPORT (loop)
"""
from typing import Dict

from .base import AgentInferenceLoop


def _zone_changed(target_zone: str):
    """Create exit condition that triggers when zone changes."""
    def check(state: Dict) -> bool:
        current = state.get("omnisanc_zone", "HOME")
        return current != target_zone
    return check


# ============================================================================
# HOME Loops (DAY and NIGHT variants)
# ============================================================================

OMNISANC_HOME_DAY = AgentInferenceLoop(
    name="OMNISANC_HOME_DAY",
    description="HOME zone in DAY mode - human available, collaborative work",
    active_hooks={"stop": ["omnisanc_home_v2"]},
    exit_condition=_zone_changed("HOME"),
    next="omnisanc_home_next",
)

OMNISANC_HOME_NIGHT = AgentInferenceLoop(
    name="OMNISANC_HOME_NIGHT",
    description="HOME zone in NIGHT mode - autonomous maintenance work",
    active_hooks={"stop": ["omnisanc_home_v2"]},
    exit_condition=_zone_changed("HOME"),
    next="omnisanc_home_next",
)


# ============================================================================
# STARPORT Loop (course plotted, browsing flights)
# ============================================================================

OMNISANC_STARPORT = AgentInferenceLoop(
    name="OMNISANC_STARPORT",
    description="STARPORT zone - course plotted, ready to browse flights",
    active_hooks={"stop": ["omnisanc_starport"]},
    exit_condition=_zone_changed("STARPORT"),
    next="omnisanc_starport_next",
)


# ============================================================================
# LAUNCH Loop (fly called, selecting flight)
# ============================================================================

OMNISANC_LAUNCH = AgentInferenceLoop(
    name="OMNISANC_LAUNCH",
    description="LAUNCH zone - browsed flights, selecting one to start",
    active_hooks={"stop": ["omnisanc_launch"]},
    exit_condition=_zone_changed("LAUNCH"),
    next="omnisanc_launch_next",
)


# ============================================================================
# SESSION Loop (active work)
# ============================================================================

OMNISANC_SESSION = AgentInferenceLoop(
    name="OMNISANC_SESSION",
    description="SESSION zone - actively working through flight waypoints",
    active_hooks={"stop": ["omnisanc_session"]},
    exit_condition=_zone_changed("SESSION"),
    next="omnisanc_session_next",
)


# ============================================================================
# LANDING Loop (wrap-up sequence with 3 sub-phases)
# ============================================================================

OMNISANC_LANDING = AgentInferenceLoop(
    name="OMNISANC_LANDING",
    description="LANDING zone - 3-phase wrap-up sequence",
    active_hooks={"stop": ["omnisanc_landing"]},
    exit_condition=_zone_changed("LANDING"),
    next="omnisanc_landing_next",
)


# ============================================================================
# Loop Registry
# ============================================================================

OMNISANC_LOOPS = {
    "OMNISANC_HOME_DAY": OMNISANC_HOME_DAY,
    "OMNISANC_HOME_NIGHT": OMNISANC_HOME_NIGHT,
    "OMNISANC_STARPORT": OMNISANC_STARPORT,
    "OMNISANC_LAUNCH": OMNISANC_LAUNCH,
    "OMNISANC_SESSION": OMNISANC_SESSION,
    "OMNISANC_LANDING": OMNISANC_LANDING,
}


def get_omnisanc_loop(name: str) -> AgentInferenceLoop:
    """Get OMNISANC loop by name."""
    return OMNISANC_LOOPS.get(name)


def list_omnisanc_loops() -> list:
    """List all OMNISANC loop names."""
    return list(OMNISANC_LOOPS.keys())
