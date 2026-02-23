"""CAVE Configuration.

Pydantic configuration model for CAVEAgent runtime.
Persists to /tmp/heaven_data/cave_agent_config.json
"""
import json
from pathlib import Path
import os
from typing import Dict, Optional

from pydantic import BaseModel, Field

from .models import MainAgentConfig

CAVE_AGENT_CONFIG_PATH = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "cave_agent_config.json"
CAVE_CONFIG_ARCHIVES_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "cave_config_archives"


class CAVEConfig(BaseModel):
    """Configuration for CAVE runtime. Persists to disk."""

    # === Server ===
    host: str = "0.0.0.0"
    port: int = 8080

    # === Paths ===
    data_dir: Path = Field(default_factory=lambda: Path("/tmp/heaven_data"))
    hook_dir: Path = Field(default_factory=lambda: Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "cave_hooks")
    claude_home: Path = Field(default_factory=Path.home)  # Where .claude/ lives (e.g., /home/GOD)

    # === System Prompt Templating ===
    system_prompt_template_path: Optional[Path] = None  # Path to template file
    system_prompt_target_path: Optional[Path] = None  # Where to write rendered prompt
    template_vars: Dict[str, str] = Field(default_factory=dict)  # {{VAR}} substitutions

    # === Main Agent ===
    main_agent_config: MainAgentConfig = Field(default_factory=MainAgentConfig)

    # === Features ===
    enable_sse: bool = True
    enable_hook_routing: bool = True
    enable_message_routing: bool = True

    # === SDNA (optional) ===
    sdna_enabled: bool = True
    sdna_default_model: str = "claude-sonnet-4-20250514"

    # === PAIA Hierarchy ===
    # If parent_url is set, this CAVEAgent is a PAIA that reports to a parent
    # If None, this is the root CAVEAgent (the real one)
    parent_url: Optional[str] = None  # e.g., "http://localhost:8421"
    paia_id: Optional[str] = None  # Identity when reporting to parent
    heartbeat_interval: float = 5.0  # Seconds between heartbeats to parent

    # === Restart Behavior (A+B Pattern) ===
    # A) Default: Restore last running state from cave_agent_config.json
    # B) If restart_config is set, load that named archive instead
    restart_config: Optional[str] = None  # e.g., "dev_setup" loads cave_config_archives/dev_setup.json

    class Config:
        arbitrary_types_allowed = True

    def save(self) -> None:
        """Save config to disk."""
        CAVE_AGENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CAVE_AGENT_CONFIG_PATH.write_text(self.model_dump_json(indent=2))

    def archive(self, name: str) -> Path:
        """Save current config as a named archive."""
        CAVE_CONFIG_ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
        path = CAVE_CONFIG_ARCHIVES_DIR / f"{name}.json"
        path.write_text(self.model_dump_json(indent=2))
        return path

    @classmethod
    def load(cls) -> "CAVEConfig":
        """Load config from disk.

        A+B Pattern:
        - A) Default: Restore last running state from cave_agent_config.json
        - B) If restart_config is set, load that named archive instead
        """
        if CAVE_AGENT_CONFIG_PATH.exists():
            data = json.loads(CAVE_AGENT_CONFIG_PATH.read_text())
            config = cls.model_validate(data)

            # B) If restart_config is set, load that named archive
            if config.restart_config:
                archive_path = CAVE_CONFIG_ARCHIVES_DIR / f"{config.restart_config}.json"
                if archive_path.exists():
                    archive_data = json.loads(archive_path.read_text())
                    return cls.model_validate(archive_data)

            return config
        # Create default and save it
        config = cls()
        config.save()
        return config
