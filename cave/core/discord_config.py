"""Shared Discord config loader.

One config file for all Discord operations (inbound + outbound).
Lives at ~/.claude/discord_config.json (same file the discord fork already uses).

Keys:
  - token: bot token
  - guild_id: server ID
  - alert_channel_id: channel for outbound alerts
  - private_chat_channel_id: private channel for inbound perception polling
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".claude" / "discord_config.json"


def load_discord_config(path: Path = DEFAULT_PATH) -> Dict[str, Any]:
    """Load Discord config from JSON file. Returns empty dict on failure."""
    if not path.exists():
        logger.warning("Discord config not found at %s", path)
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read discord config: %s", e)
        return {}
