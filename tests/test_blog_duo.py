"""Tests for the blog DUO (cave.core.publishing.blog_duo).

Mirrors the spawn-test pattern of test_blog_organ_nightly.py:
  - the DUO loop logic is tested with in-process STAND-IN dispatch seams
    (``_writer_dispatch`` / ``_eval_dispatch``) over tmp_path artifacts — no live
    heaven/minimax call — covering the four behaviors the commander asked for:
    terminate-on-eval-pass, terminate-on-budget, eval-revise-feeds-back, and
    freshness-enforced-per-cycle;
  - the real spawn+wall-clock-timeout dispatch (``_dispatch_agent``) is tested with
    MODULE-LEVEL stand-in child bodies (picklable by reference for the spawn context),
    exactly as the organ test does.
"""
import json
import os
import time
from unittest.mock import patch

import pytest

from cave.core.publishing import blog_duo as D
from cave.core.publishing import blog_rubric as R


_FULL_PROPS = {
    "aios_name": "doc-mirror",
    "aios_root": "/x",
    "journey_source": "/x/journal",
    "allowed_domain": "doc-mirror",
    "plugin_repo_url": "https://example/repo",
    # output_md_path is set per-test to a tmp file
}


def _bump_fresh(path):
    """Force an unambiguously-fresh mtime (decouples the freshness assertion from
    filesystem mtime granularity in fast in-process tests)."""
    t = time.time() + 100
    os.utime(path, (t, t))


def _all_pass_verdict():
    """A verdict covering every required dimension, all passed, each with evidence."""
    return {"verdict": "pass",
            "checks": [{"dimension": d, "pov": "all", "passed": True,
                        "evidence": "a verbatim quote", "finding": ""}
                       for d in R.REQUIRED_DIMENSIONS]}


def _fail_verdict(dim="everything_is_copy", finding="FIX_THE_HOOK_SENTENCE"):
    """Full-coverage verdict with exactly one dimension failed (carrying a finding)."""
    v = _all_pass_verdict()
    v["verdict"] = "revise"
    for c in v["checks"]:
        if c["dimension"] == dim:
            c["passed"] = False
            c["finding"] = finding
            c["evidence"] = ""
    return v


class _StubDuo:
    """In-process stand-ins for the writer + eval dispatch seams.

    The writer writes the three POV posts fresh (unless writer_writes=False); the eval
    writes the per-cycle verdict from a script. Both record their calls so tests can
    assert on cycles + feedback threading.
    """

    def __init__(self, targets, verdict_path, verdicts, writer_writes=True):
        self.targets = targets
        self.verdict_path = verdict_path
        self.verdicts = list(verdicts)
        self.writer_writes = writer_writes
        self.writer_commands = []
        self.writer_calls = 0
        self.eval_calls = 0

    def writer(self, command, name, max_tool_calls, timeout_s):
        self.writer_calls += 1
        self.writer_commands.append(command)
        if self.writer_writes:
            for t in self.targets:
                with open(t, "w") as f:
                    f.write("POST BODY")
                _bump_fresh(t)
        return (True, "", "fake-model")

    def evaluator(self, command, name, max_tool_calls, timeout_s):
        idx = self.eval_calls
        self.eval_calls += 1
        v = self.verdicts[idx] if idx < len(self.verdicts) else self.verdicts[-1]
        with open(self.verdict_path, "w") as f:
            f.write(json.dumps(v))
        _bump_fresh(self.verdict_path)
        return (True, "", "fake-model")


def _props(tmp_path):
    return dict(_FULL_PROPS, output_md_path=str(tmp_path / "post.md"))


def _stub_for(props, verdicts, writer_writes=True):
    out = props["output_md_path"]
    return _StubDuo(D._pov_targets(out), D._verdict_path(out), verdicts, writer_writes)


# ── pure helpers ─────────────────────────────────────────────────────────────
class TestPovTargets:
    def test_three_pov_siblings(self):
        assert D._pov_targets("/z/post.md") == [
            "/z/post.md", "/z/post-agent-pov.md", "/z/post-system-pov.md"]
        assert D._verdict_path("/z/post.md") == "/z/post.eval.json"


