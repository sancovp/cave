"""SILAS observe loop for CAVE DNA."""
from typing import Any, Dict

from .base import create_loop


def _phase_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("silas_coreflow", {})


def _on_start(state: Dict[str, Any]) -> None:
    core = _phase_state(state)
    core["phase"] = "observe"
    core.setdefault("completed_phases", [])
    core["observe_complete"] = False


def _on_stop(state: Dict[str, Any]) -> None:
    _phase_state(state)["last_stopped_phase"] = "observe"


def _exit_condition(state: Dict[str, Any]) -> bool:
    return bool(_phase_state(state).get("observe_complete"))


SILAS_OBSERVE_PROMPT = """You are in SILAS_OBSERVE.

Inspect the active goal, AIOS status, current mode, next action, queues, and recent evidence.
Do not edit yet. Produce a concise context packet and mark silas_coreflow.observe_complete only
after the current operating boundary is clear."""


SILAS_OBSERVE_LOOP = create_loop(
    name="silas_observe",
    description="Observe current SILAS goal, AIOS state, queues, and evidence before acting",
    prompt=SILAS_OBSERVE_PROMPT,
    output_override={
        "type": "agent_inbox",
        "to_agent": "codex",
        "from_agent": "loop:silas_observe",
    },
    active_hooks={"stop": ["cognitive_space_stop_check"]},
    exit_condition=_exit_condition,
    on_start=_on_start,
    on_stop=_on_stop,
)
