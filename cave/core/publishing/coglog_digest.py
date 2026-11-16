#!/usr/bin/env python3
"""coglog_digest — the WEBSITE-FIRST rung for the *Log lane (2026-08-04).

Isaac's ruling, 2026-08-04: "things are now supposed to pipe to publish in website first
and then subtrates/socials."

THE LANE THIS CORRECTS. The *Log lane published straight to Discord: coglog_publisher.review
safety-reviews + redacts, then coglog_publisher.publish posts the safe entries to #coglog with
NO website step. That is the Feb-14 shape (cave/core/log_router.py -> Discord) surviving in the
one place it was never replaced. The CONTENT lane is already website-first by design
(unicorn_site_publish 02:37 precedes the socials stage 03:07), so this rung brings the *Log lane
onto the same ordering rather than inventing a new one.

WHAT IT DOES: reads the SAME review queue coglog_publisher.publish reads, renders the safe,
not-yet-published entries into ONE markdown digest, and hands that file to the EXISTING site
publisher (cave_unicorn.publish.fire_site_publish in its direct md_path mode). Discord then
follows automatically and second: announce_posts already fires inside fire_site_publish after a
pushed publish, posting the live URL. So website-first-then-social falls out of the existing
rails; nothing new routes to Discord.

WHY A DIGEST AND NOT ONE POST PER ENTRY: a *Log is a SYSTEM OBJECT, not a manual and not a user
claim. steer_gaps.py states the boundary verbatim — "a system request is not something the user
said, and the claims lane's candidate-stamping gate ... must never be diluted with system
objects" — so *Log entries must NOT be minted into Blog_Requests or the content chain. A periodic
digest is a system-object surface of its own: it publishes the work record without ever entering
the certified-Framework pipeline that feeds manuals and the park.

WHAT THIS MODULE DOES NOT DO (deliberate, replace-before-remove): it does NOT modify or delete
coglog_publisher.publish. Both paths exist; switching the lane over is a one-line automation
change (point the schedule at fire_coglog_digest instead of ...publisher.publish), which is an
ACTIVATION decision, not a code change. The safety gate is preserved absolutely — this module
only ever reads entries already marked safe_to_publish by the review pass, and it renders the
REDACTED description when one exists.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# The digest lands beside the other rendered content; CONTENT_OUTDIR mirrors the content lane's
# own override so both lanes honour the same env when a caller redirects output.
_DEFAULT_OUTDIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "coglog_digests"


def select_publishable(entries, posted_names):
    """The entries a digest may carry: reviewed SAFE and not already published.

    PURE. Mirrors coglog_publisher.publish's filter exactly so the two paths can never disagree
    about what is publishable — the safety gate is the review pass's `safe_to_publish`, and this
    function never re-decides it.
    """
    posted = set(posted_names or ())
    return [
        e for e in (entries or [])
        if e.get("safe_to_publish") and e.get("name") not in posted
    ]


def _entry_text(entry):
    """The publishable text of one entry — the REDACTED description when the reviewer produced
    one, else the original. Never the raw text when a redaction exists."""
    return (entry.get("redacted_description") or entry.get("description") or "").strip()


def render_digest(entries, now=None, title=None):
    """Render publishable entries into ONE markdown digest. PURE — no I/O, no clock.

    Shape matches what cave_unicorn.site.split_front expects of a post: an H1 title, an italic
    hook line, then the body. `now` is injected (never read from the clock here) so the render is
    deterministic and testable.
    """
    stamp = (now or datetime(1970, 1, 1)).strftime("%Y-%m-%d")
    heading = title or f"CogLog digest — {stamp}"
    n = len(entries or [])
    hook = (f"*{n} work-log entr{'y' if n == 1 else 'ies'} from the agent's own record, "
            f"reviewed and redacted before publication.*")
    lines = [f"# {heading}", "", hook, ""]
    for e in entries or []:
        text = _entry_text(e)
        if not text:
            continue
        lines.append(f"## {e.get('name', 'entry')}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_digest(markdown, outdir=None, stamp=None):
    """THIN I/O: write the digest markdown and return its path."""
    d = Path(outdir) if outdir else _DEFAULT_OUTDIR
    d.mkdir(parents=True, exist_ok=True)
    name = f"coglog-digest-{stamp or datetime.now().strftime('%Y%m%d')}.md"
    path = d / name
    path.write_text(markdown)
    return str(path)


def fire_coglog_digest(dry_run=False, outdir=None, tags=None):
    """The organ entrypoint — website FIRST, Discord second (and automatically).

    Never raises: every failure is converted to a returned dict, matching the CronAutomation
    code_pointer convention the other organs follow.

    Sequence: read the review queue -> select safe+unpublished -> render the digest -> write it
    -> hand the file to cave_unicorn.publish.fire_site_publish(md_path=...). That publisher
    renders it into the live site, commits and pushes, and its own announce_posts step then posts
    the live URL to Discord — so the social lands downstream OF the website rather than instead
    of it. Checkpointing reuses coglog_publisher's checkpoint so the two paths share one
    already-published set and can never double-publish an entry.
    """
    try:
        from cave.core.publishing import coglog_publisher as cp
    except Exception as e:  # noqa: BLE001
        return {"status": "import_failed", "error": f"{type(e).__name__}: {e}"}

    review_file = cp.WORK_DIR / "review_queue.json"
    if not review_file.exists():
        return {"status": "no_review_file"}

    try:
        entries = json.loads(review_file.read_text())
        checkpoint = cp.load_checkpoint()
    except Exception as e:  # noqa: BLE001
        return {"status": "read_failed", "error": f"{type(e).__name__}: {e}"}

    to_publish = select_publishable(entries, checkpoint.get("posted", []))
    if not to_publish:
        return {"status": "nothing_to_publish", "total_posted": len(checkpoint.get("posted", []))}

    now = datetime.now()
    markdown = render_digest(to_publish, now=now)
    if dry_run:
        return {"status": "dry_run", "entries": len(to_publish), "chars": len(markdown)}

    try:
        md_path = write_digest(markdown, outdir=outdir, stamp=now.strftime("%Y%m%d"))
    except Exception as e:  # noqa: BLE001
        return {"status": "write_failed", "error": f"{type(e).__name__}: {e}"}

    try:
        from cave_unicorn.publish import fire_site_publish
    except Exception as e:  # noqa: BLE001
        # The digest EXISTS on disk; only the site hand-off is unavailable. Report precisely
        # rather than pretending nothing happened, and do NOT checkpoint (it is unpublished).
        return {"status": "site_publisher_unavailable", "md_path": md_path,
                "error": f"{type(e).__name__}: {e}"}

    try:
        report = fire_site_publish(md_path=md_path, tags=list(tags or ["coglog"]))
    except Exception as e:  # noqa: BLE001
        return {"status": "site_publish_failed", "md_path": md_path,
                "error": f"{type(e).__name__}: {e}"}

    if str(report.get("status", "")).lower() in ("failed", "error"):
        return {"status": "site_publish_failed", "md_path": md_path, "report": report}

    # Only checkpoint once the WEBSITE publish succeeded — the website is the publication of
    # record, so an entry is "published" exactly when it is on the site.
    posted = set(checkpoint.get("posted", []))
    posted.update(e["name"] for e in to_publish if e.get("name"))
    checkpoint["posted"] = list(posted)
    checkpoint["last_digest"] = now.isoformat()
    try:
        cp.save_checkpoint(checkpoint)
    except Exception as e:  # noqa: BLE001
        return {"status": "published_checkpoint_failed", "md_path": md_path,
                "report": report, "error": f"{type(e).__name__}: {e}"}

    return {"status": "published", "entries": len(to_publish),
            "md_path": md_path, "report": report, "total_posted": len(posted)}
