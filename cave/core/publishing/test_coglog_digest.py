#!/usr/bin/env python3
"""Tests for coglog_digest — the website-first rung of the *Log lane.

Script mode (the repo's own convention for these modules): run it directly, read ALL_PASS.

    python3 test_coglog_digest.py

Covers the two things that matter: the SAFETY GATE is never re-decided here (only entries the
review pass marked safe, and the REDACTED text when one exists), and the entrypoint NEVER raises
(every failure path returns a status dict, per the CronAutomation code_pointer convention).
"""

import sys
from datetime import datetime
from pathlib import Path

# Imports the INSTALLED cave (the installed-package law: a source edit changes nothing running
# without pip install --no-deps), so this test exercises exactly what the daemon would run.
from cave.core.publishing import coglog_digest as cd  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


print("T1 — select_publishable is the safety gate, and never re-decides it")
entries = [
    {"name": "A", "safe_to_publish": True, "description": "safe one"},
    {"name": "B", "safe_to_publish": False, "description": "UNSAFE — must never publish"},
    {"name": "C", "safe_to_publish": True, "description": "already posted"},
    {"name": "D", "description": "unreviewed — no safe flag at all"},
]
sel = cd.select_publishable(entries, ["C"])
names = [e["name"] for e in sel]
check("only safe + unposted selected", names == ["A"], f"got {names}")
check("unsafe entry excluded", "B" not in names)
check("already-posted excluded", "C" not in names)
check("unreviewed (no flag) excluded", "D" not in names)
check("empty inputs are safe", cd.select_publishable(None, None) == [])

print("T2 — render_digest publishes the REDACTED text, never the raw")
red = [{"name": "E1", "safe_to_publish": True,
        "description": "RAW SECRET should not appear",
        "redacted_description": "redacted body"}]
md = cd.render_digest(red, now=datetime(2026, 8, 4))
check("redacted text present", "redacted body" in md)
check("raw text ABSENT when a redaction exists", "RAW SECRET" not in md, md[:120])
check("falls back to description when no redaction",
      "plain body" in cd.render_digest(
          [{"name": "E2", "safe_to_publish": True, "description": "plain body"}],
          now=datetime(2026, 8, 4)))

print("T3 — render_digest is deterministic and post-shaped")
a = cd.render_digest(red, now=datetime(2026, 8, 4))
b = cd.render_digest(red, now=datetime(2026, 8, 4))
check("deterministic for a fixed clock", a == b)
check("has an H1 title", a.startswith("# CogLog digest — 2026-08-04"), a[:60])
check("has an italic hook line", "\n*" in a and "reviewed and redacted" in a)
check("entry heading rendered", "## E1" in a)
check("singular/plural hook agrees", "1 work-log entry" in a, a[:200])
check("empty entry text skipped",
      "## Blank" not in cd.render_digest(
          [{"name": "Blank", "safe_to_publish": True, "description": "   "}],
          now=datetime(2026, 8, 4)))

print("T4 — write_digest round-trips")
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    p = cd.write_digest("# hi\n", outdir=td, stamp="20260804")
    check("file written", Path(p).exists())
    check("content round-trips", Path(p).read_text() == "# hi\n")
    check("stamped filename", p.endswith("coglog-digest-20260804.md"), p)

print("T5 — fire_coglog_digest NEVER raises (returns a status dict on every failure path)")
real_wd = None
try:
    from cave.core.publishing import coglog_publisher as cp
    real_wd = cp.WORK_DIR
    with tempfile.TemporaryDirectory() as td:
        cp.WORK_DIR = Path(td)  # no review_queue.json in here
        r = cd.fire_coglog_digest()
        check("missing review file -> status dict", isinstance(r, dict) and r.get("status") == "no_review_file", str(r))
        (Path(td) / "review_queue.json").write_text("{ not json")
        r2 = cd.fire_coglog_digest()
        check("unparseable queue -> read_failed, no raise",
              isinstance(r2, dict) and r2.get("status") == "read_failed", str(r2))
        (Path(td) / "review_queue.json").write_text('[{"name":"X","safe_to_publish":false,"description":"no"}]')
        r3 = cd.fire_coglog_digest()
        check("nothing safe -> nothing_to_publish (and nothing written)",
              isinstance(r3, dict) and r3.get("status") == "nothing_to_publish", str(r3))
        (Path(td) / "review_queue.json").write_text('[{"name":"Y","safe_to_publish":true,"description":"yes"}]')
        r4 = cd.fire_coglog_digest(dry_run=True)
        check("dry_run reports without publishing",
              isinstance(r4, dict) and r4.get("status") == "dry_run" and r4.get("entries") == 1, str(r4))
except Exception as e:  # noqa: BLE001
    check("T5 harness ran without raising", False, f"{type(e).__name__}: {e}")
finally:
    if real_wd is not None:
        from cave.core.publishing import coglog_publisher as cp2
        cp2.WORK_DIR = real_wd

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("RESULT: ALL_PASS")
