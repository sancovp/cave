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
        """A successful heaven dispatch + FRESH artifact flips the node to done with model set."""
        carton, set_props, _ = _stub_carton_one_pending(_FULL_PROPS)
        with patch.object(B, "_carton", return_value=carton), \
             patch.object(B, "_read_props", return_value=dict(_FULL_PROPS)), \
             patch.object(B, "_build_prompt", return_value="PROMPT"), \
             patch.object(B, "_run_agent", return_value=(True, "", "MiniMax-M2.7-highspeed")), \
             patch.object(B, "_artifact_fresh", return_value=True):
            result = B.fire_blog_organ()

        assert result["status"] == "done"
        # the node was flipped done with the resolved minimax model (no model_todo)
        flip = set_props.call_args[0][1]
        assert flip["status"] == "done"
        assert flip["model"] == "MiniMax-M2.7-highspeed"
        assert "model_todo" not in flip

    def test_stale_artifact_flips_failed(self):
        """ok-report + STALE artifact = the ok-report-no-artifact trap (live
        2026-07-12: a halted run 'succeeded' against the prior run's file) —
        the node must flip failed, never done."""
        carton, set_props, _ = _stub_carton_one_pending(_FULL_PROPS)
        with patch.object(B, "_carton", return_value=carton), \
             patch.object(B, "_read_props", return_value=dict(_FULL_PROPS)), \
             patch.object(B, "_build_prompt", return_value="PROMPT"), \
             patch.object(B, "_run_agent", return_value=(True, "", "MiniMax-M2.7-highspeed")), \
             patch.object(B, "_artifact_fresh", return_value=False):
            result = B.fire_blog_organ()

        assert result["status"] == "failed"
        assert "not freshly written" in result["error"]

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


# ── dispatch wall-clock timeout (the 2026-07-12 hang class) ──────────────────
# Stand-in child bodies at MODULE level: the spawn context pickles the target
# by reference, so the child re-imports this test module to find them.

def _child_sleeper(config_kwargs, prompt, max_tool_calls, result_path):
    import time as _t
    _t.sleep(120)  # simulates the wedged-IPC hang: never returns in time


def _child_ok(config_kwargs, prompt, max_tool_calls, result_path):
    import json as _json
    from pathlib import Path as _P
    _P(result_path).write_text(_json.dumps({"ok": True, "error": ""}))


_MINIMAX_CFG = {"model": "fake-model",
                "extra_model_kwargs": {"anthropic_api_url": "https://fake.local"}}


class TestDispatchTimeout:
    """_run_agent must NEVER hang forever: the live 2026-07-12 hang wedged a
    blocking IPC read ON the event-loop thread, so only the out-of-process
    kill (child process + parent deadline) can catch the class."""

    def test_wall_clock_timeout_kills_hung_child(self):
        import time
        t0 = time.time()
        with patch.object(B, "_minimax_model_config", return_value=_MINIMAX_CFG):
            ok, err, model = B._run_agent("x", timeout_s=3,
                                          _child_target=_child_sleeper)
        assert not ok
        assert "wall-clock timeout" in err and "KILLED" in err
        assert model == "fake-model"
        assert time.time() - t0 < 60  # killed at the deadline, not after 120s

    def test_child_result_roundtrip(self):
        with patch.object(B, "_minimax_model_config", return_value=_MINIMAX_CFG):
            ok, err, model = B._run_agent("x", timeout_s=30,
                                          _child_target=_child_ok)
        assert ok and err == "" and model == "fake-model"


class TestArtifactFresh:
    def test_fresh_stale_and_missing(self, tmp_path):
        import time
        f = tmp_path / "a.md"
        f.write_text("x")
        now = time.time()
        assert B._artifact_fresh(str(f), now - 5)          # written after t0
        assert not B._artifact_fresh(str(f), now + 5)      # stale vs t0
        assert not B._artifact_fresh(str(tmp_path / "missing.md"), 0)
