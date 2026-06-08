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
from datetime import timedelta
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


def _clock() -> Clock:
    """Get a Clock from journal_config.json. Cheap to create."""
    return Clock.from_config()


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

                # Delete stale placeholder
                if autocontext_path.exists():
                    content = autocontext_path.read_text()
                    if "Late contextualization" in content or len(content) < 300:
                        autocontext_path.unlink()

                # Try contextualizer once (non-blocking, best-effort)
                if not autocontext_path.exists():
                    logger.info("Attempting contextualizer for %s (best-effort, one-shot)", name)
                    try:
                        _run_late_contextualization(period, channel_id)
                    except Exception as e:
                        logger.warning("Contextualizer unavailable for %s: %s — firing journal without context", name, e, exc_info=True)
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
_RITUAL_TRIGGERS = {
    "morning-journal": {"agent": "autobiographer_journal", "mode": "journal_morning", "period": "morning"},
    "night-journal": {"agent": "autobiographer_journal", "mode": "journal_evening", "period": "evening"},
    "friendship-saturday": {"agent": "autobiographer_night", "job_type": "friendship"},
}


def _route_trigger(ritual_name: str) -> None:
    """Route ritual trigger to appropriate agent if applicable."""
    trigger = _RITUAL_TRIGGERS.get(ritual_name)
    if not trigger:
        return

    try:
        import httpx
        clock = _clock()
        agent_name = trigger.get("agent", "autobiographer")

        if "job_type" in trigger:
            content = f"Run {trigger['job_type']} contextualization"
        else:
            period = trigger.get("period", "morning")
            autocontext_path = HEAVEN_DATA / f"journal_autocontext_{period}.txt"
            if autocontext_path.exists() and len(autocontext_path.read_text()) > 300:
                autocontext = autocontext_path.read_text().strip()
                content = (
                    f"Here is the context compiled from since the last journal:\n\n"
                    f"{autocontext}\n\n"
                    f"Contextually request my {period} journal now and work it out with me."
                )
            else:
                today = clock.today().replace("-", "_")
                period_cap = period.capitalize()
                content = (
                    f"It's time for my {period} journal. "
                    f"Check CartON for Journal_Autocontext_{period_cap}_{today} if it exists. "
                    f"Then ask me for my {period} journal — walk through the 6 dimensions, "
                    f"ask how I'm feeling, and use journal_entry() to persist."
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
