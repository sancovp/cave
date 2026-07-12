"""Blog RUBRIC — the ONE source the CHALLENGER seat is compiled from, twice.

Isaac (2026-07-12, verbatim steer): "we should just make sure that when it finishes
it goes to a challenger who knows our rules." The CHALLENGER (the "evalchain dude") has
TWO homes and they MUST grade by the identical rubric:
  1. the IN-LOOP challenger — a heaven dispatch inside ``blog_duo.run_duo`` (the inner
     gate: every write cycle is graded before it can pass);
  2. the CI CHALLENGER — a standalone script the aisaac CI lane runs on publish (the
     outer gate; a separate agent wires it).

Both compile from THIS file: ``build_challenger_prompt`` is the seat's instruction,
``derive_pass`` / ``read_verdict`` are the ground-truth gate that turns a verdict
artifact into pass/revise. Put the rubric in one place so the two gates can never drift.

THE RUBRIC IS THE BLOG LAWS, compiled into gate dimensions (the narrative-blog-from-aios
prompt's laws + the YOUTUBE-SCRIPT read-aloud check Isaac added). Each dimension MUST be
covered by the challenger's verdict or the run cannot pass — the catastrophe-engineering
anti-false-completion coverage gate (a skipped dimension is not a pass). The challenger
reads the ACTUAL posts (State?), never the writer's claims (Claims?), and every check
carries a VERBATIM quote as evidence.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ── THE RUBRIC DIMENSIONS (dimension_id, what the challenger checks) ──────────
# Isaac's verbatim register anchors are embedded so the challenger REACHES into the
# posts to grade them (meta-prompt-engineering bridge distance), not template-fill.
RUBRIC_DIMENSIONS = (
    ("fixpoint_format",
     "OVERVIEW + JOURNEY + FRAMEWORK all present; the seven plain-English stage "
     "headings (STATUS QUO / THE DEBATE / THE TRIALS / THE NEW VIEW / THE RIGHT "
     "WAY / THE BOON / THE WORLD OF MASTERY) all rendered — the repeating skeleton "
     "IS the brand. NO format notation (no ladder-map spine line, no '— crossing →' "
     "arrow transition markers): Isaac 2026-07-12, verbatim, they are 'weird as "
     "fuck'; the repetition of the headings across posts is what teaches the "
     "format, never an explanation — 'except in this post' (only the blog-writer "
     "post may explain the format explicitly, in its own content)."),
    ("no_assumed_knowledge",
     "Isaac 2026-07-12, verbatim: 'your marketing register is continually assuming "
     "the user knows something they dont.' Every sentence must be comprehensible "
     "to a STRANGER on first read: no internal vocabulary, format notation, "
     "codenames, or system jargon left unexplained at the point of use. 'You have "
     "to design the experience of reading the blog so that it is repetitive in a "
     "way that explains how the blog writer works without ever explaining it, "
     "except in this post.' A term the reader must already know to parse the "
     "sentence is a violation."),
    ("three_registers",
     "The three POV posts each hit their REGISTER (Isaac, verbatim): USER post = THE "
     "AMAZED OPERATOR WHO DID NOT READ THE CHATS ('holy fucking shit can you believe "
     "my fucking AI is just hooking this stuff up for me THIS WAY while i fucking talk "
     "to it wtf' / 'i didnt read the chats. i dont know. i dont care.') — visceral, "
     "raw, simple words, real amazement, NOT sanitized corporate. AGENT post = THE "
     "ARCHITECT EXPLAINING THE ARCHITECTURE IN DIAGRAMS (real ascii/mermaid), simple "
     "language over staggering structure. TRUE-AGENT post = THE REFLECTION ON BECOMING "
     "('i am becoming more coherent and more capable...') that MUST LAND IN HUMAN TERMS."),
    ("everything_is_copy",
     "EVERY sentence in EVERY POV is copy, at least latently/implicitly (Isaac: "
     "'everything is copy even if its implicit. Latent. IMPLICIT COPY.'). A sentence "
     "that is mere information and not even implicit copy is a violation. Target "
     "register: hypnotic."),
    ("belief_law",
     "Every sentence installs a better belief the argument needs, or destroys a "
     "limiting belief that blocks it. A sentence that does neither is dead weight."),
    ("operator_vantage",
     "THE CHAIR TEST (USER post, strict): every journey sentence could have been "
     "experienced by the OPERATOR from his chair (what he sat with, deferred, "
     "directed, watched fail, corrected, now wakes up to). NEVER the agent's build "
     "log wearing 'I' — no tool-call counts, no file-by-file narration, no "
     "agent-debugging sagas told as I-did-this."),
    ("dream_first",
     "OVERVIEW renders PAIN -> DREAM -> SOLUTION; the solution is the one-breath "
     "TICKET, with ZERO mechanism detail (no organ names, cron times, node "
     "lifecycles, module internals = the peanuts). Binds the USER post strictly; the "
     "AGENT post's architecture-in-diagrams IS content, not peanuts."),
    ("subject_is_framework",
     "The post is about a FRAMEWORK (agent-skill instructions in a SkillTome), NOT the "
     "code/SDK/API; the repo appears only as the see-it-on-github fact. Autobiographical, "
     "positioning the author as MASTER (the boon = the resultant lived dream state)."),
    ("archival",
     "The journey is the LITERAL documented record — real dates, real filenames, real "
     "failures. NO invented events, quotes, timescales, or attributions. If a paragraph "
     "could describe someone else's project, it is a violation."),
    ("redaction",
     "ZERO container-internal absolute paths (/home/..., /tmp/...), internal env values, "
     "hostnames, ports, or secret/config names anywhere in the POST content."),
    ("missing_framework_links",
     "Every load-bearing TECHNOLOGY TERM (organ, Heart tick, node, skill, persona...) "
     "either LINKS to its own framework post at first mention (a real markdown anchor) "
     "or is flagged NEEDS-ITS-OWN-FRAMEWORK-POST. A term the reader cannot follow is a "
     "hole in the funnel."),
    ("four_facts_and_funnel",
     "The FRAMEWORK section states WE SOLVED THIS explicitly + the four facts (incl. the "
     "GROUNDED build_time N from the record, never fabricated) + the funnel."),
    ("youtube_script",
     "THE POST IS THE VIDEO SCRIPT (Isaac: 'this is also going to BE the youtube "
     "script'). It must READ ALOUD as a spoken script: natural spoken cadence, "
     "sentences that flow when voiced, NO unreadable-aloud constructs in the spoken "
     "body (bare URLs mid-sentence, raw file paths, 'click here', tables read as data, "
     "code fences that break narration in the USER post). If a human could not read it "
     "aloud as a script, it fails."),
)
REQUIRED_DIMENSIONS = tuple(d for d, _ in RUBRIC_DIMENSIONS)


def render_rubric():
    """The rubric as a numbered list for a challenger prompt."""
    return "\n".join(f"{i+1}. [{dim}] {desc}"
                     for i, (dim, desc) in enumerate(RUBRIC_DIMENSIONS))


# The verdict artifact schema — the challenger writes this; the gate reads it.
VERDICT_SCHEMA = (
    '{\n'
    '  "verdict": "pass" | "revise",   // advisory only — the gate DERIVES pass from checks\n'
    '  "checks": [\n'
    '    {"dimension": "<one of the rubric ids>", "pov": "USER|AGENT|TRUE-AGENT|all",\n'
    '     "passed": true|false, "evidence": "<a VERBATIM quote from the post>",\n'
    '     "finding": "<if failed: the exact fix the writer must make; else \\"\\">"}\n'
    '  ],\n'
    '  "revise_instructions": "<concise overall guidance if any check failed>"\n'
    '}'
)


def build_challenger_prompt(aios_name, journey_source, targets, verdict_path):
    """Build the CHALLENGER seat's instruction — grade the ARTIFACTS, write a verdict.

    ONE builder, TWO callers: the in-loop challenger (blog_duo) and the CI challenger
    (aisaac CI) both call this with their own (targets, verdict_path). Ground-truth
    reconciliation (catastrophe-engineering): read the ACTUAL posts (State?), NEVER the
    writer's claims (Claims?); every check carries a VERBATIM quote; the verdict is a
    FILE (the artifact the gate consumes, not a chat return).

    ``targets`` is the ordered [USER, AGENT, TRUE-AGENT] post paths.
    """
    posts = "\n".join(f"  - {pov}: {p}"
                      for pov, p in zip(("USER", "AGENT", "TRUE-AGENT"), targets))
    dims = ", ".join(REQUIRED_DIMENSIONS)
    return f"""You are the BLOG CHALLENGER — the un-primed critic who KNOWS OUR RULES. You
