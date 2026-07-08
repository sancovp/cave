"""Tests for the nightly blog organ (cave.core.publishing.blog_organ_nightly).

Covers the no-pending no-op path WITHOUT hitting the live graph: the carton
connection + query primitive are patched (same mock style as
test_conductor_routing). The organ should query for pending Blog_Request nodes,
find none, and return a quiet {"status": "no_pending"} without dispatching an agent.
"""
from unittest.mock import patch, MagicMock

import pytest

from cave.core.publishing import blog_organ_nightly as B


def _stub_carton(query_results):
    """Build a (graph, set_props, query) triple where query returns query_results.

    Returns the tuple plus the set_props + query mocks so tests can assert on them.
    """
    graph = MagicMock(name="graph")
    set_props = MagicMock(name="set_concept_properties")
    query = MagicMock(name="query_concepts_by_properties",
                      return_value={"success": True, "results": query_results})
    return (graph, set_props, query), set_props, query


class TestNoPendingNoOp:
    """fire_blog_organ returns a quiet no-op when nothing is pending."""

    def test_no_pending_returns_no_op(self):
        carton, set_props, query = _stub_carton(query_results=[])
        with patch.object(B, "_carton", return_value=carton), \
             patch.object(B, "_run_agent") as run_agent:
            result = B.fire_blog_organ()

        assert result == {"status": "no_pending"}
        # no node was flipped and no agent was dispatched
        set_props.assert_not_called()
        run_agent.assert_not_called()

    def test_query_failure_is_treated_as_no_pending(self):
        """A failed query (e.g. transient) yields no candidate -> quiet no-op, no dispatch."""
        graph = MagicMock()
        set_props = MagicMock()
        query = MagicMock(return_value={"success": False, "error": "boom", "results": []})
        with patch.object(B, "_carton", return_value=(graph, set_props, query)), \
             patch.object(B, "_run_agent") as run_agent:
            result = B.fire_blog_organ()

        assert result == {"status": "no_pending"}
        run_agent.assert_not_called()

    def test_no_connection_returns_no_connection(self):
        """When carton cannot connect, the organ no-ops with {"status": "no_connection"}."""
        with patch.object(B, "_carton", return_value=(None, None, None)), \
             patch.object(B, "_run_agent") as run_agent:
            result = B.fire_blog_organ()

        assert result == {"status": "no_connection"}
        run_agent.assert_not_called()


_FULL_PROPS = {
    "aios_name": "doc-mirror",
    "aios_root": "/x",
    "journey_source": "/x/journal",
    "allowed_domain": "doc-mirror",
    "plugin_repo_url": "https://example/repo",
    "output_md_path": "/tmp/blog_organ_test_out.md",
    "created": "2026-06-10T00:00:00",
}


def _stub_carton_one_pending(props):
    """A carton triple whose query returns ONE pending node, and re-reads its full props."""
    graph = MagicMock(name="graph")
    set_props = MagicMock(name="set_concept_properties")
    query = MagicMock(return_value={"success": True, "results": [{"n": "Blog_Request_X"}]})
    return (graph, set_props, query), set_props, query


class TestHeavenDispatchSeam:
    """The dispatch seam now runs the agent on heaven/minimax and returns (ok, err, model)."""

    def test_success_flips_done_with_model(self):
        """A successful heaven dispatch + written artifact flips the node to done with model set."""
        carton, set_props, _ = _stub_carton_one_pending(_FULL_PROPS)
        with patch.object(B, "_carton", return_value=carton), \
             patch.object(B, "_read_props", return_value=dict(_FULL_PROPS)), \
             patch.object(B, "_build_prompt", return_value="PROMPT"), \
             patch.object(B, "_run_agent", return_value=(True, "", "MiniMax-M2.7-highspeed")), \
             patch.object(B.Path, "exists", return_value=True):
            result = B.fire_blog_organ()

        assert result["status"] == "done"
        # the node was flipped done with the resolved minimax model (no model_todo)
        flip = set_props.call_args[0][1]
        assert flip["status"] == "done"
        assert flip["model"] == "MiniMax-M2.7-highspeed"
        assert "model_todo" not in flip

    def test_missing_minimax_config_flips_failed_no_fallback(self):
        """If the minimax model config is absent, _run_agent gates -> node flips failed (no claude -p fallback)."""
        carton, set_props, _ = _stub_carton_one_pending(_FULL_PROPS)
        with patch.object(B, "_carton", return_value=carton), \
             patch.object(B, "_read_props", return_value=dict(_FULL_PROPS)), \
             patch.object(B, "_build_prompt", return_value="PROMPT"), \
             patch.object(B, "_minimax_model_config", return_value={}):
            result = B.fire_blog_organ()

        assert result["status"] == "failed"
        assert "minimax model config" in result["error"]
        flip = set_props.call_args[0][1]
        assert flip["status"] == "failed"
