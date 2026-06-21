"""CAVE Cognition MCP - tool surface for cognitive spaces and loop shapes."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests
from fastmcp import FastMCP


mcp = FastMCP("cave-cognition", "Construct CAVE cognitive spaces and reified AgentInferenceLoop shapes")

CAVE_URL = os.environ.get("CAVE_URL", "http://localhost:18765")


def _get(endpoint: str) -> dict:
    resp = requests.get(f"{CAVE_URL}{endpoint}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, data: Optional[dict] = None) -> dict:
    resp = requests.post(f"{CAVE_URL}{endpoint}", json=data or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _delete(endpoint: str) -> dict:
    resp = requests.delete(f"{CAVE_URL}{endpoint}", timeout=10)
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def cognition_create_loop(
    name: str,
    description: str = "",
    prompt: str = "",
    provider: str = "codex",
    output_override: Optional[Dict[str, Any]] = None,
    active_hooks: Optional[Dict[str, list[str]]] = None,
    phase_graph: Optional[Dict[str, Any]] = None,
    required_files: Optional[list[str]] = None,
    kv_defaults: Optional[Dict[str, Any]] = None,
    verification_gates: Optional[list[Any]] = None,
    exit_policy: Optional[Dict[str, Any]] = None,
    next: Optional[str] = None,
) -> dict:
    """Create a durable reified AgentInferenceLoop shape."""
    return _post("/cognition/loops", {
        "name": name,
        "description": description,
        "prompt": prompt,
        "provider": provider,
        "output_override": output_override,
        "active_hooks": active_hooks,
        "phase_graph": phase_graph,
        "required_files": required_files,
        "kv_defaults": kv_defaults,
        "verification_gates": verification_gates,
        "exit_policy": exit_policy,
        "next": next,
    })


@mcp.tool()
def cognition_get_loop(loop_id: str) -> dict:
    """Load a reified AgentInferenceLoop shape by id."""
    return _get(f"/cognition/loops/{loop_id}")


@mcp.tool()
def cognition_create_space(
    name: str = "cognitive_space",
    provider: str = "codex",
    loop_id: Optional[str] = None,
    phase: str = "observe",
    active_shape: Optional[Dict[str, Any]] = None,
    prompt_path: Optional[str] = None,
    kv: Optional[Dict[str, Any]] = None,
    evidence_files: Optional[list[str]] = None,
    verification_gates: Optional[list[Any]] = None,
    stop_conditions: Optional[Dict[str, Any]] = None,
    next_action: Optional[str] = None,
    set_current: bool = True,
) -> dict:
    """Create a cognitive space and optionally make it current."""
    return _post("/cognition/spaces", {
        "name": name,
        "provider": provider,
        "loop_id": loop_id,
        "phase": phase,
        "active_shape": active_shape,
        "prompt_path": prompt_path,
        "kv": kv,
        "evidence_files": evidence_files,
        "verification_gates": verification_gates,
        "stop_conditions": stop_conditions,
        "next_action": next_action,
        "set_current": set_current,
    })


@mcp.tool()
def cognition_current_space() -> dict:
    """Return the current cognitive-space payload and JSON path."""
    return _get("/cognition/spaces/current")


@mcp.tool()
def cognition_get_space(space_id: str) -> dict:
    """Load a cognitive space by id."""
    return _get(f"/cognition/spaces/{space_id}")


@mcp.tool()
def cognition_put_kv(
    key: Optional[str] = None,
    value: Any = None,
    updates: Optional[Dict[str, Any]] = None,
    space_id: Optional[str] = None,
) -> dict:
    """Update KV state on the current or selected cognitive space."""
    payload = {"key": key, "value": value, "updates": updates}
    if space_id:
        return _post(f"/cognition/spaces/{space_id}/kv", payload)
    return _post("/cognition/kv", payload)


@mcp.tool()
def cognition_add_evidence(path: str, space_id: str) -> dict:
    """Register an evidence file with a cognitive space."""
    return _post(f"/cognition/spaces/{space_id}/evidence", {"path": path})


@mcp.tool()
def cognition_stop_check(space_id: Optional[str] = None) -> dict:
    """Run the CAVE cognitive-space stop-check and return gates/path."""
    return _post("/cognition/stop-check", {"space_id": space_id})


@mcp.tool()
def cognition_install_stop_hook(activate: bool = False) -> dict:
    """Install and optionally activate CAVE's cognitive-space Stop hook."""
    return _post("/cognition/install-stop-hook", {"activate": activate})


