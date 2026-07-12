"""Nightly Blog Organ — the graph detects there IS a blog to write, and writes it.

V1 shape (a cave CronAutomation code_pointer; fires nightly at 02:00):
  1. Query CartON for ``Blog_Request`` property-nodes with ``{status: "pending"}``
     via ``query_concepts_by_properties``.
  2. None pending -> quiet no-op (``{"status": "no_pending"}``).
  3. One pending (lowest ``created`` / first) -> dispatch a HEAVEN MINIMAX agent
     carrying the PROVEN narrative-blog-from-aios blog-organ prompt, with the
     specifics filled from the node's properties. The agent reconstructs the
     AIOS journey, FILLS the JourneyCore model, and runs the deterministic
     renderer to produce the blog markdown at ``output_md_path``.
  4. On success -> flip the node to ``{status: "done", output_path, completed_at,
     model}``. On failure -> flip to ``{status: "failed", error: <first 200 chars>}``.

This dispatches on HEAVEN/MINIMAX, the SAME proven pattern as the WakingDreamer
service agents (``sanctuary_revolution.agents.night_agent`` /
``journal_agent``): a ``BaseHeavenAgent`` built from a ``HeavenAgentConfig``
(minimax model + ``anthropic_api_url`` read from
``$HEAVEN_DATA_DIR/journal_agent_config.json``), equipped with ``BashTool`` so
it can write + run the JourneyCore fill script and read the journey source
ITSELF. This organ only triggers it and flips the node. (Heaven resolves the
minimax provider key internally — no provider creds are constructed here, so the
host OAuth token is never touched.)

The Blog_Request contract — REQUIRED properties on each ``Blog_Request`` node:
  - ``aios_name``        : human name of the AIOS (e.g. "doc-mirror").
  - ``aios_root``        : absolute path to the AIOS root dir.
  - ``journey_source``   : path(s) the agent reads to reconstruct the story
                           (the journal/durable layer + the "what it is" doc).
  - ``allowed_domain``   : the ``JourneyCore.domain`` value (free-form; usually
                           the AIOS name).
  - ``plugin_repo_url``  : plugin / code URL (used for plugin_url + github_url).
  - ``output_md_path``   : where the rendered Blog 1 markdown is written.
  - ``status``           : lifecycle — "pending" -> "done" | "failed".

Optional properties:
  - ``journeycore_import_path`` : dir holding ``core.py`` + ``framework_render.py``
                           (defaults to the cave-discord-fork integration dir).

MINIMAX (the dispatch): the agent runs on HEAVEN/MINIMAX, the same proven path
the WakingDreamer service agents use (night/journal agents). The minimax model
+ ``anthropic_api_url`` are read from ``$HEAVEN_DATA_DIR/journal_agent_config.json``
(``model``, ``extra_model_kwargs.anthropic_api_url``) — the SAME config the WD
agents read, so the blog organ uses whatever minimax model they do (currently
``MiniMax-M2.7-highspeed``). The resolved model is recorded on the flipped node
(``model``). Heaven resolves the provider API key internally; no provider creds
are constructed in this module.

Env (read by the CartON connection): NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
HEAVEN_DATA_DIR. Heaven additionally reads whatever the minimax provider needs
(resolved internally by heaven-framework, same as the WD agents).
"""

import json
import logging
import multiprocessing
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Default dir holding core.py (JourneyCore) + framework_render.py — the cave-discord-fork
# integration. The blog-organ prompt imports `from core import JourneyCore` and
# `from framework_render import framework_blog_from_core` off this path.
DEFAULT_JOURNEYCORE_IMPORT_PATH = os.environ.get(
    "BLOG_ORGAN_JOURNEYCORE_PATH",
    "/home/GOD/gnosys-plugin-v2/integration/cave-discord-fork",
)

# Canonical home of the proven blog-organ prompt (narrative-blog-from-aios).
DEFAULT_PROMPT_PATH = os.environ.get(
    "BLOG_ORGAN_PROMPT_PATH",
    "/home/GOD/gnosys-plugin-v2/doc-mirror-system/plugin/skills/doc-mirror-prompts/"
    "resources/prompts/skill2framework/blog-organ/narrative-blog-from-aios/SKILL.md",
)

# Minimax model config — read from the SAME file the WakingDreamer service agents read
# (sanctuary_revolution.agents.night_agent / journal_agent). Holds `model` +
# `extra_model_kwargs.anthropic_api_url`. No hardcoded model/url (matches the WD pattern).
HEAVEN_DATA_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
MINIMAX_CONFIG_PATH = HEAVEN_DATA_DIR / "journal_agent_config.json"


