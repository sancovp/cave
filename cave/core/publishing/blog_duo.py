"""Blog DUO — the blog organ matured into a WRITER + EVAL duo (the "evalchain dude").

Isaac (2026-07-12, verbatim): "the blog writer may need to be a DUO actually. it
may need an evalchain dude. this might be the first thing where we really actually
need it. this agent needs to be running with max iterations 15 or so on top of max
tool calls 40. 300-400 api calls for writing a blog post that is good is probably
enough. this is also going to BE the youtube script dont you realize that????"

WHAT THE DUO IS (the shape): a BOUNDED write -> eval -> revise loop, exactly the
``cave_teams.algebra.gate`` primitive (``algebra.py:72`` — "μ bounded fixpoint: run
body, then evaluator φ; loop until φ sets ctx[approval_key] or max_cycles") /
``topologies.loop_refine`` (worker + critic). Here **body = the WRITER**, **φ = the
EVAL**:

  * WRITER (heaven/MINIMAX M3) runs in heaven AGENT MODE — ``agent goal=<prompt>,
    iterations=15`` — where ``max_tool_calls`` is the cap PER iteration
    (``baseheavenagent.py:4130`` ``_detect_agent_command`` + ``:4160``). So "max
    iterations 15 on top of max tool calls 40" is literally that. It FILLS the
    JourneyCore model and runs the deterministic renderer (it never hand-writes the
    blog) — one POV per pass, three POV posts, per the PROVEN narrative-blog-from-aios
    prompt. On a REVISE cycle its goal carries the eval's per-dimension findings.
  * EVAL (a SEPARATE, un-primed heaven dispatch) reads the ARTIFACTS the writer wrote
    — NEVER the writer's claims — grades them against a RUBRIC compiled from the blog
    laws, and WRITES a structured verdict JSON. This is the external gate:
    meta-prompt-engineering — "You cannot self-correct because self-correction uses
    the same mechanism that produced the error. External gates must catch you." And
    the catastrophe-engineering False-Completion cure: ground-truth reconciliation
    (Claims? <-> State?) every cycle — the orchestrator DERIVES pass from the eval's
    per-check booleans + evidence, never from a self-declared "done".

Why a DUO and not one agent (the design-record convergence, per the CartON Organ
concept): an organ BECOMES A DUO when wrapped with an OBSERVER. This build is the
blog organ maturing into exactly that — the nightly organ (blog_organ_nightly) is the
single-shot writer; wrapping it with an evaluating observer is the DUO.

ISOLATION: both roles dispatch through the SAME proven spawn-isolated pattern as
``blog_organ_nightly._run_agent`` — a spawned child process killed after a wall-clock
deadline (the 2026-07-12 hang class: a blocking IPC read wedged on the event-loop
thread; no in-process timeout can fire for that class, only an out-of-process kill).

BUDGET (Isaac: ~300-400 API calls for one good post): the loop is bounded by
``max_cycles`` (default 5). One writer dispatch (agent-mode, <=15 iterations) + one
eval dispatch per cycle keeps a full run inside that envelope.

This module ORCHESTRATES ONLY. It does not touch ``blog_organ_nightly`` and is not
wired into ``fire_blog_organ`` — wiring + the live MiniMax run are the commander's
verification step. Reused (never re-implemented) from ``blog_organ_nightly``: the
minimax model config reader, the filled blog-organ prompt builder, the artifact
freshness gate, and the required-properties contract.
"""

import json
import logging
import multiprocessing
import os
import tempfile
import time
from pathlib import Path