class TestDerivePass:
    """The gate DERIVES pass from the verdict's checks — never trusts the self-declared
    verdict field (the anti-false-completion gate). Lives in blog_rubric (the shared
    source both the in-loop challenger and the CI challenger compile from)."""

    def test_all_pass_with_evidence_passes(self):
        ok, why = R.derive_pass(_all_pass_verdict())
        assert ok and why == ""

    def test_any_failed_check_blocks(self):
        ok, why = R.derive_pass(_fail_verdict())
        assert not ok and "everything_is_copy" in why

    def test_missing_dimension_blocks_even_if_all_present_pass(self):
        v = _all_pass_verdict()
        v["checks"] = [c for c in v["checks"] if c["dimension"] != "youtube_script"]
        ok, why = R.derive_pass(v)
        assert not ok and "youtube_script" in why

    def test_self_declared_pass_with_no_checks_is_rejected(self):
        ok, why = R.derive_pass({"verdict": "pass", "checks": []})
        assert not ok

    def test_passing_check_without_evidence_is_rejected(self):
        v = _all_pass_verdict()
        v["checks"][0]["evidence"] = "   "  # ungrounded pass
        ok, why = R.derive_pass(v)
        assert not ok and "evidence" in why


class TestReadVerdict:
    def test_good_bad_and_missing(self, tmp_path):
        good = tmp_path / "g.json"
        good.write_text(json.dumps({"checks": []}))
        assert R.read_verdict(str(good)) == {"checks": []}

        bad = tmp_path / "b.json"
        bad.write_text("{not json")
        assert R.read_verdict(str(bad)) is None

        assert R.read_verdict(str(tmp_path / "missing.json")) is None


class TestReviseFeedback:
    def test_compiles_failed_checks_into_lines(self):
        fb = R.revise_feedback(_fail_verdict(finding="tighten hook"))
        assert "everything_is_copy" in fb and "tighten hook" in fb


class TestChallengerPrompt:
    """The CHALLENGER seat prompt is compiled from the shared rubric — the same builder
    the CI challenger uses (Isaac: 'a challenger who knows our rules')."""

    def test_prompt_carries_rubric_targets_and_verdict_path(self):
        targets = ["/z/post.md", "/z/post-agent-pov.md", "/z/post-system-pov.md"]
        p = R.build_challenger_prompt("doc-mirror", "/x/journal", targets, "/z/post.eval.json")
        assert "CHALLENGER" in p
        assert "youtube_script" in p and "everything_is_copy" in p  # rubric embedded
        assert "/z/post-agent-pov.md" in p                          # targets embedded
        assert "/z/post.eval.json" in p                             # verdict path embedded

    def test_render_rubric_lists_every_dimension(self):
        r = R.render_rubric()
        for dim in R.REQUIRED_DIMENSIONS:
            assert dim in r


