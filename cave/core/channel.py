"""Channel - Typed delivery targets for Automations.

UserChannel = delivery TO human (simple: post where configured)
AgentChannel = delivery TO agent (complex: inbox + wake + processing)

Same transports (Discord, etc.) but different semantics per receiver.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class Channel(ABC):
    """Base channel - typed delivery target."""

    @abstractmethod
    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Deliver payload through this channel. Returns result dict."""
        ...

    @abstractmethod
    def channel_type(self) -> str:
        """Return channel type identifier."""
        ...


# === User Channels (delivery TO human) ===


class UserChannel(Channel):
    """Delivery to the human. Simple — just put the message where configured."""
    pass


@dataclass
class UserDiscordChannel(UserChannel):
    """Post to user's configured private agent-messages channel.

    Loads credentials from shared discord_config.json.
    Override channel_id/guild_id/token to use different values.
    """
    channel_id: str = ""
    guild_id: str = ""
    token: str = ""

    def __post_init__(self):
        if not self.token:
            from .discord_config import load_discord_config
            cfg = load_discord_config()
            self.token = self.token or cfg.get("token", "")
            self.guild_id = self.guild_id or cfg.get("guild_id", "")
            self.channel_id = self.channel_id or cfg.get("private_chat_channel_id", "")

    def channel_type(self) -> str:
        return "user.discord"

    def deliver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Post message to Discord channel via REST API."""
        import httpx

        message = payload.get("message", str(payload))
        if not self.token or not self.channel_id:
            return {"status": "error", "error": "missing token or channel_id"}

        try:
            resp = httpx.post(
                f"https://discord.com/api/v10/channels/{self.channel_id}/messages",
                headers={
                    "Authorization": f"Bot {self.token}",
                    "Content-Type": "application/json",
                },
                json={"content": message},
                timeout=10.0,
            )
            resp.raise_for_status()
            return {"status": "delivered", "channel": self.channel_type(), "discord_message_id": resp.json().get("id")}
        except Exception as e:
            logger.exception(f"Discord delivery failed: {e}")
            return {"status": "error", "error": str(e)}


# === Agent Channels (delivery TO agent) ===


class AgentChannel(Channel):
    """Delivery to an agent. Complex — inbox + wake + processing."""
    pass


@dataclass
class AgentInboxChannel(AgentChannel):
    """Write to agent's file-based inbox queue."""
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


@dataclass
class AgentTmuxChannel(AgentChannel):
    """Inject prompt into agent's tmux session."""
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
