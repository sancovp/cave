"""
Event Router - Routes events to output channels.

Two output channels:
1. InTerminalObject - Visual display in tmux
2. HookInjection - Context injection into Claude Code

Events from psyche/world/system can target either, both, or neither.
SSE emission to Railgun happens automatically for all events.
"""
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)


# ==================== HOOK INJECTION ====================

class InjectionType(Enum):
    """How to inject into Claude Code."""
    SYSTEM_REMINDER = "system_reminder"  # <system-reminder> tag
    USER_PROMPT = "user_prompt"          # Appears as user message
    TOOL_RESULT = "tool_result"          # Appears in tool output


@dataclass
class HookInjection:
    """Inject content into Claude Code's context.

    Gets written to a file that hooks pick up.
    """
    message: str
    injection_type: InjectionType = InjectionType.SYSTEM_REMINDER
    priority: int = 5  # 1-10, higher = more urgent

    # Optional metadata for the hook to use
    source: Optional[str] = None  # psyche, world, system
    event_name: Optional[str] = None


# ==================== IN-TERMINAL OBJECTS ====================

class TerminalObjectType(Enum):
    """Types of visual terminal objects."""
    NOTIFICATION = "notification"  # Brief flash
    OVERLAY = "overlay"            # Interactive popup
    PANEL = "panel"                # Persistent pane
    STATUS_UPDATE = "status"       # Status bar change


@dataclass
class InTerminalObject:
    """Visual object to display in terminal.

    Base class - specific rendering handled by TerminalUI.
    """
    object_type: TerminalObjectType
    content: str

    # Display config
    duration_seconds: float = 3.0
    position: str = "top_right"  # top_left, top_right, center, bottom_left, bottom_right
    width: int = 40
    height: int = 8

    # Behavior
    interactive: bool = False

    # Styling
    icon: Optional[str] = None
    border: bool = True


# ==================== EVENT OUTPUT ====================

@dataclass
class EventOutput:
    """Defines where an event routes to."""
    # Visual channel (optional)
    in_terminal: Optional[InTerminalObject] = None

    # Context injection channel (optional)
    hook_injection: Optional[HookInjection] = None

    # SSE always emits unless disabled
    sse_emit: bool = True

    # Raw data for SSE
    sse_data: dict = field(default_factory=dict)


# ==================== EVENT ====================

class EventSource(Enum):
    """Where events originate."""
    PSYCHE = "psyche"    # Internal state
    WORLD = "world"      # External events
    SYSTEM = "system"    # Infrastructure
    DETECTED = "detected"  # Parsed from terminal output


@dataclass
class Event:
    """A routable event with output configuration."""
    source: EventSource
    name: str
    payload: dict = field(default_factory=dict)
    output: Optional[EventOutput] = None

    # Metadata
    timestamp: float = 0.0

    def __post_init__(self):
        import time
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ==================== ROUTER ====================

