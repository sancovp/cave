"""MiniCLI — Discord channel with registered commands and notifications.

A MiniCLI is its own thing — not part of any agent's CentralChannel.
It listens on a Discord channel, matches commands, fires handlers,
and sends notifications. Builder pattern for easy creation.

Usage:
    sanctum_cli = (MiniCLI.builder("sanctum", discord_id=channel_id_from_config)
        .command("done", handle_ritual_done, "Complete a ritual")
        .command("status", handle_status, "Show today's status")
        .command("skip", handle_skip, "Skip a ritual")
        .build())

    # In Ears perception loop:
    sanctum_cli.poll()  # checks Discord, routes commands

    # Send notifications:
    sanctum_cli.notify("Ritual due: morning-journal")
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .channel import UserDiscordChannel

logger = logging.getLogger(__name__)


@dataclass
class CLICommand:
    """A registered command in the MiniCLI."""
    name: str
    handler: Callable[[str], Any]  # handler(argument) → result
    description: str = ""


class MiniCLI:
    """Discord channel with registered commands and notifications.

    Not an agent. Not a channel on an agent. Its own system-level thing.
    Ears polls it during perception. Commands get routed to handlers.
    Notifications get sent to the channel.
    """

    def __init__(self, name: str, channel: UserDiscordChannel):
        self.name = name
        self.channel = channel
        self.commands: Dict[str, CLICommand] = {}
        self._poll_count = 0

    def register_command(self, name: str, handler: Callable, description: str = "") -> None:
        self.commands[name] = CLICommand(name=name, handler=handler, description=description)

    def poll(self) -> List[Dict[str, Any]]:
        """Poll Discord channel for new messages, match and execute commands.

        Returns list of command results.
        """
        results = []
        # Poll all available messages (receive returns one at a time)
        while True:
            msg = self.channel.receive()
            if not msg:
                break

            content = msg.get("content", "").strip()
            if not content:
                continue

            result = self._try_command(content, msg)
            if result:
                results.append(result)
                # Auto-reply with command result
                reply = result.get("result") or result.get("error", "")
                if reply:
                    self.notify(str(reply))
            else:
                # Not a command — could be conversational, ignore or log
                logger.debug("MiniCLI %s: unrecognized input: %s", self.name, content[:50])

        self._poll_count += 1
        return results

    def _try_command(self, content: str, msg: Dict) -> Optional[Dict[str, Any]]:
        """Try to match content against registered commands."""
        parts = content.split(None, 1)
        cmd_name = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""

        if cmd_name in self.commands:
            cmd = self.commands[cmd_name]
            try:
                result = cmd.handler(argument)
                logger.info("MiniCLI %s: %s(%s) → %s", self.name, cmd_name, argument, result)
                return {
                    "command": cmd_name,
                    "argument": argument,
                    "result": result,
                    "metadata": msg.get("metadata", {}),
                }
            except Exception as e:
                logger.error("MiniCLI %s: %s(%s) failed: %s", self.name, cmd_name, argument, e)
                return {"command": cmd_name, "argument": argument, "error": str(e)}

        return None

    def notify(self, message: str) -> Dict[str, Any]:
        """Send a notification to the channel."""
        return self.channel.deliver({"message": message})

    def help_text(self) -> str:
        """Generate help text for all registered commands."""
        lines = [f"**{self.name} commands:**"]
        for cmd in self.commands.values():
            desc = f" — {cmd.description}" if cmd.description else ""
            lines.append(f"  `{cmd.name}`{desc}")
        return "\n".join(lines)

    # === BUILDER ===

    @classmethod
    def builder(cls, name: str, channel: Any = None, discord_id: str = None) -> "MiniCLIBuilder":
        """Start building a MiniCLI. Pass any Channel, or discord_id for convenience."""
        return MiniCLIBuilder(name, channel=channel, discord_id=discord_id)


class MiniCLIBuilder:
    """Fluent builder for MiniCLI instances. Transport-agnostic."""

    def __init__(self, name: str, channel: Any = None, discord_id: str = None):
        self._name = name
        self._channel = channel
        self._discord_id = discord_id
        self._commands: List[tuple] = []

    def command(self, name: str, handler: Callable, description: str = "") -> "MiniCLIBuilder":
        self._commands.append((name, handler, description))
        return self

    def on_channel(self, channel: Any) -> "MiniCLIBuilder":
        """Set the channel (any object with receive() and deliver())."""
        self._channel = channel
        return self

    def on_discord(self, channel_id: str) -> "MiniCLIBuilder":
        """Convenience: create a UserDiscordChannel."""
        self._discord_id = channel_id
        return self

    def build(self) -> MiniCLI:
        if self._channel:
            channel = self._channel
        elif self._discord_id:
            channel = UserDiscordChannel(channel_id=self._discord_id)
        else:
            raise ValueError("MiniCLI needs a channel — use on_channel() or on_discord()")

        cli = MiniCLI(name=self._name, channel=channel)
        for name, handler, desc in self._commands:
            cli.register_command(name, handler, desc)
        return cli