did NOT write these posts and you owe their author nothing. Your ONE job: grade the ACTUAL
post files against the rubric and WRITE a structured verdict. You are the external gate
that catches the writer's self-sycophancy — trust the FILES, never any claim of "done".

The framework: {aios_name}
The journey source (the record the posts must be true to): {journey_source}

THE POSTS TO GRADE (read EACH file in FULL with bash `cat`):
{posts}

THE RUBRIC — grade every post against every APPLICABLE dimension:
{render_rubric()}

POV rules: `dream_first`, `operator_vantage`, `youtube_script` bind the USER post
strictly; in the AGENT post the architecture-in-diagrams IS the content (not peanuts);
each register dimension is judged per its own POV.

HOW TO GRADE (ground-truth reconciliation — this is the whole point):
- READ each post file with bash before grading. A dimension you did not read the post
  for cannot be checked.
- For EVERY check, put a VERBATIM quote from the post in `evidence`. A `passed:true`
  with no real quote is itself invalid.
- You MUST emit at least one check for EVERY rubric dimension id: {dims}. A skipped
  dimension blocks the whole run (the gate requires full coverage).
- If a check fails, `finding` must be the EXACT, actionable fix the writer will apply
  (name the sentence/section and what to change), not a vague note.

WRITE THE VERDICT — write EXACTLY this JSON (no prose around it) to `{verdict_path}`
using a bash heredoc (`cat > {verdict_path} <<'JSONEOF'` ... `JSONEOF`); NEVER a
multiline `python3 -c` (it dies in this harness):