@mcp.tool()
def aios_status() -> dict:
    """Return read-only SILAS AIOS status through CAVE."""
    return _get("/aios/status")


@mcp.tool()
def aios_next_action() -> dict:
    """Return the current SILAS AIOS next-action text."""
    return _get("/aios/next-action")


@mcp.tool()
def aios_search(query: str, domain: str = "all", limit: int = 8) -> dict:
    """Search AIOS, Codex skills, or Scores through CAVE."""
    return _post("/aios/search", {"query": query, "domain": domain, "limit": limit})


@mcp.tool()
def aios_select_next(limit: int = 8) -> dict:
    """Select the next lawful AIOS move and advisory DNASequence."""
    return _post("/aios/select", {"limit": limit})


@mcp.tool()
def aios_gate(candidate_id: Optional[str] = None, limit: int = 8) -> dict:
    """Check whether an AIOS candidate is lawful to execute now."""
    return _post("/aios/gate", {"candidate_id": candidate_id, "limit": limit})


@mcp.tool()
def aios_skilltree_project(command: str = "doctor", write_map: bool = False) -> dict:
    """Run project-local skilltree catalog, doctor, or map behavior."""
    return _post("/aios/skilltree/project", {"command": command, "write_map": write_map})


@mcp.tool()
def aios_skilltree_lab(command: str = "run") -> dict:
    """Run the AIOS runtime skilltree lab."""
    return _post("/aios/skilltree/lab", {"command": command})


@mcp.tool()
def dna_create_config(
    name: str,
    loop_names: list[str],
    exit_behavior: str = "one_shot",
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    set_current: bool = False,
) -> dict:
    """Create a durable AutoModeDNA config; loop_names can include dna:<config> refs."""
    return _post("/dna/configs", {
        "name": name,
        "loop_names": loop_names,
        "exit_behavior": exit_behavior,
        "description": description,
        "metadata": metadata,
        "set_current": set_current,
    })


@mcp.tool()
def dna_list_configs() -> dict:
    """List selectable AutoModeDNA configs."""
    return _get("/dna/configs")


@mcp.tool()
def dna_current_config() -> dict:
    """Return the currently selected AutoModeDNA config."""
    return _get("/dna/configs/current")


@mcp.tool()
def dna_select_config(name: str) -> dict:
    """Select a named AutoModeDNA config as current."""
    return _post(f"/dna/configs/{name}/select")


@mcp.tool()
def dna_start_config(name: str) -> dict:
    """Start a named AutoModeDNA config."""
    return _post(f"/dna/configs/{name}/start")


@mcp.tool()
def dna_start_current_config() -> dict:
    """Start the currently selected AutoModeDNA config."""
    return _post("/dna/configs/current/start")


@mcp.tool()
def dna_set_sequence(
    steps: list[Any],
    name: str = "current",
    description: str = "",
    mode: str = "advisory",
    metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """Set the live DNA follow-through sequence."""
    return _post("/dna/sequence", {
        "name": name,
        "description": description,
        "mode": mode,
        "steps": steps,
        "metadata": metadata,
    })


@mcp.tool()
def dna_get_sequence() -> dict:
    """Get the live DNA follow-through sequence."""
    return _get("/dna/sequence")


@mcp.tool()
def dna_clear_sequence() -> dict:
    """Clear the live DNA follow-through sequence."""
    return _delete("/dna/sequence")


@mcp.tool()
def dna_next_step() -> dict:
    """Get the next incomplete DNA sequence step."""
    return _get("/dna/sequence/next")


@mcp.tool()
def dna_complete_step(
    step_id: Optional[str] = None,
    status: str = "completed",
    summary: str = "",
    evidence_files: Optional[list[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """Mark a DNA sequence step complete/skipped/in-progress."""
    return _post("/dna/sequence/complete", {
        "step_id": step_id,
        "status": status,
        "summary": summary,
        "evidence_files": evidence_files,
        "metadata": metadata,
    })


@mcp.tool()
def dna_sequence_stop_check() -> dict:
    """Return Stop-hook enforcement state for the live DNA sequence."""
    return _get("/dna/sequence/stop-check")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
