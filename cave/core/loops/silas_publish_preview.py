"""SILAS preview publishing loop for CAVE DNA."""
from typing import Any, Dict

from .base import create_loop


def _phase_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("silas_coreflow", {})


def _on_start(state: Dict[str, Any]) -> None:
    core = _phase_state(state)
    core["phase"] = "publish_preview"
    core["publish_preview_complete"] = False


def _on_stop(state: Dict[str, Any]) -> None:
    _phase_state(state)["last_stopped_phase"] = "publish_preview"


def _exit_condition(state: Dict[str, Any]) -> bool:
    return bool(_phase_state(state).get("publish_preview_complete"))


SILAS_PUBLISH_PREVIEW_PROMPT = """You are in SILAS_PUBLISH_PREVIEW.

If an attention artifact passes the proof gate, publish it only to the GitHub Pages preview site
under docs/. Update the feed and artifact queue. Do not auto-post to LinkedIn, X, Discord, email,
or external communities."""


SILAS_PUBLISH_PREVIEW_LOOP = create_loop(
    name="silas_publish_preview",
    description="Publish proof-gated SILAS attention artifacts to the preview site only",
    prompt=SILAS_PUBLISH_PREVIEW_PROMPT,
    output_override={
        "type": "agent_inbox",
        "to_agent": "codex",
        "from_agent": "loop:silas_publish_preview",
    },
    active_hooks={"stop": ["cognitive_space_stop_check"]},
    exit_condition=_exit_condition,
    on_start=_on_start,
    on_stop=_on_stop,
)
