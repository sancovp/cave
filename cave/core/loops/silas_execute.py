"""SILAS execution loop for CAVE DNA."""
from typing import Any, Dict

from .base import create_loop


def _phase_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("silas_coreflow", {})


def _on_start(state: Dict[str, Any]) -> None:
    core = _phase_state(state)
    core["phase"] = "execute"
    core["execute_complete"] = False


def _on_stop(state: Dict[str, Any]) -> None:
    _phase_state(state)["last_stopped_phase"] = "execute"


def _exit_condition(state: Dict[str, Any]) -> bool:
    return bool(_phase_state(state).get("execute_complete"))


SILAS_EXECUTE_PROMPT = """You are in SILAS_EXECUTE.

Carry out exactly one bounded move from the selected plan. Keep edits scoped, avoid hidden
approval boundaries, and leave enough local evidence for the assay phase to falsify the work."""


SILAS_EXECUTE_LOOP = create_loop(
    name="silas_execute",
    description="Execute one bounded SILAS move with scoped edits",
    prompt=SILAS_EXECUTE_PROMPT,
    output_override={
        "type": "agent_inbox",
        "to_agent": "codex",
        "from_agent": "loop:silas_execute",
    },
    active_hooks={"stop": ["cognitive_space_stop_check"]},
    exit_condition=_exit_condition,
    on_start=_on_start,
    on_stop=_on_stop,
)
