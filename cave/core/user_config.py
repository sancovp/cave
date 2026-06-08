"""User Configuration — the ONE source of truth for all user-level values.

Every external value (Discord tokens, channel IDs, model preferences, schedule times)
lives here as a validated Pydantic field. Nothing is a loose dict. Nothing is hardcoded.

Usage:
    from cave.core.user_config import load_user_config
    cfg = load_user_config()
    cfg.discord.token
    cfg.discord.channels["coglog"]
    cfg.model.name
    cfg.schedule.morning_time
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

HEAVEN_DATA = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))


class DiscordConfig(BaseModel):
    """Discord connection and channel configuration."""
    token: str = ""
    guild_id: str = ""
    alert_channel_id: str = ""
    sanctum_channel_id: str = ""
    private_chat_channel_id: str = ""
    isaac_user_id: str = ""
    channels: Dict[str, str] = Field(default_factory=dict)
    categories: Dict[str, str] = Field(default_factory=dict)


class ModelConfig(BaseModel):
    """LLM model configuration for all agents."""
    name: str = ""
    max_tokens: int = 8000
    api_url: str = ""
    use_uni_api: bool = False


class ScheduleConfig(BaseModel):
    """Daily schedule configuration."""
    morning_time: str = "09:00"
    night_time: str = "21:00"
    enabled: bool = True


class UserConfig(BaseModel):
    """The ONE user config. Every user-level value lives here.

    Loaded from runtime JSON files at startup.
    Validated by Pydantic. Fails loud on bad data.
    Passed to everything that needs user values.
    """
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)

    @classmethod
    def load(cls) -> "UserConfig":
        """Load from runtime JSON files. Validates all fields."""
        discord_data = _load_json(HEAVEN_DATA / "discord_config.json")
        model_data = _load_json(HEAVEN_DATA / "conductor_agent_config.json")
        schedule_data = _load_json(HEAVEN_DATA / "sanctuary" / "journal_config.json")

        discord = DiscordConfig(
            token=discord_data.get("token", ""),
            guild_id=discord_data.get("guild_id", ""),
            alert_channel_id=discord_data.get("alert_channel_id", ""),
            sanctum_channel_id=discord_data.get("sanctum_channel_id", ""),
            private_chat_channel_id=discord_data.get("private_chat_channel_id", ""),
            isaac_user_id=discord_data.get("isaac_user_id", ""),
            channels=discord_data.get("channels", {}),
            categories=discord_data.get("categories", {}),
        )

        model = ModelConfig(
            name=model_data.get("model", ""),
            max_tokens=model_data.get("max_tokens", 8000),
            api_url=model_data.get("extra_model_kwargs", {}).get("anthropic_api_url", ""),
            use_uni_api=model_data.get("use_uni_api", False),
        )

        schedule = ScheduleConfig(
            morning_time=schedule_data.get("morning_time", "09:00"),
            night_time=schedule_data.get("night_time", "21:00"),
            enabled=schedule_data.get("enabled", True),
        )

        cfg = cls(discord=discord, model=model, schedule=schedule)
        logger.info("UserConfig loaded: model=%s, discord=%s, schedule=%s/%s",
                     cfg.model.name, bool(cfg.discord.token),
                     cfg.schedule.morning_time, cfg.schedule.night_time)
        return cfg


_instance: Optional[UserConfig] = None


def load_user_config() -> UserConfig:
    """Load or return cached UserConfig singleton."""
    global _instance
    if _instance is None:
        _instance = UserConfig.load()
    return _instance


def reload_user_config() -> UserConfig:
    """Force reload from disk."""
    global _instance
    _instance = UserConfig.load()
    return _instance


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file. Returns empty dict if missing or invalid."""
    if not path.exists():
        logger.warning("Config file not found: %s", path)
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read config %s: %s", path, e, exc_info=True)
        return {}
