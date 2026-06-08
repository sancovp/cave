"""Organ Daemon — Background process for CAVE perception.

Runs World + EventSources in a tick loop, writes events to file inbox.
Always running while Isaac's computer is on.

Usage:
    python -m cave.core.organ_daemon          # foreground
    python -m cave.core.organ_daemon &        # background
    python -m cave.core.organ_daemon --stop   # stop running daemon

Inbox: /tmp/heaven_data/inboxes/main/*.json
PID:   /tmp/heaven_data/organ_daemon.pid
"""
import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from .world import World, WorldEvent, RNGEventSource
from .discord_source import DiscordChannelSource

from .channel import UserDiscordChannel
from .discord_config import load_discord_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [organ_daemon] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

INBOX_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "inboxes" / "main"
# CONNECTS_TO: /tmp/paia_hooks/pending_injection.json (write) — paia hooks read this
INJECTION_FILE = Path("/tmp/paia_hooks/pending_injection.json")
PID_FILE = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "organ_daemon.pid"
TICK_INTERVAL = 30.0
# TRIGGERS: CAVE/sancrev:8080 via HTTP POST for organ ticks and ritual dispatches
CAVE_BASE_URL = os.environ.get("CAVE_URL", "http://localhost:8080")


RITUAL_ALIASES: dict[str, str] = {
    "exercise": "ablutions-and-exercise",
    "ablutions": "ablutions-and-exercise",
    "wb1": "work-block-1",
    "wb2": "work-block-2",
    "break": "midday-break",
    "standdown": "stand-down",
}


def _resolve_ritual_alias(name: str) -> str:
    """Resolve a ritual alias to its canonical name.

    Handles: explicit aliases, space-to-hyphen normalization,
    and time-based 'journal' disambiguation.
    """
    normalized = name.lower().strip()

    # Time-based aliases
    if normalized == "journal":
        hour = datetime.now().hour
        return "morning-journal" if hour < 18 else "night-journal"

    if normalized in ("bfsc", "meditation"):
        hour = datetime.now().hour
        if hour < 12:
            return "morning-bfsc"
        elif hour < 18:
            return "midday-bfsc"
        else:
            return "night-bfsc"

    # Explicit alias lookup
    if normalized in RITUAL_ALIASES:
        return RITUAL_ALIASES[normalized]

    # Space-to-hyphen normalization (e.g. "morning journal" → "morning-journal")
    hyphenated = normalized.replace(" ", "-")
    if hyphenated != normalized:
        return hyphenated

    return normalized


def _extract_discord_message(content: str) -> str:
    """Extract raw user message from Discord source wrapper.

    Input:  '[Discord #123] username: done standup'
    Output: 'done standup'
    """
    # Format: [Discord #channel_id] username: actual_message
    if content.startswith("[Discord #"):
        colon_idx = content.find(": ", content.find("]"))
        if colon_idx != -1:
            return content[colon_idx + 2:]
    return content


def _detect_command(content: str) -> tuple[str, str] | None:
    """Detect a command in Discord message content.

    Returns (command, resolved_argument) tuple or None.
    Currently supports: "done <ritual_name_or_alias>"
    Handles Discord source wrapper format.
    """
    message = _extract_discord_message(content)
    text = message.strip().lower()
    if text.startswith("done "):
        raw_name = message.strip()[5:].strip()
        if raw_name:
            resolved = _resolve_ritual_alias(raw_name)
            return ("done", resolved)
    return None


