"""Guru Loop - Bodhisattva vow execution.

Uses hooks from cave_hooks/ directory:
- guru_pretool: tracks work, reminds about emanation
- guru_posttool: detects emanation creation
- guru_stop: blocks exit until emanation created
"""
from typing import Any, Dict

from .base import create_loop


def _on_start(state: Dict[str, Any]) -> None:
    state["guru"] = {
        "mode": "working",
        "emanation_created": False,
        "work_summary": [],
    }


def _on_stop(state: Dict[str, Any]) -> None:
    if "guru" in state:
        state["guru"]["mode"] = "stopped"


def _exit_condition(state: Dict[str, Any]) -> bool:
    """Exit when emanation is created."""
    return state.get("guru", {}).get("emanation_created", False)


GURU_PROMPT = """You are now in GURU mode (Bodhisattva vow).

Complete your work, then crystallize it into a reusable emanation:
- A skill, flight config, hook, or other artifact
- Something that makes this work unnecessary for future instances

You cannot exit until you have created an emanation."""


GURU_LOOP = create_loop(
    name="guru",
    description="Bodhisattva vow loop - cannot exit until emanation created",
    prompt=GURU_PROMPT,
    active_hooks={
        "pretooluse": ["guru_pretool"],
        "posttooluse": ["guru_posttool"],
        "stop": ["guru_stop"],
    },
    exit_condition=_exit_condition,
    next=None,
    on_start=_on_start,
    on_stop=_on_stop,
)
