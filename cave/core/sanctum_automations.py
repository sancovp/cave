"""Sanctum → Automation bridge.

Reads the sanctum schedule, creates one CronAutomation per ritual.
Uses World.Clock for all time — no anchor logic.

On sync:
  1. Read active sanctum + morning_time from journal_config.json
  2. Compute each ritual's cron schedule (timezone-aware via Clock)
  3. Create/update automation JSONs in /tmp/heaven_data/automations/ (TRIGGERS: CronAutomation hot-reload)
  4. Delete stale ritual automations
"""
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .world import Clock

logger = logging.getLogger(__name__)

HEAVEN_DATA = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
SANCTUMS_DIR = HEAVEN_DATA / "sanctums"
JOURNAL_CONFIG = HEAVEN_DATA / "sanctuary" / "journal_config.json"
AUTOMATIONS_DIR = HEAVEN_DATA / "automations"
RITUAL_PREFIX = "sanctum-ritual-"
REMINDED_STATE_FILE = HEAVEN_DATA / "sanctum_reminded.json"
SELFTEST_STATE_FILE = HEAVEN_DATA / "sanctum_selftest.json"

# period → journal ritual name (used by the daily selftest to read REMINDED_STATE_FILE)
_PERIOD_RITUAL = {"morning": "morning-journal", "evening": "night-journal"}


def _clock() -> Clock:
    """Get a Clock from journal_config.json. Cheap to create."""
    return Clock.from_config()


def _is_fresh_today(path: Path) -> bool:
    """True iff `path` exists AND its mtime falls on today's date (in the clock's tz).

    FAIL-LOUD discipline: a missing file, or ANY unexpected stat/IO fault, returns
    False (treated as STALE). The freshness probe itself never crashes the trigger
    dispatch, but a stale/missing briefing is NEVER silently accepted as fresh — the
    caller turns False into the loud-failure path. NOTE: existence is NOT freshness;
    a real-but-ancient briefing (the 44-day "2026-04-27" bug) is correctly stale here.
    """
    clock = _clock()
    try:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime, clock.tz)
        return mtime.strftime("%Y-%m-%d") == clock.today()
    except OSError:
        return False


def _briefing_state(path: Path) -> str:
    """Human-readable reason a briefing is not fresh: 'missing' | 'stale since <ts>' | 'unreadable'.

    Used to name the failure on the ERROR log + the human-facing SYSTEM FAILURE message.
    """
    clock = _clock()
    try:
        if not path.exists():
            return "missing"
        mtime = datetime.fromtimestamp(path.stat().st_mtime, clock.tz)
        return f"stale since {mtime.strftime('%Y-%m-%d %H:%M')}"
    except OSError as e:
        return f"unreadable ({e})"


def _get_morning_time() -> str:
    """Read morning time from journal config."""
    if JOURNAL_CONFIG.exists():
        try:
            jc = json.loads(JOURNAL_CONFIG.read_text())
            return jc.get("morning_time", "09:00")
        except (json.JSONDecodeError, OSError):
            pass
    return "09:00"


