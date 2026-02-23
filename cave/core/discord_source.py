"""Discord channel polling EventSource for World.

Polls a single private Discord channel via REST API for new messages.
Converts to WorldEvents that flow through Heart → World → route_message → Ears.

Uses shared config from discord_config.load_discord_config().
"""
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .discord_config import load_discord_config
from .world import EventSource, WorldEvent

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class DiscordChannelSource(EventSource):
    """Polls a private Discord channel via REST API. Produces WorldEvents for new messages.

    Reads config from ~/.claude/discord_config.json. Requires token and private_chat_channel_id.
    Bot must have read access to the channel. Tracks last_message_id to
    only return new messages. Skips bot messages.
    """

    def __init__(
        self,
        name: str = "discord_channel",
        config_path: Optional[Path] = None,
        enabled: bool = True,
    ):
        super().__init__(name, enabled)
        self._config: Dict[str, Any] = load_discord_config(config_path) if config_path else load_discord_config()
        self._last_message_id: Optional[str] = None
        self._seeded: bool = False
        self._total_messages: int = 0
        self._validate_config()

    def _validate_config(self) -> None:
        """Check required fields are present."""
        if not self._config:
            self.enabled = False
            return
        if not self._config.get("token"):
            logger.error("Discord config missing token — source disabled")
            self.enabled = False
            return
        if not self._config.get("private_chat_channel_id"):
            logger.error("Discord config missing private_chat_channel_id — source disabled")
            self.enabled = False

    @property
    def _token(self) -> str:
        return self._config.get("token", "")

    @property
    def _channel_id(self) -> str:
        return self._config.get("private_chat_channel_id", "")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
        }

    def _get_new_messages(self) -> List[Dict[str, Any]]:
        """Fetch messages newer than last_message_id for the configured channel."""
        params: Dict[str, Any] = {"limit": 10}
        if self._last_message_id:
            params["after"] = self._last_message_id

        try:
            resp = httpx.get(
                f"{DISCORD_API}/channels/{self._channel_id}/messages",
                headers=self._headers(),
                params=params,
                timeout=10.0,
            )
            resp.raise_for_status()
            messages = resp.json()
            # Discord returns newest first — reverse for chronological order
            return list(reversed(messages))
        except Exception as e:
            logger.error("Discord: failed to fetch messages for channel %s: %s", self._channel_id, e)
            return []

    def poll(self, current_time: float) -> List[WorldEvent]:
        """Poll the configured channel for new messages.

        Only tracks human messages. Bot messages are completely ignored —
        they never advance the cursor and never emit events. This prevents
        outbound pings from hiding inbound human messages.
        """
        if not self._token or not self._channel_id:
            return []

        messages = self._get_new_messages()
        events = []
        for msg in messages:
            author = msg.get("author", {})
            # Completely ignore bot messages — don't even advance cursor
            if author.get("bot"):
                continue

            msg_id = msg["id"]
            if self._last_message_id and msg_id <= self._last_message_id:
                continue

            content = msg.get("content", "")
            if not content:
                continue

            username = author.get("username", "unknown")
            events.append(WorldEvent(
                source="discord",
                content=f"[Discord #{self._channel_id}] {username}: {content}",
                priority=7,
                metadata={
                    "discord_message_id": msg_id,
                    "discord_channel_id": self._channel_id,
                    "discord_user_id": author.get("id", ""),
                    "discord_username": username,
                },
            ))
            self._last_message_id = msg_id
            self._total_messages += 1

        return events

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "has_token": bool(self._token),
            "channel_id": self._channel_id,
            "seeded": self._seeded,
            "total_messages": self._total_messages,
            "last_message_id": self._last_message_id,
        }

    @classmethod
    def from_config(cls, config_path: Optional[Path] = None) -> "DiscordChannelSource":
        """Factory: create from config file."""
        return cls(config_path=config_path)
