"""Container Registration — reusable primitives for inter-container messaging.

Any container running a CAVEHTTPServer (or any HTTP server) can register
with a parent sancrev instance to be reachable via the agent relay.

Usage (inside a container on startup):
    from cave.core.container_registration import register_with_parent

    register_with_parent(
        parent_url="http://host.docker.internal:8080",
        agent_id="grug",
        local_port=8081,
        metadata={"type": "worker", "container": "repo-lord"},
    )

Then the parent relays messages via:
    POST /agents/grug/execute  → forwarded to http://container:8081/execute
    POST /agents/grug/inject   → forwarded to http://container:8081/self/inject

These primitives are NOT specific to PAIAs or Observatory.
Any containerized agent uses the same pattern.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def register_with_parent(
    parent_url: str,
    agent_id: str,
    local_port: int,
    local_host: str = "0.0.0.0",
    paia_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register this container's agent with a parent sancrev instance.

    Calls POST /agents/register on the parent. After registration,
    the parent can relay messages to this container via /agents/{agent_id}/*.

    Args:
        parent_url: URL of parent sancrev (e.g. "http://host.docker.internal:8080")
        agent_id: Unique agent identifier (e.g. "grug")
        local_port: Port this container's HTTP server runs on
        local_host: Bind address (default 0.0.0.0)
        paia_name: Optional PAIA name for the registry
        metadata: Optional metadata dict

    Returns:
        Registration result from parent, or error dict
    """
    import httpx

    # Build the address the parent should relay to.
    # From the parent's perspective, this container is reachable at its
    # Docker network address. We use the container's hostname.
    import socket
    container_hostname = socket.gethostname()
    address = f"http://{container_hostname}:{local_port}"

    registration = {
        "agent_id": agent_id,
        "address": address,
        "paia_name": paia_name,
        "metadata": metadata or {},
    }

    try:
        resp = httpx.post(
            f"{parent_url}/agents/register",
            json=registration,
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info("Registered with parent %s as %s (address=%s)", parent_url, agent_id, address)
        return result
    except Exception as e:
        logger.error("Failed to register with parent %s: %s", parent_url, e)
        return {"error": str(e)}


def deregister_from_parent(parent_url: str, agent_id: str) -> Dict[str, Any]:
    """Deregister this container's agent from the parent.

    Args:
        parent_url: URL of parent sancrev
        agent_id: Agent to deregister

    Returns:
        Result dict or error
    """
    import httpx

    try:
        resp = httpx.delete(
            f"{parent_url}/agents/{agent_id}",
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info("Deregistered %s from parent %s", agent_id, parent_url)
        return result
    except Exception as e:
        logger.error("Failed to deregister %s: %s", agent_id, e)
        return {"error": str(e)}


def health_check_parent(parent_url: str) -> bool:
    """Check if parent sancrev is reachable.

    Args:
        parent_url: URL of parent sancrev

    Returns:
        True if parent responds to /health
    """
    import httpx

    try:
        resp = httpx.get(f"{parent_url}/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False
