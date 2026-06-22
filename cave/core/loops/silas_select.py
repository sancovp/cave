"""SILAS selection loop for CAVE DNA."""
from typing import Any, Dict

from .base import create_loop


def _phase_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("silas_coreflow", {})


def _on_start(state: Dict[str, Any]) -> None:
    core = _phase_state(state)
    core["phase"] = "select"
    core["select_complete"] = False


def _on_stop(state: Dict[str, Any]) -> None:
    _phase_state(state)["last_stopped_phase"] = "select"


def _exit_condition(state: Dict[str, Any]) -> bool:
    return bool(_phase_state(state).get("select_complete"))


SILAS_SELECT_PROMPT = """You are in SILAS_SELECT.

Choose the next lawful bounded move. Prefer the smallest move that advances the active
objective, has a proof gate, and does not cross approval boundaries. If needed, emit a
DNASequence-shaped plan before execution."""


SILAS_SELECT_LOOP = create_loop(
    name="silas_select",
    description="Select the next lawful bounded SILAS move and proof gate",
    prompt=SILAS_SELECT_PROMPT,
    output_override={
        "type": "agent_inbox",
        "to_agent": "codex",
        "from_agent": "loop:silas_select",
    },
    active_hooks={"stop": ["cognitive_space_stop_check"]},
    exit_condition=_exit_condition,
    on_start=_on_start,
    on_stop=_on_stop,
)
