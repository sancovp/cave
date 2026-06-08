"""Channel - Typed delivery targets for Automations.

UserChannel = delivery TO human (simple: post where configured)
AgentChannel = delivery TO agent (complex: inbox + wake + processing)

Same transports (Discord, etc.) but different semantics per receiver.

# =============================================================================
# CAVE_REFACTOR: CHANNEL CHANGES (from CAVE_REFACTOR_ANALYSIS.md Stage 2)
# =============================================================================
#
# CURRENT: Channels are OUTPUT-ONLY (deliver() only, no receive()).
#          Not connected to agents — standalone objects used ad-hoc.
#          Conductor creates UserDiscordChannel() directly instead of
#          asking CAVE "send this through my configured channel."
#
# TARGET: A Channel IS a CONVERSATION with its own transcript/history.
#         NOT a transport pipe — a conversation track.
#         The transport (Discord API, tmux send-keys) is just how bytes
#         move in and out of that conversation history.
#         Channel wraps the native history object (Heaven history,
#         Claude transcript, tmux capture, etc.)
#
# class Channel(ABC):
#     \"\"\"A conversation the agent has. Stage 2.\"\"\"
#
#     @abstractmethod
#     def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
#         \"\"\"Send payload OUT through this conversation.\"\"\"
#         ...
#
#     @abstractmethod
#     def receive(self) -> Optional[Dict[str, Any]]:
#         \"\"\"Receive payload IN from this conversation. Stage 2 addition.
#         Result gets fed to inbox.enqueue().
#         \"\"\"
#         ...
#
#     @abstractmethod
#     def channel_type(self) -> str:
#         \"\"\"Return channel type identifier.\"\"\"
#         ...
#
#
# CHANNEL ≠ INBOX. Channel is a conversation (with history). Inbox is a queue.
#   channel.receive() → inbox.enqueue(message)   [input path]
#   inbox.dequeue() → agent processes → channel.deliver(response)  [output path]
#   Inbox MEDIATES across channels — messages from ANY conversation get
#   enqueued, processed in priority order, response routes back to the
#   originating channel (the right conversation/history).
#
# CentralChannel = an agent's collection of conversation types.
#   Every agent has one. It IS the set of conversations that agent has.
#   Splitting = SEPARATE CONVERSATIONS with SEPARATE TRANSCRIPTS.
#   NOT separate transports — separate histories.
#
#   Examples:
#     Conductor:      {main: discord_user_chat, heartbeat: heartbeat_convo}
#     Autobiographer: {chat: memory_chat, journal: journal_convo, night: night_convo}
#     GNOSYS:         {main: tmux_session}
#     OpenClaw:       {main: discord_pipe}
#
# CAVEAgent.CentralChannel = the COMPLETE MAP of all agents + all conversations.
#   It IS the routing table for the entire system.
#   Nadis = external inputs (Discord channels, cron timers, webhooks) that
#   flow INTO agent CentralChannels:
#     Discord #conductor-whisper  →  conductor.main
#     Discord heartbeat timer     →  conductor.heartbeat
#     Discord #journal            →  autobiographer.journal
#     Cron 6AM/10PM               →  autobiographer.journal
#     tmux session                →  gnosys.main
#     Discord #openclaw           →  openclaw.main
#     Webhook /webhook/{name}     →  wherever automation routes
#
# =============================================================================
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChannelMode:
    """Channel mode constants.

    mirror: channel is an INPUT source — Ears polls it, feeds agent inbox
    broadcast: channel receives agent OUTPUT — transcript, events, turn-by-turn
    deliverable: channel receives the final RESULT of agent.run() — typed output, not transcript
    """
    MIRROR = "mirror"
    BROADCAST = "broadcast"
    DELIVERABLE = "deliverable"


class Channel(ABC):
    """A conversation the agent has.

    CAVE_REFACTOR Stage 2: Channels are BIDIRECTIONAL conversations.
    A Channel IS a conversation with its own transcript/history.
    The transport (Discord API, tmux, file I/O) is just how bytes
    move in and out of that conversation history.

    deliver() = send OUT through this conversation
    receive() = receive IN from this conversation

    Modes determine how the channel is used:
    - mirror: Ears polls this channel for input
    - broadcast: agent output goes here
    - deliverable: agent.run() result goes here
    """

    _modes: List[str] = []

    def set_modes(self, modes: List[str]) -> None:
        """Set channel modes."""
        self._modes = modes

    @property
    def modes(self) -> List[str]:
        return self._modes

    @property
    def is_mirror(self) -> bool:
        return ChannelMode.MIRROR in self._modes

    @property
    def is_broadcast(self) -> bool:
        return ChannelMode.BROADCAST in self._modes

    @property
    def is_deliverable(self) -> bool:
        return ChannelMode.DELIVERABLE in self._modes

    @abstractmethod
    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send payload OUT through this conversation. Returns result dict."""
        ...

    @abstractmethod
    def receive(self) -> Optional[Dict[str, Any]]:
        """Receive payload IN from this conversation.

        Returns None if no message available.
        The agent's polling loop or CAVEAgent wiring calls this.
        Result gets fed to inbox.enqueue() by the wiring layer.
        """
        ...

    @abstractmethod
    def channel_type(self) -> str:
        """Return channel type identifier."""
        ...