def _get_sanctum_channel_id() -> str:
    """Read sanctum Discord channel ID from discord config."""
    cfg_path = HEAVEN_DATA / "discord_config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text()).get("sanctum_channel_id", "")
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def _load_active_sanctum() -> tuple:
    """Load active sanctum name + data. Returns (name, data) or ("", None)."""
    config_path = SANCTUMS_DIR / "_config.json"
    if not config_path.exists():
        return "", None
    try:
        name = json.loads(config_path.read_text()).get("current", "")
        if not name:
            return "", None
        sanctum_path = SANCTUMS_DIR / f"{name}.json"
        if not sanctum_path.exists():
            return name, None
        return name, json.loads(sanctum_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load sanctum: %s", e, exc_info=True)
        return "", None


def _extract_weekly_day(ritual_name: str) -> Optional[int]:
    """Extract day-of-week from ritual name. Returns cron DOW or None."""
    name_lower = ritual_name.lower()
    for day, dow in [("sunday", 0), ("monday", 1), ("tuesday", 2),
                     ("wednesday", 3), ("thursday", 4), ("friday", 5), ("saturday", 6)]:
        if day in name_lower:
            return dow
    return None


def _load_sanctum_context() -> Optional[Dict[str, Any]]:
    """Load sanctum name, data, morning time, channel ID, active rituals."""
    sanctum_name, sanctum_data = _load_active_sanctum()
    if not sanctum_data:
        return None
    morning_time = _get_morning_time()
    channel_id = _get_sanctum_channel_id()
    h, m = map(int, morning_time.split(":"))
    rituals = sanctum_data.get("rituals", [])
    active_rituals = [r for r in rituals if r.get("active", True)]
    return {
        "sanctum_name": sanctum_name, "sanctum_data": sanctum_data,
        "morning_time": morning_time, "channel_id": channel_id,
        "h": h, "m": m, "active_rituals": active_rituals,
    }


def _is_completed_today(ritual: Dict, today: str) -> bool:
    """Check if ritual has a completion (done or skipped) for today's date."""
    for c in ritual.get("completions", []):
        if str(c.get("date", "")).startswith(today):
            return True
    return False


def _filter_todays_rituals(active_rituals: List[Dict], day_of_week: str) -> List[Dict]:
    """Filter rituals that apply today based on frequency."""
    result = []
    for r in active_rituals:
        freq = r.get("frequency", "daily").lower()
        if freq == "daily":
            result.append(r)
        elif freq == "weekly" and day_of_week in r.get("name", "").lower():
            result.append(r)
    return result


def _compute_schedule(rituals: List[Dict], start_hour: int, start_minute: int, clock: Clock):
    """Compute sequential schedule starting at morning_time today (clock-aware)."""
    now = clock.now()
    start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    schedule = []
    current = start
    for r in rituals:
        schedule.append((r["name"], r.get("description", ""), current, r))
        current = current + timedelta(minutes=r.get("duration_minutes", 30))
    return schedule


# ─── Sync ritual automations ────────────────────────────────────────────────


def sync_ritual_automations() -> Dict[str, Any]:
    """Sync sanctum rituals → CronAutomation JSONs.

    Creates one automation per active ritual. Deletes stale ones.
    Called at server start and after ritual changes (done/skip).
    """
    AUTOMATIONS_DIR.mkdir(parents=True, exist_ok=True)

    ctx = _load_sanctum_context()
    if not ctx:
        logger.warning("No active sanctum — skipping ritual automation sync")
        return {"status": "no_sanctum"}

    channel_id = ctx["channel_id"]
    sanctum_name = ctx["sanctum_name"]
    active_rituals = ctx["active_rituals"]
    h, m = ctx["h"], ctx["m"]

    # Schedule times use morning_time in clock's timezone
    clock = _clock()
    now = clock.now()
    current_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
    created = []
    expected_names = set()

    for ritual in active_rituals:
        name = ritual["name"]
        desc = ritual.get("description", "")
        freq = ritual.get("frequency", "daily").lower()
        duration = ritual.get("duration_minutes", 30)

        ritual_hour = current_time.hour
        ritual_minute = current_time.minute

        if freq == "daily":
            cron_expr = f"{ritual_minute} {ritual_hour} * * *"
        elif freq == "weekly":
            dow = _extract_weekly_day(name)
            if dow is None:
                logger.warning("Weekly ritual '%s' has no day in name — skipping", name)
                current_time = current_time + timedelta(minutes=duration)
                continue
            cron_expr = f"{ritual_minute} {ritual_hour} * * {dow}"
        elif freq == "monthly":
            cron_expr = f"{ritual_minute} {ritual_hour} 1 * *"
        else:
            current_time = current_time + timedelta(minutes=duration)
            continue

        auto_name = f"{RITUAL_PREFIX}{name}"
        expected_names.add(auto_name)

        auto_json = {
            "name": auto_name,
            "description": f"SANCTUM ritual: {name} — {desc}",
            "schedule": cron_expr,
            "code_pointer": "cave.core.sanctum_automations.fire_ritual_notification",
            "code_args": {
                "ritual_name": name,
                "description": desc,
                "channel_id": channel_id,
                "sanctum_name": sanctum_name,
            },
            "priority": 6,
            "tags": ["sanctum", "ritual", freq],
            "enabled": True,
        }

        auto_path = AUTOMATIONS_DIR / f"{auto_name}.json"
        auto_path.write_text(json.dumps(auto_json, indent=2))
        created.append(name)

        current_time = current_time + timedelta(minutes=duration)

    # Delete stale ritual automations
    deleted = []
    for json_file in AUTOMATIONS_DIR.glob(f"{RITUAL_PREFIX}*.json"):
        if json_file.stem not in expected_names:
            json_file.unlink()
            deleted.append(json_file.stem)

    logger.info("Synced %d ritual automations (deleted %d stale)", len(created), len(deleted))
    return {"status": "synced", "created": created, "deleted": deleted}


# ─── Catch-up missed rituals ────────────────────────────────────────────────

_JOURNAL_ORDER = ["morning-journal", "night-journal"]


def catch_up_missed_rituals() -> Dict[str, Any]:
    """Check for past-due rituals and fire notifications.

    Uses Clock for all time. No anchor logic.
    "Today" = clock.today() (one date, one check).
    Contextualizer is best-effort (journal fires with or without autocontext).
    """
    clock = _clock()
    today = clock.today()
    now = clock.now()

    ctx = _load_sanctum_context()
    if not ctx:
        return {"status": "no_sanctum"}

    sanctum_name = ctx["sanctum_name"]
    channel_id = ctx["channel_id"]
    h, m = ctx["h"], ctx["m"]
    active_rituals = ctx["active_rituals"]

    # Filter rituals for today
    todays_rituals = _filter_todays_rituals(active_rituals, clock.day_of_week())

    # Compute schedule from morning_time
    schedule = _compute_schedule(todays_rituals, h, m, clock)

    # Check completions — one date, one check
    completed_today = set()
    for r in todays_rituals:
        if _is_completed_today(r, today):
            completed_today.add(r["name"])

    # Load reminded state (notification dedup only)
    reminded = set()
    if REMINDED_STATE_FILE.exists():
        try:
            data = json.loads(REMINDED_STATE_FILE.read_text())
            if data.get("date") == today:
                reminded = set(data.get("reminded", []))
        except (json.JSONDecodeError, OSError):
            pass

    # Find past-due rituals NOT completed today
    past_due = []
    for name, desc, sched_time, ritual in schedule:
        if now >= sched_time and name not in completed_today:
            past_due.append((name, desc, sched_time, ritual))

    # Daily pipeline selftest — runs on the SAME automation schedule as catch-up,
    # AFTER ritual evaluation, exactly once per period per day (≥30 min past target).
    # Placed before the early returns so it fires even when nothing was missed.
    # Journal target = morning_time (h:m); evening uses night_time when available.
    _maybe_run_daily_selftest("morning", clock, h, m)
    nh, nm = h, m
    if JOURNAL_CONFIG.exists():
        try:
            _jc = json.loads(JOURNAL_CONFIG.read_text())
            nh, nm = map(int, _jc.get("night_time", f"{h:02d}:{m:02d}").split(":"))
        except (json.JSONDecodeError, OSError, ValueError):
            nh, nm = h, m
    _maybe_run_daily_selftest("evening", clock, nh, nm)

    if not past_due:
        return {"status": "nothing_missed"}

    # Journal ordering — later journal supersedes earlier
    due_journals = [name for name, _, _, _ in past_due if name in _JOURNAL_ORDER]
    missed_journals = set()
    if due_journals:
        latest_idx = max(_JOURNAL_ORDER.index(j) for j in due_journals)
        for j in _JOURNAL_ORDER[:latest_idx]:
            if j not in completed_today:
                missed_journals.add(j)

    results = {"caught_up": [], "missed": []}

    for name, desc, sched_time, ritual in past_due:
        if name in missed_journals:
            # Skip once — don't re-skip if already skipped today
            if name not in completed_today:
                logger.info("Ritual MISSED: %s (later journal supersedes)", name)
                _log_missed_ritual(name, sanctum_name, today, channel_id)
                results["missed"].append(name)
            continue

        # Fire notification ONCE per day
        if name not in reminded:
            # Journal rituals: try contextualizer ONCE (best-effort, not a gate)
            trigger = _RITUAL_TRIGGERS.get(name)
            if trigger and "period" in trigger:
                period = trigger["period"]
                autocontext_path = HEAVEN_DATA / f"journal_autocontext_{period}.txt"

                # Delete stale/placeholder briefing so the one-shot contextualizer
                # re-runs — FAIL LOUD (a stale briefing is a producer failure, never
                # silently tolerated). Existence is NOT freshness: delete if placeholder
                # OR not fresh-today, so a real-but-ancient briefing is refreshed.
                if autocontext_path.exists():
                    file_content = autocontext_path.read_text()
                    if (not _is_fresh_today(autocontext_path)
                            or "Late contextualization" in file_content
                            or len(file_content) < 300):
                        logger.error(
                            "SYSTEM FAILURE: %s autocontext briefing is %s (placeholder/stale) — "
                            "the night-tick contextualize producer did not refresh it; deleting so "
                            "the one-shot contextualizer re-runs", period, _briefing_state(autocontext_path),
                        )
                        try:
                            autocontext_path.unlink()
                        except OSError as e:
                            logger.error("Could not delete stale briefing %s: %s", autocontext_path, e)

                # Try contextualizer once (one-shot late repair — the designed mechanism)
                if not autocontext_path.exists():
                    logger.info("Attempting contextualizer for %s (one-shot late repair)", name)
                    try:
                        _run_late_contextualization(period, channel_id)
                    except Exception as e:
                        logger.error("SYSTEM FAILURE: late contextualization for %s failed: %s — firing journal without fresh context", name, e, exc_info=True)
            fire_ritual_notification(
                ritual_name=name, description=desc,
                channel_id=channel_id, sanctum_name=sanctum_name,
            )
            reminded.add(name)
            results["caught_up"].append(name)

    # Persist reminded state (keyed by today's date)
    REMINDED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    REMINDED_STATE_FILE.write_text(json.dumps({"date": today, "reminded": list(reminded)}))

    logger.info("Catch-up complete: %d caught up, %d missed", len(results["caught_up"]), len(results["missed"]))
    return results


# ─── Helpers ────────────────────────────────────────────────────────────────


def _log_missed_ritual(name: str, sanctum_name: str, date: str, channel_id: str) -> None:
    """Log a missed ritual to Discord + sanctum JSON as skipped. Idempotent per day."""
    # Mark as skipped in sanctum (handle_skip has its own idempotency check now)
    try:
        from .sanctum_cli import handle_skip
        handle_skip(name)
    except Exception as e:
        logger.warning("Failed to auto-skip missed ritual %s: %s", name, e)

    # Notify Discord — ONCE (caller checks completed_today before calling)
    if channel_id:
        try:
            from .channel import UserDiscordChannel
            discord = UserDiscordChannel(channel_id=channel_id)
            if discord.token and discord.channel_id:
                discord.deliver({"message": f"⏭ **MISSED:** {name} — auto-skipped (deadline passed)"})
        except Exception as e:
            logger.warning("Failed to notify missed ritual: %s", e, exc_info=True)


def _run_late_contextualization(period: str, channel_id: str) -> None:
    """Run journal contextualization. Best-effort, non-blocking."""
    import httpx

    logger.info("Running late %s contextualization via autobiographer_night agent", period)

    # TRIGGERS: CAVE/sancrev:8080/agents/autobiographer_night/message via HTTP POST
    response = httpx.post(
        "http://localhost:8080/agents/autobiographer_night/message",
        json={"content": json.dumps({"job_type": "contextualize", "period": period}), "source": "sanctum_catchup", "priority": 9},
        timeout=30,
    )
    response.raise_for_status()
    logger.info("Late %s contextualization dispatched to night agent: %s", period, response.status_code)


def _default_selftest_ping(text: str) -> None:
    """Production ping for the selftest line — the sanctum Discord channel.

    The module's existing Discord mechanism (UserDiscordChannel to the sanctum
    channel) is the module-level equivalent of the Ears `_ping_discord` path used by
    the night-tick. Best-effort, never raises into the selftest.
    """
    channel_id = _get_sanctum_channel_id()
    if not channel_id:
        return
    try:
        from .channel import UserDiscordChannel
        discord = UserDiscordChannel(channel_id=channel_id)
        if discord.token and discord.channel_id:
            discord.deliver({"message": text})
    except Exception as e:
        logger.error("Selftest ping failed: %s", e, exc_info=True)


def run_ritual_pipeline_selftest(period: str, clock=None, heaven_data=None, ping=None) -> str:
    """Daily pure-Python (ZERO LLM) self-test of the ritual/journal pipeline.

    Checks, in order:
      1. GET http://localhost:8080/health == 200 (httpx, 5s timeout) — server up.
      2. _is_fresh_today(journal_autocontext_{period}.txt) — briefing fresh today.
      3. The trigger-reminded state file shows today's journal ritual processed
         (REMINDED_STATE_FILE: date==today AND the period's ritual in `reminded`).

    Builds EXACTLY one line. All pass →
      "🟢 ritual pipeline green ({period}: briefing fresh {HH:MM}, server up)"
    else →
      "🔴 RITUAL PIPELINE FAILURE ({period}): {comma-list of exact failed checks with values}".

    Sends it via `ping` (production default = the sanctum Discord ping; tests pass a
    list.append). Returns the line. FAIL-LOUD: any failed check is named with its value;
    nothing is silently swallowed.
    """
    clock = clock or _clock()
    hd = Path(heaven_data) if heaven_data is not None else HEAVEN_DATA
    ping = ping if ping is not None else _default_selftest_ping
    today = clock.today()

    failures = []

    # Check 1: server health
    try:
        import httpx
        resp = httpx.get("http://localhost:8080/health", timeout=5)
        if resp.status_code != 200:
            failures.append(f"server health http {resp.status_code}")
    except Exception as e:
        failures.append(f"server unreachable ({e})")

    # Check 2: briefing freshness today
    briefing_path = hd / f"journal_autocontext_{period}.txt"
    briefing_hhmm = ""
    if _is_fresh_today(briefing_path):
        try:
            mtime = datetime.fromtimestamp(briefing_path.stat().st_mtime, clock.tz)
            briefing_hhmm = mtime.strftime("%H:%M")
        except OSError:
            briefing_hhmm = "??:??"
    else:
        failures.append(f"briefing {_briefing_state(briefing_path)}")

    # Check 3: today's journal ritual processed (reminded state)
    reminded_state_file = hd / REMINDED_STATE_FILE.name
    ritual_name = _PERIOD_RITUAL.get(period, f"{period}-journal")
    processed = False
    if reminded_state_file.exists():
        try:
            data = json.loads(reminded_state_file.read_text())
            if data.get("date") == today and ritual_name in data.get("reminded", []):
                processed = True
        except (json.JSONDecodeError, OSError):
            pass
    if not processed:
        failures.append(f"ritual {ritual_name} not processed today")

    if not failures:
        line = f"🟢 ritual pipeline green ({period}: briefing fresh {briefing_hhmm}, server up)"
    else:
        line = f"🔴 RITUAL PIPELINE FAILURE ({period}): {', '.join(failures)}"

    try:
        ping(line)
    except Exception as e:
        logger.error("Selftest ping callable raised: %s", e, exc_info=True)
    return line


def _maybe_run_daily_selftest(period: str, clock, h: int, m: int) -> None:
    """Run the daily selftest EXACTLY once per period per day, ≥30 min past journal target.

    Reads SELFTEST_STATE_FILE (sibling of REMINDED_STATE_FILE, same json shape:
    {"date": today, "ran": [periods...]}). If now ≥ journal target + 30 min and today's
    {period} has not been recorded → run the selftest and record it. Idempotent per day.
    Wired into catch_up_missed_rituals (runs on the automation schedule).
    """
    now = clock.now()
    today = clock.today()
    target_min = h * 60 + m + 30
    current_min = now.hour * 60 + now.minute
    if current_min < target_min:
        return

    ran = []
    if SELFTEST_STATE_FILE.exists():
        try:
            data = json.loads(SELFTEST_STATE_FILE.read_text())
            if data.get("date") == today:
                ran = list(data.get("ran", []))
        except (json.JSONDecodeError, OSError):
            pass
    if period in ran:
        return

    run_ritual_pipeline_selftest(period, clock=clock)

    ran.append(period)
    SELFTEST_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SELFTEST_STATE_FILE.write_text(json.dumps({"date": today, "ran": ran}))


# ─── Fire ritual notification ───────────────────────────────────────────────


def fire_ritual_notification(
    ritual_name: str = "",
    description: str = "",
    channel_id: str = "",
    sanctum_name: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """Fire a single ritual notification. Called by CronAutomation.

    Sends Discord notification + routes journal/friendship triggers.
    """
    clock = _clock()
    today = clock.today()

    # Check if already completed today — don't nag
    if sanctum_name and ritual_name:
        sanctum_path = SANCTUMS_DIR / f"{sanctum_name}.json"
        if sanctum_path.exists():
            try:
                sanctum = json.loads(sanctum_path.read_text())
                for r in sanctum.get("rituals", []):
                    if r.get("name") == ritual_name:
                        if _is_completed_today(r, today):
                            logger.info("Ritual '%s' already done today — skipping notification", ritual_name)
                            return {"ritual": ritual_name, "status": "already_done"}
                        break
            except (json.JSONDecodeError, OSError):
                pass

    message = f"[SANCTUM] Ritual due: {ritual_name} — {description}"

    # Send to Discord
    discord_result = {"discord": "no_channel"}
    if channel_id:
        try:
            from .channel import UserDiscordChannel
            discord = UserDiscordChannel(channel_id=channel_id)
            if discord.token and discord.channel_id:
                result = discord.deliver({"message": message})
                discord_result = {"discord": "sent", "message_id": result.get("discord_message_id")}
                logger.info("Ritual notification sent: %s → channel %s", ritual_name, channel_id[:6])
        except Exception as e:
            logger.error("Ritual Discord notification failed: %s", e, exc_info=True)
            discord_result = {"discord": "error", "error": str(e)}

    # Route journal/friendship triggers to autobiographer
    _route_trigger(ritual_name)

    return {"ritual": ritual_name, **discord_result}


# Ritual name → agent trigger mapping
# All journal-flow rituals (morning/evening/friendship) hand off to the JOURNAL
# agent in the JOURNAL channel where the user CAN speak. The night agent only
# CONTEXTUALIZES ahead of time (its Job B/C heart ticks build the autocontext);
# the night channel carries only night's own archive output, never a ritual the
# user is asked to act on. (Fixes the May26 bug: friendship summary landed in the
# NIGHT channel — "use friendship ritual" — where the user cannot respond.)
_RITUAL_TRIGGERS = {
    "morning-journal": {"agent": "autobiographer_journal", "mode": "journal_morning", "period": "morning"},
    "night-journal": {"agent": "autobiographer_journal", "mode": "journal_evening", "period": "evening"},
    "friendship-saturday": {"agent": "autobiographer_journal", "mode": "friendship", "kind": "friendship"},
}


def build_journal_trigger_content(period, clock, heaven_data, late_runner) -> str:
    """Build the journal-trigger CONTENT STRING with the freshness gate + FAIL-LOUD discipline.

    PURE module-level builder SHARED by BOTH journal-trigger call sites —
    sanctum_automations._route_trigger (httpx.post dispatch) AND
    anatomy._route_sanctum_trigger (UserPromptMessage enqueue dispatch) — so the
    content logic has ONE implementation and ZERO drift. Only the DISPATCH mechanism
    differs per call site; the content string is identical.

    Args:
        period: 'morning' | 'evening'.
        clock: the World.Clock — supplies today() (+ now() for the late-NOTE branch).
            EVERY returned branch LEADS with today's date (the date-blindness cure;
            never a raw datetime.now() date-leak, never a pasted ancient date).
        heaven_data: the HEAVEN_DATA dir; the briefing path is computed as
            heaven_data / f"journal_autocontext_{period}.txt".
        late_runner: zero-arg callable that attempts the one-shot late contextualization
            (the designed repair, NOT a fallback). When the briefing is not fresh it is
            invoked ONCE; any exception is captured and surfaced LOUDLY. Production passes
            `lambda: _run_late_contextualization(period, _get_sanctum_channel_id())`; tests
            inject a deterministic runner.

    Returns the content string. A stale/missing briefing (existence is NOT freshness —
    the 44-day "2026-04-27" bug) yields a LOUD 'SYSTEM FAILURE:' message that LEADS the
    content so the human sees it in the journal flow — NEVER a silent chipper
    "It's time for my ... journal" fallback (that branch DIES).
    """
    today = clock.today()
    # Weekday APPENDED in parens (LLMs miscompute weekdays from bare dates — the
    # "Wednesday June 11" slip, 2026-06-11); parenthesized so "Today is {today}"
    # prefix assertions stay stable.
    from datetime import datetime as _dt2
    try:
        today = f"{today} ({_dt2.strptime(today, '%Y-%m-%d').strftime('%A')})"
    except ValueError:
        pass  # unexpected clock format: date alone is still correct
    autocontext_path = Path(heaven_data) / f"journal_autocontext_{period}.txt"

    if _is_fresh_today(autocontext_path):
        autocontext = autocontext_path.read_text().strip()
        return (
            f"Today is {today} and this is the {period} journal trigger.\n\n"
            f"Here is the context compiled since the last journal:\n\n"
            f"{autocontext}\n\n"
            f"OPEN your first message by STATING today's date ({today}) explicitly — the "
            f"human must always see what day the journal is for. Then contextually request "
            f"my {period} journal and work it out with me."
        )

    # PIPELINE FAILURE — log LOUDLY (ERROR), naming the file, its state, and the
    # producer that should have written it. Then attempt the one-shot late
    # contextualization ONCE (the designed repair). Delete the stale cache first so
    # the repair writes clean.
    state = _briefing_state(autocontext_path)
    logger.error(
        "SYSTEM FAILURE: %s autocontext briefing is %s at %s — the scheduled "
        "night-tick contextualize producer did not write it; attempting one-shot "
        "late contextualization (producer=night-tick contextualize job)",
        period, state, autocontext_path,
    )
    if autocontext_path.exists():
        try:
            autocontext_path.unlink()
        except OSError as e:
            logger.error("Could not delete stale briefing %s: %s", autocontext_path, e)

    late_error = None
    if late_runner is not None:
        try:
            late_runner()
        except Exception as e:  # repair is best-effort; surfaced loudly below
            late_error = e
            logger.error(
                "SYSTEM FAILURE: late %s contextualization failed: %s", period, e, exc_info=True,
            )

    if late_error is None and _is_fresh_today(autocontext_path):
        # Late repair produced a fresh briefing — inject it, but DISCLOSE it ran late.
        autocontext = autocontext_path.read_text().strip()
        return (
            f"Today is {today} and this is the {period} journal trigger.\n\n"
            f"NOTE: the scheduled contextualizer did not run; this briefing was "
            f"compiled late at {clock.now().strftime('%H:%M')}.\n\n"
            f"{autocontext}\n\n"
            f"OPEN your first message by STATING today's date ({today}) explicitly — the "
            f"human must always see what day the journal is for. Then contextually request "
            f"my {period} journal and work it out with me."
        )

    # Late repair ALSO failed (or was not attempted) — the human MUST see the failure
    # FIRST, in the journal flow itself, never a normal-looking prompt. The human
    # message names the failure DATE-FREE (the precise stale mtime is in the ERROR log
    # above) — embedding the ancient date in the agent's prompt is the very date-leak
    # that caused this bug.
    # The human-facing failure names the state {missing | stale since ...} per spec,
    # but DATE-FREE: the precise stale mtime is in the ERROR log above; embedding the
    # ancient date in the agent's prompt is the very date-leak that caused this bug
    # (the 44-day "2026-04-27" fossil). So the missing-case is literal "missing" and
    # the stale-case says "stale since the last successful compile" — names the
    # failure, leaks no fossil date.
    human_state = "missing" if state == "missing" else "stale since the last successful compile (not refreshed today)"
    reason = (f"failed ({late_error})" if late_error is not None
              else "did not produce a fresh briefing")
    return (
        f"SYSTEM FAILURE: the {period} autocontext briefing is {human_state} and late "
        f"contextualization {reason}. Today is {today}. Tell Isaac plainly that the "
        f"contextualizer pipeline failed before doing anything else, then run the "
        f"{period} journal with him manually."
    )


def _route_trigger(ritual_name: str) -> None:
    """Route ritual trigger to appropriate agent if applicable."""
    trigger = _RITUAL_TRIGGERS.get(ritual_name)
    if not trigger:
        return

    try:
        import httpx
        clock = _clock()
        agent_name = trigger.get("agent", "autobiographer")

        # DATE-BLINDNESS CURE: every constructed `content` LEADS with today's date,
        # ahead of any pasted briefing — so no pasted (possibly stale) briefing can
        # ever out-date the agent's message (the "Evening Journal — 2026-04-27" bug).
        today = clock.today()

        if "job_type" in trigger:
            content = (
                f"Today is {today} and this is the {trigger['job_type']} contextualization trigger. "
                f"Run {trigger['job_type']} contextualization."
            )
        elif trigger.get("kind") == "friendship":
            # Friendship hands off to the JOURNAL agent in friendship mode. The
            # Night agent's Job C tick built Friendship_Autocontext_{today} ahead
            # of time; the journal agent's friendship-mode system prompt reads it
            # (get_concept) and runs the ritual collaboratively with the user.
            today_us = today.replace("-", "_")
            content = (
                f"Today is {today} and this is the weekly Friendship ritual trigger.\n\n"
                "It's time for the weekly Friendship ritual (Act 3B — the RETURN). "
                f"The Night agent prepared Friendship_Autocontext_{today_us}. "
                "Read it, present both protagonist tracks (what the system did + what "
                "Isaac did this week), run the TWI compliance check, decide TWI changes "
                "+ deliverables, and close with friendship_journal()."
            )
        else:
            # Journal trigger. The CONTENT STRING (freshness gate + FAIL-LOUD
            # discipline: existence is NOT freshness; a stale/missing briefing is a
            # LOUD pipeline failure, never a silent chipper fallback) is built by the
            # SHARED module-level helper so this HTTP path and anatomy's enqueue path
            # have ONE implementation, zero drift. Only the DISPATCH below (httpx.post)
            # differs. The late repair is the one-shot late contextualization (designed
            # mechanism, NOT a fallback), injected so it is the same in both call sites.
            period = trigger.get("period", "morning")
            content = build_journal_trigger_content(
                period, clock, HEAVEN_DATA,
                late_runner=lambda: _run_late_contextualization(period, _get_sanctum_channel_id()),
            )

        try:
            # D1 FIX (investigation #5): carry the ritual's DECLARED mode so the agent
            # fires in the right mode (e.g. night-journal → journal_evening). The
            # /agents/{name}/message route applies it via set_mode before processing.
            # Without this the persistent autobiographer_journal stays in its boot mode
            # (journal_morning) and the evening journal fires as morning.
            payload = {"content": content, "source": "sanctum", "priority": 8}
            if "mode" in trigger:
                payload["mode"] = trigger["mode"]
            # TRIGGERS: CAVE/sancrev:8080/agents/{agent_name}/message via HTTP POST
            httpx.post(
                f"http://localhost:8080/agents/{agent_name}/message",
                json=payload,
                timeout=5,
            )
            logger.info("Ritual trigger routed: %s → %s", ritual_name, agent_name)
        except Exception as e:
            logger.warning("Failed to route trigger %s → %s: %s", ritual_name, agent_name, e)

    except Exception as e:
        logger.error("Ritual trigger routing error: %s", e, exc_info=True)