def _minimax_model_config() -> dict:
    """Read minimax model config from journal_agent_config.json (the WD agents' config).

    Returns the parsed dict (``model``, ``max_tokens``, ``extra_model_kwargs``,
    ``use_uni_api``) or {} if absent/unreadable. Same reader as night_agent's
    ``_get_night_model_config`` — the blog organ rides the WD minimax config.
    """
    if MINIMAX_CONFIG_PATH.exists():
        try:
            return json.loads(MINIMAX_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# REQUIRED Blog_Request properties — a node missing any of these is skipped (failed).
REQUIRED_PROPS = (
    "aios_name",
    "aios_root",
    "journey_source",
    "allowed_domain",
    "plugin_repo_url",
    "output_md_path",
)


def _carton():
    """Import the CartON property primitives + a shared graph connection.

    Mirrors the connection pattern in scalable-publishing/bin/sync_manifest_to_carton.py:
    carton_mcp is the canonical source of the property-write primitives + the conn.
    Returns (graph, set_props_fn, query_fn) or (None, None, None) if unavailable.
    """
    try:
        from carton_mcp.add_concept_tool import _get_module_connection
        from carton_mcp.carton_utils import (
            set_concept_properties,
            query_concepts_by_properties,
        )
    except ImportError as e:
        logger.error("carton_mcp not importable: %s", e)
        return None, None, None

    graph = _get_module_connection()
    if graph is None:
        logger.error("no neo4j connection available (check NEO4J_* env vars)")
        return None, None, None
    return graph, set_concept_properties, query_concepts_by_properties


def _pick_pending(query_fn, graph):
    """Return the ONE Blog_Request to process: lowest `created`, else first.

    query_concepts_by_properties matches {status: "pending"} AND. Each result
    carries only `n` + the matched keys, so we re-read full properties per node.
    """
    res = query_fn({"status": "pending"}, limit=100, shared_connection=graph)
    if not res.get("success"):
        logger.error("query_concepts_by_properties failed: %s", res.get("error"))
        return None
    results = res.get("results", [])
    if not results:
        return None

    # Read full properties for each candidate so we can order by `created`.
    candidates = []
    for row in results:
        name = row.get("n")
        if not name:
            continue
        props = _read_props(graph, name)
        if props is not None:
            candidates.append((name, props))

    if not candidates:
        return None

    # Order: lowest `created` first; nodes with no `created` sort last (stable order).
    def _key(item):
        created = item[1].get("created")
        return (0, created) if created is not None else (1, item[0])

    candidates.sort(key=_key)
    return candidates[0]


def _read_props(graph, concept_name):
    """Read all non-reserved-ish properties of a :Wiki node as a dict, or None if absent."""
    rows = graph.execute_query(
        "MATCH (c:Wiki {n: $n}) RETURN properties(c) AS p LIMIT 1",
        {"n": concept_name},
    )
    if not rows:
        return None
    return dict(rows[0].get("p") or {})


def _build_prompt(props):
    """Fill the proven blog-organ prompt with this Blog_Request's specifics.

    Reads the prompt template from DEFAULT_PROMPT_PATH (the ## PROMPT body) and
    fills the {placeholder} fields. journeycore_import_path defaults to the
    cave-discord-fork dir (holds core.py + framework_render.py).
    """
    prompt_path = Path(DEFAULT_PROMPT_PATH)
    raw = prompt_path.read_text()
    # The SKILL.md carries frontmatter + a "## PROMPT" body; use the body if present.
    marker = "## PROMPT"
    body = raw.split(marker, 1)[1] if marker in raw else raw

    journeycore_import_path = props.get(
        "journeycore_import_path", DEFAULT_JOURNEYCORE_IMPORT_PATH
    )

    return body.format(
        aios_name=props["aios_name"],
        aios_root=props["aios_root"],
        journey_source=props["journey_source"],
        journeycore_import_path=journeycore_import_path,
        allowed_domain=props["allowed_domain"],
        plugin_repo_url=props["plugin_repo_url"],
        output_md_path=props["output_md_path"],
    )


# Healthy organ runs complete in 5-25 minutes; 45 minutes is unambiguous hang
# territory (a live 2026-07-12 dispatch sat 85+ minutes and would have sat
# forever, wedging the tick worker).
DEFAULT_DISPATCH_TIMEOUT_S = int(
    os.environ.get("BLOG_ORGAN_DISPATCH_TIMEOUT_S", "2700"))


def _dispatch_child(config_kwargs, prompt, max_tool_calls, result_path):
    """Child-process body: run the heaven dispatch, write the outcome JSON.

    Module-level (picklable for the spawn context). Heavy imports happen HERE.
    Writes {"ok": bool, "error": str} to result_path; a missing result file
    means the child died before finishing — the parent reports that loudly.
    """
    import asyncio

    out = {"ok": False, "error": "child died before writing a result"}
    try:
        from heaven_base.baseheavenagent import BaseHeavenAgent, HeavenAgentConfig
        from heaven_base.unified_chat import UnifiedChat
        from heaven_base.tools import BashTool
        from heaven_base.docs.examples.heaven_callbacks import BackgroundEventCapture

        # Provider defaults to anthropic (minimax speaks the anthropic API via
        # anthropic_api_url) — same as the WD night/journal agents.
        config = HeavenAgentConfig(tools=[BashTool], **config_kwargs)

        async def _dispatch():
            agent = BaseHeavenAgent(
                config=config,
                unified_chat=UnifiedChat(),
                max_tool_calls=max_tool_calls,
            )
            capture = BackgroundEventCapture()
            return await agent.run(prompt=prompt, heaven_main_callback=capture)

        asyncio.run(_dispatch())
        out = {"ok": True, "error": ""}
    except Exception as e:  # heaven dispatch failure — capture literally, do NOT fall back
        import traceback
        out = {"ok": False,
               "error": f"heaven minimax dispatch failed: {e}\n"
                        + traceback.format_exc()}
    Path(result_path).write_text(json.dumps(out))


def _run_agent(prompt, max_tool_calls=40, timeout_s=None, _child_target=None):
    """Dispatch the blog-organ agent on HEAVEN/MINIMAX. Agent reads/writes files itself.

    SAME proven pattern as the WakingDreamer service agents
    (sanctuary_revolution.agents.night_agent / journal_agent): build a
    ``HeavenAgentConfig`` (minimax model + ``anthropic_api_url`` from
    ``journal_agent_config.json``), equip ``BashTool``, run the prompt. Heaven
    resolves the provider key internally — no provider creds constructed here.

    WALL-CLOCK TIMEOUT (2026-07-12): the dispatch runs in a spawned CHILD
    PROCESS killed after ``timeout_s`` (default DEFAULT_DISPATCH_TIMEOUT_S).
    The live hang that forced this wedged a blocking unix-socket read ON the
    event-loop thread — no in-process timeout (asyncio/signal) can fire for
    that class; only an out-of-process kill can. On timeout the organ fails
    LOUD (the node flips failed). ``_child_target`` is a test seam.

    Sync-callable (a cron code_pointer).

    Returns (ok: bool, error: str, model: str). error is "" on success.
    """
    timeout_s = DEFAULT_DISPATCH_TIMEOUT_S if timeout_s is None else timeout_s
    cfg = _minimax_model_config()
    # BLOG_ORGAN_MODEL overrides the shared WD config's model for THIS organ
    # (Isaac 2026-07-12: "call m3" — content quality wants the big model; the
    # WD journal agents keep their own config untouched).
    model = os.environ.get("BLOG_ORGAN_MODEL") or cfg.get("model", "")
    api_url = cfg.get("extra_model_kwargs", {}).get("anthropic_api_url", "")
    if not (model and api_url):
        return (False,
                f"minimax model config missing/incomplete at {MINIMAX_CONFIG_PATH} "
                f"(model={model!r}, anthropic_api_url={api_url!r})",
                model)

    config_kwargs = dict(
        name="blog_organ",
        system_prompt="",  # the whole instruction is the prompt (the blog-organ prompt body)
        model=model,
        use_uni_api=cfg.get("use_uni_api", False),
        # The blog organ gets its OWN token budget (BLOG_ORGAN_MAX_TOKENS,
        # default 16000) instead of the shared WD config's 8000: a 3-POV run
        # died live (2026-07-12) with its entire 8000 burned inside one
        # thinking pass — the final message was thinking-only, no tool call,
        # zero writes. The shared journal_agent_config stays untouched.
        max_tokens=int(os.environ.get("BLOG_ORGAN_MAX_TOKENS", "16000")),
        extra_model_kwargs={"anthropic_api_url": api_url},
        **({"provider": cfg["provider"]} if cfg.get("provider") else {}),
    )

    fd, result_path = tempfile.mkstemp(prefix="blog_organ_dispatch_", suffix=".json")
    os.close(fd)
    os.unlink(result_path)  # the child writing it back IS the success signal
    ctx = multiprocessing.get_context("spawn")  # clean interpreter, fork-safe
    proc = ctx.Process(target=_child_target or _dispatch_child,
                       args=(config_kwargs, prompt, max_tool_calls, result_path))
    try:
        proc.start()
        proc.join(timeout_s)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            logger.error("Blog agent dispatch exceeded %ss wall-clock — KILLED",
                         timeout_s)
            return (False,
                    f"dispatch exceeded wall-clock timeout {timeout_s}s and was "
                    "KILLED (the 2026-07-12 hang class: a blocking IPC read "
                    "wedged on the event-loop thread — only an out-of-process "
                    "kill can catch it)", model)
        result_file = Path(result_path)
        if not result_file.exists():
            return (False,
                    f"dispatch child exited (code {proc.exitcode}) without "
                    "writing a result — child crashed", model)
        out = json.loads(result_file.read_text())
        if not out.get("ok"):
            logger.error("Blog agent (heaven minimax) failed: %s", out.get("error"))
        return bool(out.get("ok")), str(out.get("error", "")), model
    finally:
        Path(result_path).unlink(missing_ok=True)


def _artifact_fresh(path, t0):
    """True iff ``path`` exists AND was written at/after dispatch start ``t0``.

    Existence alone is the ok-report-no-artifact trap (caught live 2026-07-12:
    a halted run 'succeeded' against a STALE artifact from a prior run) —
    only a write newer than the dispatch counts as the deliverable.
    """
    p = Path(path)
    return p.exists() and p.stat().st_mtime >= t0


def _flip_failed(set_props, graph, concept_name, err):
    """Flip a Blog_Request node to status=failed and return the failure status dict."""
    err = str(err)
    set_props(
        concept_name,
        {"status": "failed", "error": err[:200],
         "completed_at": datetime.now().isoformat()},
        mode="merge", shared_connection=graph,
    )
    logger.error("Blog organ: %s failed — %s", concept_name, err)
    return {"status": "failed", "concept": concept_name, "error": err[:200]}


def fire_blog_organ(**kwargs) -> dict:
    """CronAutomation code_pointer — write the next pending blog, if any.

    1. Find one pending Blog_Request. None -> quiet no-op.
    2. Validate it carries the required properties.
    3. Dispatch the blog-organ agent with the filled prompt.
    4. Flip the node: done (with output_path) on success, failed (with error) on failure.

    Returns a status dict (the automation result). Never raises — failures are
    captured on the node and in the return.
    """
    graph, set_props, query_props = _carton()
    if graph is None:
        return {"status": "no_connection"}

    picked = _pick_pending(query_props, graph)
    if picked is None:
        return {"status": "no_pending"}

    concept_name, props = picked

    # Validate required properties before dispatch.
    missing = [k for k in REQUIRED_PROPS if not props.get(k)]
    if missing:
        return _flip_failed(set_props, graph, concept_name,
                            f"missing required properties: {', '.join(missing)}")

    output_path = props["output_md_path"]

    # Dispatch the blog-organ agent (it reads the journey + writes the markdown itself).
    try:
        prompt = _build_prompt(props)
    except (KeyError, OSError) as e:
        return _flip_failed(set_props, graph, concept_name, f"prompt build failed: {e}")

    logger.info("Blog organ: dispatching heaven minimax agent for %s -> %s", concept_name, output_path)
    t0 = time.time()
    # 80 tool calls, env-overridable: the 3-POV task (read sources + three
    # draft->write->run->confirm passes) exhausted the old default of 40 —
    # a run died at exactly 40 with the third post unwritten (2026-07-12).
    ok, agent_err, model = _run_agent(
        prompt,
        max_tool_calls=int(os.environ.get("BLOG_ORGAN_MAX_TOOL_CALLS", "80")))

    # Verify the deliverable is FRESH (the agent claims success; we check the
    # artifact was written by THIS dispatch — bare existence passes on a stale
    # file from a prior run, the ok-report-no-artifact trap).
    if not (ok and _artifact_fresh(output_path, t0)):
        err = agent_err if agent_err else (
            f"agent reported ok but {output_path} was not freshly written "
            "(missing, or mtime predates this dispatch)")
        return _flip_failed(set_props, graph, concept_name, err)

    # Success — flip to done. Record the minimax model the agent actually ran on.
    flip = {
        "status": "done",
        "output_path": output_path,
        "completed_at": datetime.now().isoformat(),
        "model": model,
    }
    set_props(concept_name, flip, mode="merge", shared_connection=graph)
    logger.info("Blog organ: %s done -> %s", concept_name, output_path)
    return {"status": "done", "concept": concept_name, "output_path": output_path}


if __name__ == "__main__":
    print(json.dumps(fire_blog_organ(), indent=2))