# === User Channels (delivery TO human) ===


class UserChannel(Channel):
    """Conversation with the human. Deliver = send to human, receive = get from human."""

    def receive(self) -> Optional[Dict[str, Any]]:
        """User channels receive via external push (Discord events, webhooks).
        Default: return None (push-based channels don't poll).
        CAVEAgent wiring handles the push path.
        """
        return None


@dataclass
class UserDiscordChannel(UserChannel):
    """Bidirectional Discord channel conversation.

    deliver() = post TO Discord (outbound)
    receive() = poll FROM Discord for new messages (inbound)

    Loads credentials from shared discord_config.json.
    Tracks cursor (last_message_id) to only return new messages.
    Skips bot messages. Persists cursor to disk.

    This unifies the old UserDiscordChannel (deliver-only) with
    DiscordChannelSource (receive-only) into one Channel object.
    """
    channel_id: str = ""
    guild_id: str = ""
    token: str = ""
    _cursor_dir: Path = field(default_factory=lambda: Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")))
    _last_message_id: Optional[str] = field(default=None, repr=False)
    _cursor_loaded: bool = field(default=False, repr=False)

    def __post_init__(self):
        if not self.token:
            from .discord_config import load_discord_config
            cfg = load_discord_config()
            self.token = self.token or cfg.get("token", "")
            self.guild_id = self.guild_id or cfg.get("guild_id", "")
            self.channel_id = self.channel_id or cfg.get("private_chat_channel_id", "")

    def channel_type(self) -> str:
        return "user.discord"

    # === OUTBOUND (deliver) ===

    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Post message to Discord channel via REST API."""
        import httpx

        message = payload.get("message", str(payload))
        if not self.token or not self.channel_id:
            return {"status": "error", "error": "missing token or channel_id"}

        try:
            import time as _time
            for attempt in range(3):
                resp = httpx.post(
                    f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                    headers=self._headers(),
                    json={"content": message},
                    timeout=10.0,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.json().get("retry_after", 2))
                    logger.warning("Discord rate limited, waiting %.1fs (attempt %d/3)", retry_after, attempt + 1)
                    _time.sleep(retry_after + 0.5)
                    continue
                resp.raise_for_status()
                return {"status": "delivered", "channel": self.channel_type(), "discord_message_id": resp.json().get("id")}
            return {"status": "error", "error": "Discord rate limited after 3 retries"}
        except Exception as e:
            logger.exception(f"Discord delivery failed: {e}")
            return {"status": "error", "error": str(e)}

    # === INBOUND (receive) ===

    def receive(self) -> Optional[Dict[str, Any]]:
        """Poll Discord for new human messages. Returns first new message or None.

        Tracks cursor (last_message_id) to avoid duplicates.
        Skips bot messages. Persists cursor to disk.
        Returns dict with content, metadata (user_id, username, message_id).
        """
        if not self.token or not self.channel_id:
            return None

        if not self._cursor_loaded:
            self._load_cursor()
            self._cursor_loaded = True

        messages = self._fetch_new_messages()
        for msg in messages:
            author = msg.get("author", {})
            msg_id = msg["id"]

            # Always advance cursor past any message
            if not self._last_message_id or msg_id > self._last_message_id:
                self._last_message_id = msg_id

            # Skip bot messages — cursor advanced but no event
            if author.get("bot"):
                continue

            content = msg.get("content", "")
            if not content:
                continue

            self._save_cursor()
            username = author.get("username", "unknown")
            return {
                "content": content,
                "channel": self.channel_type(),
                "metadata": {
                    "discord_message_id": msg_id,
                    "discord_channel_id": self.channel_id,
                    "discord_user_id": author.get("id", ""),
                    "discord_username": username,
                },
            }

        # Save cursor even if only bot messages advanced it
        if messages:
            self._save_cursor()
        return None

    # === INTERNALS ===

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
        }

    def _fetch_new_messages(self) -> List[Dict[str, Any]]:
        """Fetch messages newer than cursor from Discord REST API."""
        import httpx

        params: Dict[str, Any] = {"limit": 10}
        if self._last_message_id:
            params["after"] = self._last_message_id

        try:
            resp = httpx.get(
                f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                headers=self._headers(),
                params=params,
                timeout=10.0,
            )
            resp.raise_for_status()
            return list(reversed(resp.json()))  # Discord returns newest first
        except Exception as e:
            logger.error("Discord fetch failed for channel %s: %s", self.channel_id, e)
            return []

    @property
    def _cursor_file(self) -> Path:
        return self._cursor_dir / f"discord_cursor_{self.channel_id}.json"

    def _load_cursor(self) -> None:
        """Load persisted cursor from disk."""
        if self._cursor_file.exists():
            try:
                data = json.loads(self._cursor_file.read_text())
                self._last_message_id = data.get("last_message_id")
            except (json.JSONDecodeError, IOError):
                pass

    def _save_cursor(self) -> None:
        """Persist cursor to disk."""
        if self._last_message_id:
            self._cursor_file.parent.mkdir(parents=True, exist_ok=True)
            self._cursor_file.write_text(json.dumps({"last_message_id": self._last_message_id}))


# === Agent Channels (delivery TO agent) ===


class AgentChannel(Channel):
    """Conversation with an agent. Deliver = send to agent, receive = get from agent."""
    pass


@dataclass
class AgentInboxChannel(AgentChannel):
    """File-based inbox conversation. Each message is a JSON file."""
    inbox_dir: Path = field(default_factory=lambda: Path("/tmp/heaven_data/inbox"))

    def channel_type(self) -> str:
        return "agent.inbox"

    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Write JSON event to inbox directory."""
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        msg_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        msg_file = self.inbox_dir / f"{msg_id}.json"

        event = {
            "id": msg_id,
            "timestamp": datetime.now().isoformat(),
            "payload": payload,
            "status": "unread",
        }
        msg_file.write_text(json.dumps(event, indent=2))
        logger.info(f"Inbox event written: {msg_file.name}")
        return {"status": "delivered", "channel": self.channel_type(), "event_id": msg_id}

    def receive(self) -> Optional[Dict[str, Any]]:
        """Read oldest unread JSON file from inbox dir, mark as read."""
        if not self.inbox_dir.exists():
            return None

        unread = sorted([
            f for f in self.inbox_dir.glob("*.json")
            if f.is_file()
        ])

        if not unread:
            return None

        msg_file = unread[0]
        try:
            data = json.loads(msg_file.read_text())
            msg_file.unlink()  # consumed — remove from dir
            return data.get("payload", data)
        except Exception as e:
            logger.error(f"Failed to read inbox file {msg_file}: {e}")
            return None


@dataclass
class AgentTmuxChannel(AgentChannel):
    """Tmux session conversation. Send = send-keys, receive = capture-pane."""
    session: str = "claude"

    def channel_type(self) -> str:
        return "agent.tmux"

    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send prompt to tmux session."""
        import subprocess
        prompt = payload.get("prompt", payload.get("message", str(payload)))
        try:
            subprocess.run(["tmux", "send-keys", "-t", self.session, prompt], check=True)
            subprocess.run(["tmux", "send-keys", "-t", self.session, "Enter"], check=True)
            return {"status": "delivered", "channel": self.channel_type(), "session": self.session}
        except Exception as e:
            logger.exception(f"Tmux delivery failed: {e}")
            return {"status": "error", "error": str(e)}

    def receive(self) -> Optional[Dict[str, Any]]:
        """Capture current pane content. Pass-through — just returns what's there."""
        import subprocess
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", self.session, "-p", "-S", "-500"],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return {"content": result.stdout, "channel": self.channel_type(), "session": self.session}
        except Exception:
            pass
        return None


# === SSE Channel (delivery TO frontend via asyncio.Queue) ===


@dataclass
class SSEChannel(UserChannel):
    """Push events to frontend via asyncio.Queue for SSE streaming.

    The queue is shared with an SSE endpoint handler that reads from it
    and streams events to connected frontend clients.
    """
    queue: Any = None  # asyncio.Queue — passed in at construction

    def channel_type(self) -> str:
        return "user.sse"

    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Put event on the SSE queue. Non-blocking."""
        if self.queue is None:
            logger.warning("SSEChannel.deliver() called but self.queue is None!")
            return {"status": "error", "error": "no queue configured"}
        try:
            self.queue.put_nowait(payload)
            qsize = self.queue.qsize() if hasattr(self.queue, 'qsize') else '?'
            logger.warning("SSEChannel.deliver() SUCCESS — queue id=%s, size=%s, event_type: %s", id(self.queue), qsize, payload.get("event_type", "?"))
            return {"status": "delivered", "channel": self.channel_type()}
        except Exception as e:
            logger.warning("SSEChannel.deliver() FAILED: %s", e)
            return {"status": "error", "error": str(e)}


# === Multi-Channel (deliver to multiple targets) ===


@dataclass
class MultiChannel(Channel):
    """Deliver to multiple channels simultaneously."""
    channels: list = field(default_factory=list)

    def channel_type(self) -> str:
        return "multi"

    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        results = []
        for ch in self.channels:
            results.append(ch.deliver(payload))
        return {"status": "delivered", "channel": self.channel_type(), "results": results}

    def receive(self) -> Optional[Dict[str, Any]]:
        """Check all channels, return first available message."""
        for ch in self.channels:
            msg = ch.receive()
            if msg is not None:
                return msg
        return None


# =============================================================================
# CENTRAL CHANNEL — An agent's collection of conversation types
# =============================================================================


@dataclass
class CentralChannel:
    """An agent's collection of conversation types.

    Every agent has a CentralChannel. It IS the set of conversations
    that agent participates in. Each conversation is a Channel with
    its own transcript/history.

    Splitting = SEPARATE CONVERSATIONS with SEPARATE TRANSCRIPTS.
    Not separate transports — separate histories.

    Examples:
        Conductor:      CentralChannel({"main": discord_chat, "heartbeat": heartbeat_convo})
        Autobiographer: CentralChannel({"chat": memory_chat, "journal": journal_convo, "night": night_convo})
        GNOSYS:         CentralChannel({"main": tmux_session})
        OpenClaw:       CentralChannel({"main": discord_pipe})

    If main and heartbeat point to the SAME Channel instance, they share
    one conversation/transcript (the basic pattern — heartbeat and user
    chat happen in one history). Splitting them = two Channel instances
    = two separate histories.
    """
    conversations: Dict[str, Channel] = field(default_factory=dict)

    def get(self, name: str) -> Optional[Channel]:
        """Get a conversation by name."""
        return self.conversations.get(name)

    def main(self) -> Optional[Channel]:
        """Shortcut for the 'main' conversation."""
        return self.conversations.get("main")

    def list_conversations(self) -> list:
        """List conversation names."""
        return list(self.conversations.keys())

    def receive_all(self) -> Dict[str, Dict[str, Any]]:
        """Poll all conversations, return {name: message} for those with messages."""
        results = {}
        for name, channel in self.conversations.items():
            msg = channel.receive()
            if msg is not None:
                results[name] = msg
        return results
