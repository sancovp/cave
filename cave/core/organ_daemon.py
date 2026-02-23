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
from .sanctum_source import SanctumRitualSource
from .channel import UserDiscordChannel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [organ_daemon] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

INBOX_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "inboxes" / "main"
PID_FILE = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "organ_daemon.pid"
TICK_INTERVAL = 30.0
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
    """Main daemon loop."""
    # Build World
    world = World()
    world.add_source(RNGEventSource.default_world_events())
    world.add_source(DiscordChannelSource.from_config())
    world.add_source(SanctumRitualSource.from_config())

    # PID management
    _write_pid()
    running = True

    def _shutdown(signum, frame):
        nonlocal running
        logger.info("Received signal %s, shutting down...", signum)
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Discord channel for outbound pings
    discord_out = UserDiscordChannel()
    discord_ok = bool(discord_out.token and discord_out.channel_id)
    if not discord_ok:
        logger.warning("UserDiscordChannel not configured — no Discord pings for rituals")

    # Sources that should also ping Isaac in Discord
    DISCORD_PING_SOURCES = {"sanctum"}

    logger.info("Organ daemon started (pid %d, tick every %.0fs)", os.getpid(), TICK_INTERVAL)
    logger.info("Inbox: %s", INBOX_DIR)
    logger.info("Discord pings: %s", "enabled" if discord_ok else "disabled")
    logger.info("Sources: %s", ", ".join(
        f"{name}({'on' if s.enabled else 'off'})"
        for name, s in world._sources.items()
    ))

    try:
        while running:
            events = world.tick()
            for event in events:
                # Check for commands in Discord messages
                is_command = False
                if event.source == "discord":
                    cmd = _detect_command(event.content)
                    if cmd:
                        command, argument = cmd
                        logger.info("Command detected: %s %s", command, argument)
                        _handle_command(command, argument, source="discord")
                        is_command = True
                        # Still write to inbox for audit, but mark as command
                        event.metadata["command"] = True
                        event.metadata["command_type"] = command
                        event.metadata["command_arg"] = argument

                mid = write_to_inbox(event)
                logger.info("Inbox <- %s: %s (%s)%s", event.source, event.content[:80], mid,
                            " [CMD]" if is_command else "")

                # Ping Isaac in Discord for configured sources (skip commands — they get their own confirmation)
                if discord_ok and event.source in DISCORD_PING_SOURCES and not is_command:
                    try:
                        discord_out.deliver({"message": event.content})
                        logger.info("Discord ping <- %s: %s", event.source, event.content[:60])
                    except Exception as e:
                        logger.error("Discord ping failed: %s", e)
            time.sleep(TICK_INTERVAL)
    finally:
        _remove_pid()
        logger.info("Organ daemon stopped")


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop_daemon()
    else:
        run()