# Reuse (do NOT duplicate) the proven organ primitives.
from cave.core.publishing.blog_organ_nightly import (
    _minimax_model_config,
    _build_prompt,
    _artifact_fresh,
    REQUIRED_PROPS,
    MINIMAX_CONFIG_PATH,
    DEFAULT_DISPATCH_TIMEOUT_S,
)
# THE CHALLENGER is compiled from the ONE shared rubric (blog_rubric) — the same
# source the CI challenger compiles from, so the inner gate and the outer gate can
# never drift. See blog_rubric.py.
from cave.core.publishing.blog_rubric import (
    RUBRIC_DIMENSIONS,
    REQUIRED_DIMENSIONS,
    build_challenger_prompt,
    read_verdict,
    derive_pass,
    revise_feedback,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── DUO knobs (Isaac's numbers; env-overridable) ────────────────────────────
# max_cycles bounds the whole run to ~300-400 API calls; the writer runs in agent
# mode with iterations=15 and 40 tool calls PER iteration (baseheavenagent:4160).
DEFAULT_MAX_CYCLES = int(os.environ.get("BLOG_DUO_MAX_CYCLES", "5"))
DEFAULT_WRITER_ITERATIONS = int(os.environ.get("BLOG_DUO_WRITER_ITERATIONS", "15"))
DEFAULT_WRITER_MAX_TOOL_CALLS = int(os.environ.get("BLOG_DUO_WRITER_MAX_TOOL_CALLS", "40"))
DEFAULT_EVAL_MAX_TOOL_CALLS = int(os.environ.get("BLOG_DUO_EVAL_MAX_TOOL_CALLS", "25"))


# The RUBRIC_DIMENSIONS / REQUIRED_DIMENSIONS live in blog_rubric (imported above) —
# the single source the in-loop challenger and the CI challenger both compile from.


# ── POV targets — the three fixpoint posts (matches the blog prompt STEP 2) ──
def _pov_targets(output_md_path):
    """The three POV artifacts the writer must produce, from the primary output path.

    Mirrors the renderer loop in the narrative-blog-from-aios prompt: the primary
    (USER) post at output_md_path, plus sibling ``-agent-pov.md`` / ``-system-pov.md``.
    """
    base = output_md_path.rsplit(".", 1)[0]
    return [output_md_path, base + "-agent-pov.md", base + "-system-pov.md"]


def _verdict_path(output_md_path):
    """Where the EVAL writes its structured verdict artifact (sibling of the post)."""
    return output_md_path.rsplit(".", 1)[0] + ".eval.json"


# ── the spawn-isolated dispatch (the proven blog_organ_nightly._run_agent shape) ──
def _dispatch_child(config_kwargs, command, max_tool_calls, result_path):
    """Child-process body: run ONE heaven/minimax dispatch, write the outcome JSON.

    Module-level (picklable for the spawn context); heavy imports happen HERE. Same
    body as ``blog_organ_nightly._dispatch_child`` — ``command`` is the agent-mode
    string ``agent goal=..., iterations=N`` (writer) OR a plain completion prompt
    (eval). Writes {"ok": bool, "error": str}; a missing result file means the child
    died before finishing (the parent reports that loudly).
    """
    import asyncio

    out = {"ok": False, "error": "child died before writing a result"}
    try:
        from heaven_base.baseheavenagent import BaseHeavenAgent, HeavenAgentConfig
        from heaven_base.unified_chat import UnifiedChat
        from heaven_base.tools import BashTool
        from heaven_base.docs.examples.heaven_callbacks import BackgroundEventCapture

        config = HeavenAgentConfig(tools=[BashTool], **config_kwargs)

        async def _dispatch():
            agent = BaseHeavenAgent(
                config=config,
                unified_chat=UnifiedChat(),
                max_tool_calls=max_tool_calls,
            )
            capture = BackgroundEventCapture()
            return await agent.run(prompt=command, heaven_main_callback=capture)

        asyncio.run(_dispatch())
        out = {"ok": True, "error": ""}
    except Exception as e:  # heaven dispatch failure — capture literally, NO fallback
        import traceback
        out = {"ok": False,
               "error": f"heaven minimax dispatch failed: {e}\n" + traceback.format_exc()}
    Path(result_path).write_text(json.dumps(out))


def _dispatch_agent(command, name, max_tool_calls, timeout_s=None, _child_target=None):
    """Dispatch ONE heaven/MINIMAX agent in a spawned child killed at a wall-clock deadline.

    The SAME proven pattern as ``blog_organ_nightly._run_agent``: resolve the minimax
    model (``BLOG_ORGAN_MODEL`` override, else the WD ``journal_agent_config.json``
    model — Isaac: "call m3"), build a ``HeavenAgentConfig`` with BashTool, spawn a
    child, and kill it out-of-process if it exceeds ``timeout_s`` (the only cure for the
    2026-07-12 wedged-IPC hang class). ``_child_target`` is a test seam.

    Returns (ok: bool, error: str, model: str). error is "" on success. Fails LOUD —
    no claude-p / no silent fallback.
    """
    timeout_s = DEFAULT_DISPATCH_TIMEOUT_S if timeout_s is None else timeout_s
    cfg = _minimax_model_config()
    model = os.environ.get("BLOG_ORGAN_MODEL") or cfg.get("model", "")
    api_url = cfg.get("extra_model_kwargs", {}).get("anthropic_api_url", "")
    if not (model and api_url):
        return (False,
                f"minimax model config missing/incomplete at {MINIMAX_CONFIG_PATH} "
                f"(model={model!r}, anthropic_api_url={api_url!r})",
                model)

    config_kwargs = dict(
        name=name,
        system_prompt="",  # the whole instruction is the command (the writer/eval prompt)
        model=model,
        use_uni_api=cfg.get("use_uni_api", False),
        max_tokens=int(os.environ.get(
            "BLOG_DUO_MAX_TOKENS", os.environ.get("BLOG_ORGAN_MAX_TOKENS", "16000"))),
        extra_model_kwargs={"anthropic_api_url": api_url},
        **({"provider": cfg["provider"]} if cfg.get("provider") else {}),
    )

    fd, result_path = tempfile.mkstemp(prefix=f"blog_duo_{name}_", suffix=".json")
    os.close(fd)
    os.unlink(result_path)  # the child writing it back IS the success signal
    ctx = multiprocessing.get_context("spawn")  # clean interpreter, fork-safe
    proc = ctx.Process(target=_child_target or _dispatch_child,
                       args=(config_kwargs, command, max_tool_calls, result_path))
    try:
        proc.start()
        proc.join(timeout_s)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            logger.error("%s dispatch exceeded %ss wall-clock — KILLED", name, timeout_s)
            return (False,
                    f"{name} dispatch exceeded wall-clock timeout {timeout_s}s and was "
                    "KILLED (the 2026-07-12 hang class: a blocking IPC read wedged on "
                    "the event-loop thread — only an out-of-process kill can catch it)",
                    model)
        result_file = Path(result_path)
        if not result_file.exists():
            return (False,
                    f"{name} dispatch child exited (code {proc.exitcode}) without "
                    "writing a result — child crashed", model)
        out = json.loads(result_file.read_text())
        if not out.get("ok"):
            logger.error("%s (heaven minimax) failed: %s", name, out.get("error"))
        return bool(out.get("ok")), str(out.get("error", "")), model
    finally:
        Path(result_path).unlink(missing_ok=True)


# ── prompt builders (meta-prompt-engineering bridge-distance discipline) ─────
# The laws are the CONSTRAINT scaffold; the journey source is the ONLY content well;
# the eval feedback is a CONSTRAIN(task) that forces the writer to REACH into the
# source at the exact weak spots (never template-fill the feedback's own prose).

_REVISION_BLOCK = """

## ==== REVISION CYCLE — the EVAL rejected the prior draft ====

Your previous posts exist on disk at these paths (READ them first, then FIX them):
{targets}

The EVAL (a separate, un-primed reader) graded your posts against the blog laws and
found these DIMENSION FAILURES — you MUST address EACH one:

{feedback}

HOW TO REVISE (do NOT template-fill the findings' words — REACH into the journey
source and fix the underlying fill):
- For each finding, re-derive the affected fill from the JOURNEY SOURCE under the laws
  in this prompt — do NOT blindly re-render the prior core (that is the banned
  reuse-a-sibling-core failure).
- Re-run your fill script so ALL THREE posts are re-written FRESH this cycle (the
  orchestrator checks each post's mtime — a post not freshly written this cycle fails
  the run).
- Everything the prompt above still binds (dream-first, operator vantage, the three
  registers, everything-is-copy, archival, redaction, the youtube-script read-aloud
  test) still binds — the findings are the FOCUS, not the whole law.
"""


def _writer_command(props, feedback, iterations):
    """Build the heaven AGENT-MODE command for the writer.

    Base = the PROVEN filled narrative-blog-from-aios prompt (reused verbatim via the
    organ's ``_build_prompt``). On a revise cycle, append the MPE-disciplined revision
    block carrying the eval's per-dimension findings. Wrapped as
    ``agent goal=<prompt>, iterations=N`` so heaven runs it in agent mode
    (baseheavenagent:4130). NOTE: the assembled goal must never contain the literal
    substring ", iterations=<digits>" (the regex that enters agent mode keys on it) —
    the blog prompt + this block do not.
    """
    prompt = _build_prompt(props)
    if feedback:
        prompt += _REVISION_BLOCK.format(
            targets="\n".join(_pov_targets(props["output_md_path"])),
            feedback=feedback,
        )
    return f"agent goal={prompt}, iterations={iterations}"


# The CHALLENGER prompt + the verdict GATE (build_challenger_prompt / read_verdict /
# derive_pass / revise_feedback) live in blog_rubric (imported above) — the same source
# the CI challenger compiles from. run_duo just WALKS them.


# ── the DUO orchestrator ─────────────────────────────────────────────────────
def run_duo(props,
            max_cycles=None,
            writer_iterations=None,
            writer_max_tool_calls=None,
            eval_max_tool_calls=None,
            timeout_s=None,
            _writer_dispatch=None,
            _eval_dispatch=None):
    """Run the bounded WRITER -> EVAL -> revise DUO for one Blog_Request's props.

    gate()-shaped (``cave_teams.algebra.gate`` μ): body = the writer, φ = the eval; loop
    until the eval passes (derived from its verdict artifact) or ``max_cycles`` is hit.

    Per cycle:
      1. WRITER dispatch (agent mode, iterations, tool_calls/iter) fills + renders the 3
         POV posts. Freshness gate: EVERY target post must be written THIS cycle (mtime
         >= cycle start) — a stale/missing post is a hard failure.
      2. EVAL dispatch grades the posts and writes a verdict JSON. Freshness gate on the
         verdict too. The orchestrator DERIVES pass from the verdict's per-check
         booleans + evidence (never the eval's self-declared "verdict").
      3. pass -> done. else -> compile the failed checks into feedback for the next
         writer cycle.

    ``_writer_dispatch`` / ``_eval_dispatch`` are test seams (default: ``_dispatch_agent``).
    Returns a status dict; never raises. Never claims done without a fresh, eval-passed
    artifact (verify-via-user-surface discipline pushed into the loop).

    CALLER CONSTRAINT: a script that calls this at module top level MUST guard with
    ``if __name__ == "__main__":`` — the spawn-context children re-import ``__main__``
    (multiprocessing/spawn.py ``_fixup_main_from_path``), so an unguarded call re-executes
    run_duo inside the child's bootstrap and the child dies with RuntimeError (proven live
    2026-07-12, duo run r1).
    """
    max_cycles = DEFAULT_MAX_CYCLES if max_cycles is None else max_cycles
    writer_iterations = (DEFAULT_WRITER_ITERATIONS
                         if writer_iterations is None else writer_iterations)
    writer_max_tool_calls = (DEFAULT_WRITER_MAX_TOOL_CALLS
                             if writer_max_tool_calls is None else writer_max_tool_calls)
    eval_max_tool_calls = (DEFAULT_EVAL_MAX_TOOL_CALLS
                           if eval_max_tool_calls is None else eval_max_tool_calls)
    writer = _writer_dispatch or _dispatch_agent
    evaluator = _eval_dispatch or _dispatch_agent

    missing = [k for k in REQUIRED_PROPS if not props.get(k)]
    if missing:
        return {"status": "failed", "stage": "validate",
                "error": f"missing required properties: {', '.join(missing)}"}

    output_path = props["output_md_path"]
    targets = _pov_targets(output_path)
    verdict_path = _verdict_path(output_path)

    feedback = None
    model = ""
    last_reason = ""
    for cycle in range(1, max_cycles + 1):
        # ── WRITER (body) ──
        t0 = time.time()
        w_command = _writer_command(props, feedback, writer_iterations)
        w_ok, w_err, model = writer(
            w_command, name="blog_duo_writer",
            max_tool_calls=writer_max_tool_calls, timeout_s=timeout_s)
        if not (w_ok and all(_artifact_fresh(p, t0) for p in targets)):
            err = w_err or ("writer reported ok but the three POV posts were not all "
                            "freshly written this cycle (missing or stale mtime)")
            logger.error("Blog DUO cycle %d: writer failed — %s", cycle, err)
            return {"status": "failed", "stage": "writer", "cycle": cycle,
                    "error": err, "model": model}

        # ── CHALLENGER (φ) — reads the ARTIFACTS, writes a verdict ──
        t1 = time.time()
        e_command = build_challenger_prompt(
            props["aios_name"], props["journey_source"], targets, verdict_path)
        e_ok, e_err, _ = evaluator(
            e_command, name="blog_duo_challenger",
            max_tool_calls=eval_max_tool_calls, timeout_s=timeout_s)
        if not (e_ok and _artifact_fresh(verdict_path, t1)):
            err = e_err or ("challenger reported ok but the verdict was not freshly "
                            "written this cycle (missing or stale mtime)")
            logger.error("Blog DUO cycle %d: challenger failed — %s", cycle, err)
            return {"status": "failed", "stage": "challenger", "cycle": cycle,
                    "error": err, "model": model}

        verdict = read_verdict(verdict_path)
        if verdict is None:
            return {"status": "failed", "stage": "challenger", "cycle": cycle,
                    "error": "challenger verdict missing or unparseable", "model": model}

        passed, last_reason = derive_pass(verdict)
        if passed:
            logger.info("Blog DUO: challenger PASSED at cycle %d -> %s", cycle, output_path)
            return {"status": "done", "cycle": cycle, "output_path": output_path,
                    "targets": targets, "verdict_path": verdict_path, "model": model}

        logger.info("Blog DUO cycle %d: challenger says revise — %s", cycle, last_reason)
        feedback = revise_feedback(verdict)

    # budget exhausted — bounded, honest, no false "done"
    logger.error("Blog DUO: budget exhausted after %d cycles (last: %s)",
                 max_cycles, last_reason)
    return {"status": "budget_exhausted", "cycles": max_cycles,
            "output_path": output_path, "targets": targets,
            "verdict_path": verdict_path, "last_reason": last_reason, "model": model}
