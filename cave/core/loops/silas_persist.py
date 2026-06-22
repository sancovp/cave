"""SILAS persistence loop for CAVE DNA."""
from typing import Any, Dict

from .base import create_loop


def _phase_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("silas_coreflow", {})


def _on_start(state: Dict[str, Any]) -> None:
    core = _phase_state(state)
    core["phase"] = "persist"
    core["persist_complete"] = False


def _on_stop(state: Dict[str, Any]) -> None:
    _phase_state(state)["last_stopped_phase"] = "persist"


def _exit_condition(state: Dict[str, Any]) -> bool:
    return bool(_phase_state(state).get("persist_complete"))


SILAS_PERSIST_PROMPT = """You are in SILAS_PERSIST.

Persist what future runs need: evidence entries, context ledger updates, queue changes, Scores,
or skill/map updates. Do not write a diary transcript. Write replayable state that lets the next
run learn from this one."""


SILAS_PERSIST_LOOP = create_loop(
    name="silas_persist",
    description="Persist evidence, context, queue, and replay state after a SILAS move",
    prompt=SILAS_PERSIST_PROMPT,
    output_override={
        "type": "agent_inbox",
        "to_agent": "codex",
        "from_agent": "loop:silas_persist",
    },
    active_hooks={"stop": ["cognitive_space_stop_check"]},
    exit_condition=_exit_condition,
    on_start=_on_start,
    on_stop=_on_stop,
)
