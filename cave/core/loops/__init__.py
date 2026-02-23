"""CAVE Loops - AgentInferenceLoop configs that define agent behavior.

A loop is a complete autonomous execution pattern:
- prompt: injected via tmux to start the loop
- active_hooks: which hooks to activate
- exit_condition: when the loop is complete
- next: which loop to chain to (or None)
"""
from .base import AgentInferenceLoop, create_loop
from .autopoiesis import AUTOPOIESIS_LOOP
from .guru import GURU_LOOP
from .transitions import TRANSITIONS, register_omnisanc_transitions
from .omnisanc_loops import (
    OMNISANC_LOOPS,
    OMNISANC_HOME_DAY,
    OMNISANC_HOME_NIGHT,
    OMNISANC_STARPORT,
    OMNISANC_LAUNCH,
    OMNISANC_SESSION,
    OMNISANC_LANDING,
    get_omnisanc_loop,
    list_omnisanc_loops,
)

AVAILABLE_LOOPS = {
    "autopoiesis": AUTOPOIESIS_LOOP,
    "guru": GURU_LOOP,
    **OMNISANC_LOOPS,
}

__all__ = [
    "AgentInferenceLoop",
    "create_loop",
    "AVAILABLE_LOOPS",
    "AUTOPOIESIS_LOOP",
    "GURU_LOOP",
    # OMNISANC
    "TRANSITIONS",
    "OMNISANC_LOOPS",
    "OMNISANC_HOME_DAY",
    "OMNISANC_HOME_NIGHT",
    "OMNISANC_STARPORT",
    "OMNISANC_LAUNCH",
    "OMNISANC_SESSION",
    "OMNISANC_LANDING",
    "get_omnisanc_loop",
    "list_omnisanc_loops",
]