class EventRouter:
    """Routes events to their output channels.

    Usage:
        router = EventRouter(terminal_ui, hook_dir="/tmp/paia_hooks")
        router.on_sse(callback)  # Register SSE handler

        router.route(Event(
            source=EventSource.PSYCHE,
            name="curiosity_spike",
            output=EventOutput(
                in_terminal=InTerminalObject(
                    object_type=TerminalObjectType.NOTIFICATION,
                    content="Curiosity rising...",
                    icon="🧠"
                ),
                hook_injection=HookInjection(
                    message="Is there something hidden here?",
                    injection_type=InjectionType.SYSTEM_REMINDER
                )
            )
        ))
    """

    def __init__(
        self,
        terminal_ui=None,  # TerminalUI instance
        hook_dir: str = "/tmp/paia_hooks"
    ):
        self.terminal_ui = terminal_ui
        self.hook_dir = Path(hook_dir)
        self.hook_dir.mkdir(parents=True, exist_ok=True)

        # SSE callbacks
        self._sse_callbacks: list[Callable[[Event], None]] = []

        # Event log
        self._event_log: list[Event] = []
        self._max_log_size = 100

    def on_sse(self, callback: Callable[[Event], None]):
        """Register callback for SSE emission."""
        self._sse_callbacks.append(callback)

    def route(self, event: Event):
        """Route an event to all configured outputs."""
        logger.info(f"Routing event: {event.source.value}/{event.name}")

        # Log the event
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

        if not event.output:
            # No output configured, just log
            return

        output = event.output

        # 1. In-terminal visual
        if output.in_terminal and self.terminal_ui:
            self._route_to_terminal(event, output.in_terminal)

        # 2. Hook injection
        if output.hook_injection:
            self._route_to_hook(event, output.hook_injection)

        # 3. SSE emission
        if output.sse_emit:
            self._route_to_sse(event)

    def _route_to_terminal(self, event: Event, obj: InTerminalObject):
        """Send to terminal UI."""
        try:
            if obj.object_type == TerminalObjectType.NOTIFICATION:
                from .terminal_ui import InTerminalNotification, NotificationType

                # Map event source to notification type
                type_map = {
                    EventSource.PSYCHE: NotificationType.PSYCHE,
                    EventSource.WORLD: NotificationType.EVENT,
                    EventSource.SYSTEM: NotificationType.INFO,
                    EventSource.DETECTED: NotificationType.INFO,
                }

                notification = InTerminalNotification(
                    message=obj.content,
                    notification_type=type_map.get(event.source, NotificationType.INFO),
                    duration_seconds=obj.duration_seconds,
                    width=obj.width,
                    height=obj.height,
                    interactive=obj.interactive
                )
                self.terminal_ui.notify(notification)

            elif obj.object_type == TerminalObjectType.OVERLAY:
                from .terminal_ui import InTerminalOverlay
                overlay = InTerminalOverlay(
                    title=event.name,
                    content=obj.content,
                    width=obj.width,
                    height=obj.height,
                    interactive=obj.interactive
                )
                self.terminal_ui.show_overlay(overlay)

        except Exception as e:
            logger.exception(f"Terminal routing failed: {e}")

    def _route_to_hook(self, event: Event, injection: HookInjection):
        """Write to hook injection file for Claude Code to pick up."""
        try:
            # Create injection file
            injection_file = self.hook_dir / "pending_injection.json"

            data = {
                "message": injection.message,
                "type": injection.injection_type.value,
                "priority": injection.priority,
                "source": injection.source or event.source.value,
                "event": injection.event_name or event.name,
                "timestamp": event.timestamp
            }

            # Append to list of pending injections
            pending = []
            if injection_file.exists():
                try:
                    pending = json.loads(injection_file.read_text())
                except:
                    pending = []

            pending.append(data)

            # Keep only recent injections
            pending = pending[-20:]

            injection_file.write_text(json.dumps(pending, indent=2))
            logger.info(f"Hook injection queued: {injection.message[:50]}...")

        except Exception as e:
            logger.exception(f"Hook routing failed: {e}")

    def _route_to_sse(self, event: Event):
        """Emit to all SSE callbacks."""
        for callback in self._sse_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"SSE callback failed: {e}")

    def get_recent_events(self, count: int = 10) -> list[Event]:
        """Get recent events from log."""
        return self._event_log[-count:]


# ==================== CONVENIENCE BUILDERS ====================

def psyche_event(
    name: str,
    message: str,
    inject: bool = True,
    visual: bool = True,
    **payload
) -> Event:
    """Build a psyche event with common defaults."""
    output = EventOutput()

    if visual:
        output.in_terminal = InTerminalObject(
            object_type=TerminalObjectType.NOTIFICATION,
            content=message,
            icon="🧠",
            duration_seconds=2.0
        )

    if inject:
        output.hook_injection = HookInjection(
            message=message,
            injection_type=InjectionType.SYSTEM_REMINDER,
            source="psyche",
            event_name=name
        )

    return Event(
        source=EventSource.PSYCHE,
        name=name,
        payload=payload,
        output=output
    )


def world_event(
    name: str,
    message: str,
    inject: bool = True,
    visual: bool = True,
    **payload
) -> Event:
    """Build a world event with common defaults."""
    output = EventOutput()

    if visual:
        output.in_terminal = InTerminalObject(
            object_type=TerminalObjectType.NOTIFICATION,
            content=message,
            icon="🌍",
            duration_seconds=3.0
        )

    if inject:
        output.hook_injection = HookInjection(
            message=message,
            injection_type=InjectionType.SYSTEM_REMINDER,
            source="world",
            event_name=name
        )

    return Event(
        source=EventSource.WORLD,
        name=name,
        payload=payload,
        output=output
    )


def system_event(
    name: str,
    message: str,
    inject: bool = True,
    visual: bool = True,
    **payload
) -> Event:
    """Build a system event with common defaults."""
    output = EventOutput()

    if visual:
        output.in_terminal = InTerminalObject(
            object_type=TerminalObjectType.NOTIFICATION,
            content=message,
            icon="⚙️",
            duration_seconds=2.0
        )

    if inject:
        output.hook_injection = HookInjection(
            message=message,
            injection_type=InjectionType.SYSTEM_REMINDER,
            source="system",
            event_name=name
        )

    return Event(
        source=EventSource.SYSTEM,
        name=name,
        payload=payload,
        output=output
    )
