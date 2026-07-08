"""Pure-logic tests for the journal-trigger pipeline (no LLM, no real network).

Covers the SHARED content builder `build_journal_trigger_content` (freshness gate +
FAIL-LOUD discipline) and the daily `run_ritual_pipeline_selftest`. tmp_path is used as
HEAVEN_DATA; a FakeClock supplies a fixed today ('2026-06-11'). Monkeypatching httpx in
the selftest test captures NETWORK plumbing only — it is NOT an LLM stub.

This test imports the MONOREPO cave source (application/cave/cave/...), not the stale
site-packages copy, so it exercises the change under test.
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Import the monorepo cave source (this file: application/cave/tests/<f>.py;
# parent.parent == application/cave/, which holds the `cave/` package).
_CAVE_ROOT = str(Path(__file__).resolve().parent.parent)
if _CAVE_ROOT not in sys.path:
    sys.path.insert(0, _CAVE_ROOT)

from cave.core.sanctum_automations import (  # noqa: E402
    build_journal_trigger_content,
    run_ritual_pipeline_selftest,
)
import cave.core.sanctum_automations as SA  # noqa: E402


class FakeClock:
    """Minimal Clock stand-in: fixed today, real now/tz for the late-NOTE + selftest."""

    def __init__(self, today_str="2026-06-11"):
        self._today = today_str
        self.tz = ZoneInfo("UTC")

    def today(self):
        return self._today

    def now(self):
        return datetime.now(self.tz)


_BRIEFING = "BRIEFING_SENTINEL " + ("x" * 400)  # >300 chars so the no-placeholder gate passes


def _fail_runner(*a, **k):
    pytest.fail("late_runner must NOT run when the briefing is fresh")


def _raising_runner(*a, **k):
    raise RuntimeError("boom")


def _writing_runner_factory(tmp_path, period):
    """Return a runner that WRITES a fresh >300-char briefing into tmp_path then returns."""
    def _runner(*a, **k):
        p = tmp_path / f"journal_autocontext_{period}.txt"
        p.write_text("LATE_BRIEFING_SENTINEL " + ("y" * 400))
    return _runner


def test_fresh_briefing_injected_with_date(tmp_path):
    p = tmp_path / "journal_autocontext_morning.txt"
    p.write_text(_BRIEFING)  # mtime = now (fresh today)
    content = build_journal_trigger_content("morning", FakeClock(), tmp_path, _fail_runner)
    assert content.startswith("Today is 2026-06-11")
    assert "BRIEFING_SENTINEL" in content            # the briefing text made it in
    print("FRESH_INJECTED_WITH_DATE_OK")


def test_stale_briefing_fails_loud_when_late_compile_fails(tmp_path):
    p = tmp_path / "journal_autocontext_evening.txt"
    p.write_text("Evening Journal — 2026-04-27 fossil briefing " + ("z" * 400))
    # os.utime to April so it is STALE (existence is NOT freshness)
    april = datetime(2026, 4, 27, 9, 0, tzinfo=ZoneInfo("UTC")).timestamp()
    os.utime(p, (april, april))
    content = build_journal_trigger_content("evening", FakeClock(), tmp_path, _raising_runner)
    assert content.startswith("SYSTEM FAILURE:")
    assert "stale since" in content and "Today is 2026-06-11" in content
    assert "2026-04-27" not in content               # the fossil never reaches the agent
    assert not (tmp_path / "journal_autocontext_evening.txt").exists()  # stale file deleted
    print("STALE_FAILS_LOUD_OK")


def test_late_compile_success_is_announced(tmp_path):
    # no file; late_runner WRITES a fresh >300-char briefing into tmp_path then returns
    content = build_journal_trigger_content(
        "morning", FakeClock(), tmp_path, _writing_runner_factory(tmp_path, "morning")
    )
    assert "compiled late at" in content and content.startswith("Today is 2026-06-11")
    print("LATE_COMPILE_NOTED_OK")


def test_absent_and_late_fails_loud(tmp_path):
    content = build_journal_trigger_content("morning", FakeClock(), tmp_path, _raising_runner)
    assert content.startswith("SYSTEM FAILURE:") and "missing" in content
    print("ABSENT_FAILS_LOUD_OK")


def test_selftest_green_and_red(tmp_path, monkeypatch):
    # GREEN scenario: fresh file + httpx.get -> 200 + today's reminded state shows the ritual
    fresh = tmp_path / "journal_autocontext_morning.txt"
    fresh.write_text(_BRIEFING)
    reminded = tmp_path / SA.REMINDED_STATE_FILE.name
    import json as _json
    reminded.write_text(_json.dumps({"date": "2026-06-11", "reminded": ["morning-journal"]}))

    class _Resp200:
        status_code = 200

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp200())
    green_pings = []
    green = run_ritual_pipeline_selftest("morning", clock=FakeClock(), heaven_data=tmp_path, ping=green_pings.append)
    assert green.startswith("🟢 ritual pipeline green (morning")
    assert "server up" in green and "briefing fresh" in green
    assert green_pings == [green]
    print("SELFTEST_GREEN_OK")

    # RED scenario: stale file + dead port + no reminded entry
    stale = tmp_path / "journal_autocontext_morning.txt"
    april = datetime(2026, 4, 27, 9, 0, tzinfo=ZoneInfo("UTC")).timestamp()
    os.utime(stale, (april, april))
    reminded.write_text(_json.dumps({"date": "2026-06-11", "reminded": []}))

    def _raise_get(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr("httpx.get", _raise_get)
    red_pings = []
    red = run_ritual_pipeline_selftest("morning", clock=FakeClock(), heaven_data=tmp_path, ping=red_pings.append)
    assert red.startswith("🔴 RITUAL PIPELINE FAILURE (morning):")
    assert "server unreachable" in red
    assert "briefing stale since" in red
    assert "morning-journal not processed today" in red
    assert red_pings == [red]
    print("SELFTEST_RED_OK")
