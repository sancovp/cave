"""
Terminal UI - Abstraction over tmux visual capabilities.

Strategic architecture:
- InTerminalNotification: transient messages
- InTerminalOverlay: floating interactive windows
- InTerminalPanel: persistent side panes

All are triggered by events from output_watcher or harness tick.
"""
import subprocess
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class Position(Enum):
    """Where to show the UI element."""
    TOP_LEFT = "0%", "0%"
    TOP_CENTER = "50%", "0%"
    TOP_RIGHT = "90%", "0%"
    CENTER = "50%", "50%"
    BOTTOM_LEFT = "0%", "90%"
    BOTTOM_CENTER = "50%", "90%"
    BOTTOM_RIGHT = "90%", "90%"


class NotificationType(Enum):
    """Semantic types for notifications."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCK = "block"           # Block report
    CONTEXT = "context"       # Context warning
    PSYCHE = "psyche"         # Psychoblood state change
    EVENT = "event"           # Generic event


@dataclass
class InTerminalNotification:
    """A notification to display in the terminal.

    Can be rendered as:
    - Flash message (display-message)
    - Brief popup (display-popup with timeout)
    - Status bar update
    """
    message: str
    notification_type: NotificationType = NotificationType.INFO
    duration_seconds: float = 3.0
    position: Position = Position.TOP_RIGHT

    # Visual customization
    width: int = 40
    height: int = 5
    border: bool = True

    # Behavior
    interactive: bool = False
    on_dismiss: Optional[Callable] = None

    def render_content(self) -> str:
        """Render the notification content with borders."""
        if not self.border:
            return self.message

        # Create bordered box
        inner_width = self.width - 4
        lines = []

        # Top border
        lines.append(f"╭{'─' * (self.width - 2)}╮")

        # Icon based on type
        icons = {
            NotificationType.INFO: "ℹ️",
            NotificationType.WARNING: "⚠️",
            NotificationType.ERROR: "❌",
            NotificationType.BLOCK: "🛑",
            NotificationType.CONTEXT: "📊",
            NotificationType.PSYCHE: "🧠",
            NotificationType.EVENT: "⚡",
        }
        icon = icons.get(self.notification_type, "•")

        # Header
        header = f" {icon} {self.notification_type.value.upper()}"
        lines.append(f"│{header:<{self.width - 2}}│")
        lines.append(f"├{'─' * (self.width - 2)}┤")

        # Message (word wrap)
        words = self.message.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= inner_width:
                current_line += (" " if current_line else "") + word
            else:
                lines.append(f"│ {current_line:<{inner_width}} │")
                current_line = word
        if current_line:
            lines.append(f"│ {current_line:<{inner_width}} │")

        # Padding to fill height
        while len(lines) < self.height - 1:
            lines.append(f"│{' ' * (self.width - 2)}│")

        # Bottom border
        lines.append(f"╰{'─' * (self.width - 2)}╯")

        return "\n".join(lines)


@dataclass
class InTerminalOverlay:
    """An interactive overlay window.

    For menus, HUDs, command palettes, etc.
    """
    title: str
    content: str  # Or callable that returns content
    width: int = 50
    height: int = 15
    position: Position = Position.CENTER

    # Behavior
    interactive: bool = True
    command: Optional[str] = None  # Shell command to run inside
    close_on_exit: bool = True

    def get_command(self) -> str:
        """Get the command to run in the popup."""
        if self.command:
            return self.command
        # Default: echo content and wait
        return f"echo '{self.content}'; read -p 'Press enter to close'"


@dataclass
class InTerminalPanel:
    """A persistent side panel.

    For always-visible HUDs, logs, status displays.
    """
    name: str
    command: str  # Command to run in the panel (e.g., "watch -n1 cat /tmp/hud.txt")
    width: int = 30  # Columns
    position: str = "right"  # left or right

    pane_id: Optional[str] = None  # Set after creation


class TerminalUI:
    """Manager for all terminal UI elements.

    Usage:
        ui = TerminalUI(session="paia-agent")
        ui.notify(InTerminalNotification("Block detected!", NotificationType.BLOCK))
        ui.show_overlay(menu_overlay)
        ui.create_panel(hud_panel)
    """

    def __init__(self, session: str):
        self.session = session
        self._panels: dict[str, InTerminalPanel] = {}

    def _run_tmux(self, *args) -> subprocess.CompletedProcess:
        """Run a tmux command."""
        cmd = ["tmux"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    # ==================== NOTIFICATIONS ====================

    def notify(self, notification: InTerminalNotification):
        """Show a notification."""
        if notification.interactive:
            self._show_popup_notification(notification)
        else:
            self._show_flash_notification(notification)

    def _show_flash_notification(self, n: InTerminalNotification):
        """Brief display-message style notification."""
        icons = {
            NotificationType.INFO: "ℹ️",
            NotificationType.WARNING: "⚠️",
            NotificationType.ERROR: "❌",
            NotificationType.BLOCK: "🛑",
            NotificationType.CONTEXT: "📊",
            NotificationType.PSYCHE: "🧠",
            NotificationType.EVENT: "⚡",
        }
        icon = icons.get(n.notification_type, "•")

        self._run_tmux(
            "display-message",
            "-t", self.session,
            "-d", str(int(n.duration_seconds * 1000)),
            f"{icon} {n.message}"
        )

    def _show_popup_notification(self, n: InTerminalNotification):
        """Popup-style notification with content box."""
        x, y = n.position.value
        content = n.render_content()

        # Escape single quotes in content
        content_escaped = content.replace("'", "'\\''")

        cmd = f"echo '{content_escaped}'; sleep {n.duration_seconds}"

        self._run_tmux(
            "display-popup",
            "-t", self.session,
            "-x", x,
            "-y", y,
            "-w", str(n.width),
            "-h", str(n.height),
            "-E",
            cmd
        )

    # ==================== OVERLAYS ====================

    def show_overlay(self, overlay: InTerminalOverlay) -> bool:
        """Show an interactive overlay."""
        x, y = overlay.position.value

        flags = [
            "display-popup",
            "-t", self.session,
            "-x", x,
            "-y", y,
            "-w", str(overlay.width),
            "-h", str(overlay.height),
        ]

        if overlay.close_on_exit:
            flags.append("-E")

        flags.append(overlay.get_command())

        result = self._run_tmux(*flags)
        return result.returncode == 0

    # ==================== PANELS ====================

    def create_panel(self, panel: InTerminalPanel) -> bool:
        """Create a persistent side panel."""
        if panel.name in self._panels:
            return True  # Already exists

        flags = [
            "split-window",
            "-t", self.session,
            "-h" if panel.position == "right" else "-hb",
            "-l", str(panel.width),
            panel.command
        ]

        result = self._run_tmux(*flags)

        if result.returncode == 0:
            self._panels[panel.name] = panel
            return True
        return False

    def close_panel(self, name: str) -> bool:
        """Close a panel by name."""
        if name not in self._panels:
            return False

        panel = self._panels[name]
        if panel.pane_id:
            self._run_tmux("kill-pane", "-t", panel.pane_id)

        del self._panels[name]
        return True

    # ==================== CONVENIENCE ====================

    def notify_block(self, message: str):
        """Quick block notification."""
        self.notify(InTerminalNotification(
            message=message,
            notification_type=NotificationType.BLOCK,
            duration_seconds=5.0
        ))

    def notify_context(self, percentage: int):
        """Quick context warning."""
        self.notify(InTerminalNotification(
            message=f"Context window at {percentage}%",
            notification_type=NotificationType.CONTEXT,
            duration_seconds=3.0
        ))

    def notify_psyche(self, state: str):
        """Quick psyche state notification."""
        self.notify(InTerminalNotification(
            message=f"Psyche state: {state}",
            notification_type=NotificationType.PSYCHE,
            duration_seconds=2.0
        ))
