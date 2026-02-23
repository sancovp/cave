"""Capability Resolver - Wire *graph RAG into CAVE hook system.

Provides capability recommendations based on context via unified RAG.

Note: Requires rag_tool_discovery package installed or RAG_TOOL_DISCOVERY_PATH env var set.
Install: pip install -e /tmp/rag_tool_discovery
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_rag_module = None


def _get_rag_module():
    """Lazy load RAG module with fallback paths."""
    global _rag_module
    if _rag_module is not None:
        return _rag_module

    try:
        from capability_predictor import unified_rag
        _rag_module = unified_rag
        return _rag_module
    except ImportError:
        pass

    rag_path = os.environ.get("RAG_TOOL_DISCOVERY_PATH", "/tmp/rag_tool_discovery")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "unified_rag",
            f"{rag_path}/capability_predictor/unified_rag.py"
        )
        if spec and spec.loader:
            _rag_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_rag_module)
            return _rag_module
    except Exception:
        logger.exception("Could not load RAG module")

    return None


def resolve_capabilities(query: str, compact: bool = True) -> Optional[str]:
    """
    Resolve capabilities for a query using unified *graph RAG.

    Args:
        query: Natural language describing what the agent wants to do
        compact: If True, return condensed output

    Returns:
        Formatted capability recommendations, or None if RAG unavailable
    """
    rag = _get_rag_module()
    if rag is None:
        return None

    try:
        return rag.get_capability_context(query, compact=compact)
    except Exception:
        logger.exception("Capability resolution failed")
        return None


def extract_query_from_hook_payload(payload: dict) -> Optional[str]:
    """
    Extract a capability query from hook payload.

    For PreToolUse: use tool_name + tool_input to form query
    For PostToolUse: use tool_name + result summary
    For Stop: use any user message content
    """
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool_name == "Task":
        return tool_input.get("prompt", "")[:200]

    if tool_name in ("Read", "Glob", "Grep"):
        return None

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return f"bash command: {cmd[:100]}" if cmd else None

    if tool_input:
        input_str = str(tool_input)[:150]
        return f"{tool_name}: {input_str}"

    return None


def get_capability_context_for_hook(
    hook_type: str,
    payload: dict,
    enabled: bool = True
) -> Optional[str]:
    """
    Main entry point for hook integration.

    Args:
        hook_type: pretooluse, posttooluse, stop, etc.
        payload: Hook payload with tool_name, tool_input, etc.
        enabled: Feature flag to disable RAG

    Returns:
        Capability context string to inject, or None
    """
    if not enabled:
        return None

    if hook_type not in ("pretooluse", "stop"):
        return None

    query = extract_query_from_hook_payload(payload)
    if not query:
        return None

    return resolve_capabilities(query, compact=True)