# ── the DUO loop (in-process seams) ──────────────────────────────────────────
class TestRunDuoLoop:
    def test_terminates_on_eval_pass(self, tmp_path):
        props = _props(tmp_path)
        stub = _stub_for(props, [_all_pass_verdict()])
        result = D.run_duo(props, _writer_dispatch=stub.writer,
                           _eval_dispatch=stub.evaluator)
        assert result["status"] == "done"
        assert result["cycle"] == 1
        assert stub.writer_calls == 1 and stub.eval_calls == 1
        assert result["model"] == "fake-model"

    def test_terminates_on_budget(self, tmp_path):
        props = _props(tmp_path)
        stub = _stub_for(props, [_fail_verdict()])  # always fails -> never passes
        result = D.run_duo(props, max_cycles=3,
                           _writer_dispatch=stub.writer, _eval_dispatch=stub.evaluator)
        assert result["status"] == "budget_exhausted"
        assert result["cycles"] == 3
        assert stub.writer_calls == 3 and stub.eval_calls == 3
        assert "everything_is_copy" in result["last_reason"]

    def test_eval_revise_feeds_back(self, tmp_path):
        props = _props(tmp_path)
        # cycle 1 fails with a distinctive finding; cycle 2 passes.
        stub = _stub_for(props, [_fail_verdict(finding="FIX_THE_HOOK_SENTENCE"),
                                 _all_pass_verdict()])
        result = D.run_duo(props, max_cycles=3,
                           _writer_dispatch=stub.writer, _eval_dispatch=stub.evaluator)
        assert result["status"] == "done" and result["cycle"] == 2
        # cycle-1 goal has no revision block; cycle-2 goal carries the eval's finding.
        assert "REVISION CYCLE" not in stub.writer_commands[0]
        assert "REVISION CYCLE" in stub.writer_commands[1]
        assert "FIX_THE_HOOK_SENTENCE" in stub.writer_commands[1]

    def test_freshness_enforced_per_cycle(self, tmp_path):
        """A writer that reports ok but does NOT freshly write the posts fails the
        run at the writer stage — the eval is never even reached."""
        props = _props(tmp_path)
        stub = _stub_for(props, [_all_pass_verdict()], writer_writes=False)
        result = D.run_duo(props, _writer_dispatch=stub.writer,
                           _eval_dispatch=stub.evaluator)
        assert result["status"] == "failed" and result["stage"] == "writer"
        assert stub.eval_calls == 0

    def test_challenger_stale_verdict_fails(self, tmp_path):
        """Writer writes fresh posts, but the challenger leaves a STALE verdict (from
        before this cycle) -> the challenger stage fails (the ok-report-no-artifact trap)."""
        props = _props(tmp_path)
        out = props["output_md_path"]
        targets = D._pov_targets(out)
        verdict_path = D._verdict_path(out)

        # pre-write a stale verdict far in the past
        with open(verdict_path, "w") as f:
            f.write(json.dumps(_all_pass_verdict()))
        os.utime(verdict_path, (1000, 1000))

        def writer(command, name, max_tool_calls, timeout_s):
            for t in targets:
                with open(t, "w") as f:
                    f.write("POST")
                _bump_fresh(t)
            return (True, "", "fake-model")

        def evaluator(command, name, max_tool_calls, timeout_s):
            return (True, "", "fake-model")  # ok-report, but never (re)writes the verdict

        result = D.run_duo(props, _writer_dispatch=writer, _eval_dispatch=evaluator)
        assert result["status"] == "failed" and result["stage"] == "challenger"

    def test_missing_props_fails_validate(self, tmp_path):
        props = _props(tmp_path)
        del props["plugin_repo_url"]
        result = D.run_duo(props, _writer_dispatch=lambda *a, **k: (True, "", "m"),
                           _eval_dispatch=lambda *a, **k: (True, "", "m"))
        assert result["status"] == "failed" and result["stage"] == "validate"
        assert "plugin_repo_url" in result["error"]


# ── real spawn dispatch (wall-clock timeout) — module-level child bodies ──────
def _child_ok(config_kwargs, command, max_tool_calls, result_path):
    import json as _json
    from pathlib import Path as _P
    _P(result_path).write_text(_json.dumps({"ok": True, "error": ""}))


def _child_sleeper(config_kwargs, command, max_tool_calls, result_path):
    import time as _t
    _t.sleep(120)  # simulates the wedged-IPC hang: never returns in time


_MINIMAX_CFG = {"model": "fake-model",
                "extra_model_kwargs": {"anthropic_api_url": "https://fake.local"}}


class TestDispatchAgent:
    def test_child_result_roundtrip(self):
        with patch.object(D, "_minimax_model_config", return_value=_MINIMAX_CFG):
            ok, err, model = D._dispatch_agent("x", name="blog_duo_writer",
                                               max_tool_calls=5, timeout_s=30,
                                               _child_target=_child_ok)
        assert ok and err == "" and model == "fake-model"

    def test_wall_clock_timeout_kills_hung_child(self):
        t0 = time.time()
        with patch.object(D, "_minimax_model_config", return_value=_MINIMAX_CFG):
            ok, err, model = D._dispatch_agent("x", name="blog_duo_eval",
                                               max_tool_calls=5, timeout_s=3,
                                               _child_target=_child_sleeper)
        assert not ok
        assert "wall-clock timeout" in err and "KILLED" in err
        assert model == "fake-model"
        assert time.time() - t0 < 60

    def test_missing_minimax_config_gates_no_fallback(self):
        with patch.object(D, "_minimax_model_config", return_value={}):
            ok, err, model = D._dispatch_agent("x", name="blog_duo_writer",
                                               max_tool_calls=5)
        assert not ok and "minimax model config" in err
