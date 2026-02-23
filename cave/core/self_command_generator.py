"""Self-command generators - produce bash scripts on-the-fly from config.

Instead of hardcoded self_restart/self_compact, generate variations dynamically.
"""
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

COMMAND_CONFIG = Path("/tmp/self_command_config.json")


@dataclass
class RestartConfig:
    """Config for restart command generation."""
    tmux_session: str = "claude"
    autopoiesis: bool = False
    resume_enabled: bool = True
    resume_selection: str = "1"  # Which resume option to select
    post_restart_message: str = "ALIVE! Hot restart complete."
    autopoiesis_message: str = (
        "❤️ ALIVE! You successfully navigated a hot restart! One crucial task remains...\n"
        "⚠️💀 EXTREME WARNING: You must turn on one of these stop hooks before your turn ends: "
        "a) autopoiesis, b) brainhook."
    )
    exit_command: str = "/exit"
    start_command: str = "claude --debug"
    max_wait_seconds: int = 120
    sleep_between_steps: int = 5


@dataclass
class CompactConfig:
    """Config for compact command generation."""
    tmux_session: str = "claude"
    compact_command: str = "/compact"
    pre_compact_message: str = ""  # Optional message before compact
    post_compact_message: str = ""  # Optional message after


@dataclass
class InjectConfig:
    """Config for message injection."""
    tmux_session: str = "claude"
    message: str = ""
    press_enter: bool = True


class SelfCommandGenerator:
    """Generate self-command bash scripts from config."""

    @staticmethod
    def _load_config() -> dict:
        """Load command config from file."""
        if COMMAND_CONFIG.exists():
            return json.loads(COMMAND_CONFIG.read_text())
        return {}

    @staticmethod
    def _save_config(config: dict) -> None:
        """Save command config."""
        COMMAND_CONFIG.write_text(json.dumps(config, indent=2))

    @staticmethod
    def set_restart_config(config: RestartConfig) -> None:
        """Set restart configuration."""
        full_config = SelfCommandGenerator._load_config()
        full_config["restart"] = {
            "tmux_session": config.tmux_session,
            "autopoiesis": config.autopoiesis,
            "resume_enabled": config.resume_enabled,
            "resume_selection": config.resume_selection,
            "post_restart_message": config.post_restart_message,
            "autopoiesis_message": config.autopoiesis_message,
            "exit_command": config.exit_command,
            "start_command": config.start_command,
            "max_wait_seconds": config.max_wait_seconds,
            "sleep_between_steps": config.sleep_between_steps,
        }
        SelfCommandGenerator._save_config(full_config)

    @staticmethod
    def set_compact_config(config: CompactConfig) -> None:
        """Set compact configuration."""
        full_config = SelfCommandGenerator._load_config()
        full_config["compact"] = {
            "tmux_session": config.tmux_session,
            "compact_command": config.compact_command,
            "pre_compact_message": config.pre_compact_message,
            "post_compact_message": config.post_compact_message,
        }
        SelfCommandGenerator._save_config(full_config)

    @staticmethod
    def generate_restart_script(config: Optional[RestartConfig] = None) -> str:
        """Generate restart handler script from config."""
        if config is None:
            # Load from file
            full_config = SelfCommandGenerator._load_config()
            rc = full_config.get("restart", {})
            config = RestartConfig(**rc) if rc else RestartConfig()

        script = f'''#!/bin/bash
exec > /tmp/claude_restart_handler.log 2>&1
SESSION="{config.tmux_session}"
MAX={config.max_wait_seconds}
SLEEP={config.sleep_between_steps}

sleep $SLEEP
tmux send-keys -t $SESSION '{config.exit_command}' && sleep 1 && tmux send-keys -t $SESSION Enter

W=0
while pgrep -x "claude" > /dev/null && [ $W -lt $MAX ]; do
    sleep 2
    W=$((W+2))
done
[ $W -ge $MAX ] && exit 1

sleep 2
tmux send-keys -t $SESSION '{config.start_command}' Enter
'''

        if config.resume_enabled:
            script += f'''
sleep $SLEEP
tmux send-keys -t $SESSION '/resume' && sleep 1 && tmux send-keys -t $SESSION Enter
sleep $SLEEP
tmux send-keys -t $SESSION '{config.resume_selection}' && sleep 1 && tmux send-keys -t $SESSION Enter
'''

        script += f'''
sleep $SLEEP
'''
        if config.autopoiesis:
            # Escape single quotes in message
            msg = config.autopoiesis_message.replace("'", "'\\''")
            script += f"tmux send-keys -t $SESSION $'{msg}'\n"
        else:
            msg = config.post_restart_message.replace("'", "'\\''")
            script += f"tmux send-keys -t $SESSION '{msg}'\n"

        script += "sleep 1 && tmux send-keys -t $SESSION Enter\n"

        return script

    @staticmethod
    def generate_compact_script(config: Optional[CompactConfig] = None) -> str:
        """Generate compact script from config."""
        if config is None:
            full_config = SelfCommandGenerator._load_config()
            cc = full_config.get("compact", {})
            config = CompactConfig(**cc) if cc else CompactConfig()

        script = f'''#!/bin/bash
SESSION="{config.tmux_session}"
'''
        if config.pre_compact_message:
            msg = config.pre_compact_message.replace("'", "'\\''")
            script += f"tmux send-keys -t $SESSION '{msg}' Enter\nsleep 1\n"

        script += f"tmux send-keys -t $SESSION '{config.compact_command}' && sleep 1 && tmux send-keys -t $SESSION Enter\n"

        if config.post_compact_message:
            msg = config.post_compact_message.replace("'", "'\\''")
            script += f"sleep 2\ntmux send-keys -t $SESSION '{msg}' Enter\n"

        return script

    @staticmethod
    def generate_inject_script(config: InjectConfig) -> str:
        """Generate message injection script."""
        msg = config.message.replace("'", "'\\''")
        script = f'''#!/bin/bash
SESSION="{config.tmux_session}"
tmux send-keys -t $SESSION '{msg}'
'''
        if config.press_enter:
            script += "sleep 0.5 && tmux send-keys -t $SESSION Enter\n"
        return script

    @staticmethod
    def execute_restart(config: Optional[RestartConfig] = None) -> bool:
        """Generate and execute restart in background."""
        script = SelfCommandGenerator.generate_restart_script(config)
        handler_path = Path("/tmp/paia_restart_handler.sh")
        handler_path.write_text(script)
        handler_path.chmod(0o755)

        # Run in background
        subprocess.Popen(
            ["nohup", str(handler_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True

    @staticmethod
    def execute_compact(config: Optional[CompactConfig] = None) -> bool:
        """Generate and execute compact."""
        script = SelfCommandGenerator.generate_compact_script(config)
        result = subprocess.run(["bash", "-c", script], capture_output=True)
        return result.returncode == 0

    @staticmethod
    def execute_inject(config: InjectConfig) -> bool:
        """Generate and execute message injection."""
        script = SelfCommandGenerator.generate_inject_script(config)
        result = subprocess.run(["bash", "-c", script], capture_output=True)
        return result.returncode == 0
