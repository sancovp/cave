"""Autopoiesis Loop - Self-maintaining agent execution.

Uses hooks from cave_hooks/ directory:
- autopoiesis_stop: blocks until promise completed
"""
from typing import Any, Dict

from .base import create_loop


def _on_start(state: Dict[str, Any]) -> None:
    """Initialize autopoiesis loop state."""
    state["autopoiesis"] = {
        "mode": "working",
        "promise_fulfilled": False,
    }


def _on_stop(state: Dict[str, Any]) -> None:
    """Cleanup when loop stops."""
    if "autopoiesis" in state:
        state["autopoiesis"]["mode"] = "stopped"


def _exit_condition(state: Dict[str, Any]) -> bool:
    """Exit when promise file no longer exists (work complete)."""
    from pathlib import Path
    # Matches autopoiesis_mcp pattern: file exists = working, file gone = done
    return not Path("/tmp/active_promise.md").exists()


AUTOPOIESIS_PROMPT = """You are now in AUTOPOIESIS mode.

Make a promise about what you will accomplish, then fulfill it.
You cannot exit until your promise is complete.

State your promise now."""


AUTOPOIESIS_LOOP = create_loop(
    name="autopoiesis",
    description="Self-maintaining agent loop - blocks stop until promise completed",
    prompt=AUTOPOIESIS_PROMPT,
    active_hooks={
        "stop": ["autopoiesis_stop"],
    },
    exit_condition=_exit_condition,
    next=None,  # Can be set to "guru" to chain
    on_start=_on_start,
    on_stop=_on_stop,
)
