"""SILAS assay loop for CAVE DNA."""
from typing import Any, Dict

from .base import create_loop


def _phase_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("silas_coreflow", {})


def _on_start(state: Dict[str, Any]) -> None:
    core = _phase_state(state)
    core["phase"] = "assay"
    core["assay_complete"] = False


def _on_stop(state: Dict[str, Any]) -> None:
    _phase_state(state)["last_stopped_phase"] = "assay"


def _exit_condition(state: Dict[str, Any]) -> bool:
    return bool(_phase_state(state).get("assay_complete"))


SILAS_ASSAY_PROMPT = """You are in SILAS_ASSAY.

Try to falsify the completed move. Run focused tests or file checks, inspect generated artifacts,
and identify fake completion. Mark assay complete only after the proof gate is satisfied or a
clear repair/ask-human decision exists."""


SILAS_ASSAY_LOOP = create_loop(
    name="silas_assay",
    description="Adversarially verify one SILAS move before persistence",
    prompt=SILAS_ASSAY_PROMPT,
    output_override={
        "type": "agent_inbox",
        "to_agent": "codex",
        "from_agent": "loop:silas_assay",
    },
    active_hooks={"stop": ["cognitive_space_stop_check"]},
    exit_condition=_exit_condition,
    on_start=_on_start,
    on_stop=_on_stop,
)