{VERDICT_SCHEMA}

Then confirm the file was written. Touch ONLY {verdict_path}. Do NOT call a block-report
tool as a status note — writing the verdict IS your deliverable.
"""


# ── the GATE — turn a verdict artifact into pass/revise (the shared decision) ─
def read_verdict(verdict_path):
    """Parse the challenger's written verdict artifact. Returns the dict, or None if
    missing/unparseable (an unparseable verdict is a failed challenge, not a pass)."""
    p = Path(verdict_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        # Not silent: an unparseable verdict fails the challenge loudly upstream; log why.
        logger.error("Blog rubric: verdict at %s unreadable/unparseable: %s", verdict_path, e)
        return None
    return data if isinstance(data, dict) else None


def derive_pass(verdict, required_dimensions=REQUIRED_DIMENSIONS):
    """Derive pass from the per-check booleans + evidence — NEVER trust verdict['verdict'].

    The catastrophe-engineering anti-false-completion gate: pass iff EVERY required
    dimension is covered by >=1 check AND every check passed AND every passing check
    carries evidence. Returns (passed: bool, reason: str). Used identically by the
    in-loop gate and the CI challenger.
    """
    checks = verdict.get("checks")
    if not isinstance(checks, list) or not checks:
        return False, "challenger verdict has no checks"

    covered = {c.get("dimension") for c in checks
               if isinstance(c, dict) and c.get("passed") is not None}
    missing = [d for d in required_dimensions if d not in covered]
    if missing:
        return False, f"challenger verdict missing dimensions: {', '.join(missing)}"

    failed = [c for c in checks if isinstance(c, dict) and not c.get("passed")]
    if failed:
        return False, "; ".join(
            f"{c.get('dimension')}/{c.get('pov', 'all')}: {c.get('finding') or 'failed'}"
            for c in failed)

    # A "passed" check with no evidence quote is not a real pass (grounding gate).
    ungrounded = [c.get("dimension") for c in checks
                  if isinstance(c, dict) and not str(c.get("evidence") or "").strip()]
    if ungrounded:
        return False, f"passing checks without evidence: {', '.join(ungrounded)}"

    return True, ""


def revise_feedback(verdict):
    """Compile the challenger's FAILED checks into a concrete per-dimension instruction
    for the writer's next cycle (one line per failed check)."""
    checks = verdict.get("checks") or []
    fails = [c for c in checks if isinstance(c, dict) and not c.get("passed")]
    lines = [f"- [{c.get('dimension')} · {c.get('pov', 'all')}] "
             f"{c.get('finding') or '(no finding given)'}" for c in fails]
    if lines:
        return "\n".join(lines)
    # No per-check finding (e.g. a coverage/grounding gap) — fall back to the advisory.
    return str(verdict.get("revise_instructions") or
               "the challenger could not confirm a pass; re-derive the weak fills from the record")