def _handle_command(command: str, argument: str, source: str = "discord") -> None:
    """Handle a detected command by POSTing to CAVE endpoint."""
    if command == "done":
        try:
            resp = httpx.post(
                f"{CAVE_BASE_URL}/sanctum/ritual/complete",
                json={"ritual_name": argument, "source": source},
                timeout=30.0,
            )
            logger.info("Command 'done %s' → CAVE: %s %s", argument, resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Command 'done %s' failed: %s", argument, e, exc_info=True)


_sent_discord_ids: set = set()


def send_to_conductor(event: WorldEvent) -> str:
    """Send a WorldEvent to Conductor via /messages/send (llegos inbox). Returns message_id."""
    # Deduplicate by discord_message_id to prevent double-delivery across tick cycles
    discord_mid = event.metadata.get("discord_message_id")
    if discord_mid and discord_mid in _sent_discord_ids:
        logger.debug("Skipping duplicate discord_message_id %s", discord_mid)
        return "duplicate"
    if discord_mid:
        _sent_discord_ids.add(discord_mid)
        # Keep set bounded
        if len(_sent_discord_ids) > 500:
            _sent_discord_ids.clear()
    try:
        resp = httpx.post(
            f"{CAVE_BASE_URL}/messages/send",
            json={
                "from_agent": f"world:{event.source}",
                "to_agent": "conductor",
                "content": event.content,
                "ingress": "discord",
                "priority": event.priority,
                "metadata": event.metadata,
            },
            timeout=5.0,
        )
        data = resp.json()
        return data.get("message_id", "unknown")
    except Exception as e:
        logger.error("Failed to send to Conductor via /messages/send: %s", e)
        return "error"


def write_to_injection(event: WorldEvent) -> None:
    """Write a WorldEvent directly to pending_injection.json for immediate context injection."""
    INJECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    pending = []
    if INJECTION_FILE.exists():
        try:
            pending = json.loads(INJECTION_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pending = []
    pending.append({
        "source": "world",
        "event": event.metadata.get("rng_event", event.source),
        "message": event.content,
        "priority": event.priority,
    })
    INJECTION_FILE.write_text(json.dumps(pending, indent=2))


def write_to_inbox(event: WorldEvent) -> str:
    """Write a WorldEvent to file inbox. Returns message_id."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    message_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat()

    message = {
        "id": message_id,
        "from": f"world:{event.source}",
        "to": "main",
        "content": event.content,
        "timestamp": timestamp,
        "priority": event.priority,
        "metadata": event.metadata,
    }
    msg_file = INBOX_DIR / f"{timestamp}_{message_id}.json"
    msg_file.write_text(json.dumps(message, indent=2))
    return message_id


def _write_pid():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid():
    if PID_FILE.exists():
        PID_FILE.unlink()


def _read_pid() -> int | None:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return None


def stop_daemon():
    """Stop a running daemon via PID file."""
    pid = _read_pid()
    if pid is None:
        print("No daemon running (no PID file)")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (pid {pid})")
    except ProcessLookupError:
        print(f"Daemon (pid {pid}) not running, cleaning up PID file")
        _remove_pid()


def run():
    """Organ daemon — DEPRECATED as standalone World poller.

    ARCHITECTURE RULE (Isaac, Mar 01 2026):
    CaveAgent is the ONLY thing that ever runs. ALL World polling and Discord
    routing happens inside CaveAgent's Ears (perceive_world / _route_discord_event).
    organ_daemon must NEVER create its own World or DiscordChannelSource.

    This daemon now only manages PID lifecycle. All event routing has been moved
    to cave.core.mixins.anatomy.Ears.perceive_world().

    Previously this created its own World() with DiscordChannelSource, causing
    double-message delivery (two processes polling same Discord channel with
    same cursor file). See: Bug_Organ_Daemon_Rogue_World_Mar01 in CartON.
    """
    # PID management — kept so health checks can verify daemon is "alive"
    _write_pid()
    running = True

    def _shutdown(signum, frame):
        nonlocal running
        logger.info("Received signal %s, shutting down...", signum)
        running = False

    import threading as _threading
    if _threading.current_thread() is _threading.main_thread():
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

    logger.info("Organ daemon started (pid %d) — PASSIVE MODE (no World, no polling)", os.getpid())
    logger.info("All event routing moved to CaveAgent.ears.perceive_world()")

    try:
        while running:
            # No World.tick() — CaveAgent owns the World.
            # This loop only keeps the PID file alive for health checks.
            time.sleep(TICK_INTERVAL)
    finally:
        _remove_pid()
        logger.info("Organ daemon stopped")


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop_daemon()
    else:
        run()
