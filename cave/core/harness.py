"""
PAIA Harness Core - The daemon that wraps code agents.

Boot sequence:
1. Start Python harness (this)
2. Load configs (psyche, world, system)
3. Start RNG modules
4. Create tmux session
5. Spawn code agent inside
6. Attach user

The harness is the CONTROL PLANE. Everything else is just processes being puppeted.
Single Python runtime controls all via tmux send_keys.
"""
import subprocess
import time
import re
import tempfile
import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

# Conditional imports - these may not exist yet in all environments
try:
    from events.psyche.module import PsycheModule
    from events.world.module import WorldModule
    from events.system.module import SystemModule
    HAS_MODULES = True
except ImportError:
    HAS_MODULES = False

try:
    from .output_watcher import OutputWatcher, DetectedEvent, EventType
    HAS_WATCHER = True
except ImportError:
    HAS_WATCHER = False

try:
    from .event_router import EventRouter, Event, EventSource, EventOutput
    from .event_router import InTerminalObject, TerminalObjectType, HookInjection, InjectionType
    from .terminal_ui import TerminalUI
    HAS_ROUTER = True
except ImportError:
    HAS_ROUTER = False


@dataclass
class HarnessConfig:
    # Agent command from env var - user must configure this themselves
    agent_command: str = field(default_factory=lambda: os.environ.get("AGENT_COMMAND", ""))
    # If no env var, harness won't spawn anything - user must set AGENT_COMMAND
    tmux_session: str = "paia-agent"
    tick_interval: float = 5.0  # seconds between RNG checks
    auto_prompt_idle_seconds: int = 30
    working_directory: str = field(default_factory=lambda: os.getcwd())
    # Response detection
    response_marker: str = "❯"  # Claude Code uses this for input prompt
    poll_interval: float = 0.5  # How often to check for response
    max_wait_seconds: float = 300.0  # 5 minute timeout


class PAIAHarness:
    """The harness daemon - wraps code agents with psychoblood simulation.

    This is the CONTROL PLANE. Claude Code is just a process being puppeted.
    """

    def __init__(self, config: Optional[HarnessConfig] = None):
        self.config = config or HarnessConfig()
        if HAS_MODULES:
            self.psyche = PsycheModule()
            self.world = WorldModule()
            self.system = SystemModule()
        else:
            self.psyche = None
            self.world = None
            self.system = None
        self.running = False
        self.agent_pid: Optional[int] = None
        self._last_output_length = 0

        # Output watcher for event detection
        if HAS_WATCHER:
            self.watcher = OutputWatcher()
        else:
            self.watcher = None

        # Event router and terminal UI
        if HAS_ROUTER:
            self.terminal_ui = TerminalUI(self.config.tmux_session)
            self.router = EventRouter(self.terminal_ui)
        else:
            self.terminal_ui = None
            self.router = None

        # Event callbacks - Railgun/HTTP server registers here
        self._event_callbacks: list = []

    # ==================== TMUX CONTROL ====================

    def _run_tmux(self, *args) -> subprocess.CompletedProcess:
        """Run a tmux command."""
        cmd = ["tmux"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def session_exists(self) -> bool:
        """Check if our tmux session exists."""
        result = self._run_tmux("has-session", "-t", self.config.tmux_session)
        return result.returncode == 0

    def create_session(self) -> bool:
        """Create the tmux session for the agent."""
        if self.session_exists():
            return True

        result = self._run_tmux(
            "new-session",
            "-d",  # detached
            "-s", self.config.tmux_session,
            "-c", self.config.working_directory
        )
        return result.returncode == 0

    def kill_session(self) -> bool:
        """Kill the tmux session."""
        result = self._run_tmux("kill-session", "-t", self.config.tmux_session)
        return result.returncode == 0

    def spawn_agent(self) -> bool:
        """Spawn the code agent inside the tmux session.

        Requires AGENT_COMMAND env var to be set by user.
        """
        if not self.config.agent_command:
            raise RuntimeError(
                "AGENT_COMMAND env var not set. "
                "User must configure their own code agent command."
            )

        if not self.session_exists():
            if not self.create_session():
                return False

        # Send the agent command to the session
        result = self._run_tmux(
            "send-keys",
            "-t", self.config.tmux_session,
            self.config.agent_command,
            "Enter"
        )
        return result.returncode == 0

    def send_keys(self, sequence: list) -> bool:
        """Send key sequence with optional sleeps.

        Args:
            sequence: List of items, each is either:
                - str: key to send (Enter, Down, C-c, text, etc.)
                - float/int: sleep duration in seconds

        Examples:
            send_keys(["Down", 0.3, "Enter"])  # Down, wait, Enter
            send_keys(["C-c"])                  # Just Ctrl+C
            send_keys(["hello", "Enter"])       # Type and submit
            send_keys(["Down", 0.2, "Down", 0.2, "Enter"])  # Navigate menu
        """
        for item in sequence:
            if isinstance(item, (int, float)):
                time.sleep(item)
            else:
                result = self._run_tmux(
                    "send-keys",
                    "-t", self.config.tmux_session,
                    item
                )
                if result.returncode != 0:
                    return False
        return True

    def send_to_agent(self, text: str) -> bool:
        """Send text + Enter to the agent. Convenience wrapper.

        This is the core control mechanism - 3 lines instead of 6 hours.
        """
        return self.send_keys([text, "Enter"])

    def capture_pane(self, history_limit: int = 5000) -> str:
        """Capture current pane content."""
        result = self._run_tmux(
            "capture-pane",
            "-t", self.config.tmux_session,
            "-p",  # print to stdout
            "-S", f"-{history_limit}"  # include scrollback
        )
        return result.stdout if result.returncode == 0 else ""

    def send_and_wait(self, prompt: str, timeout: Optional[float] = None) -> str:
        """Send prompt to agent and wait for response.

        This is the main interface for Heaven integration.
        Detects when Claude Code is done by looking for input prompt marker.

        Returns the agent's response text.
        """
        timeout = timeout or self.config.max_wait_seconds

        # Capture current state before sending
        before = self.capture_pane()
        before_lines = len(before.splitlines())

        # Send the prompt
        if not self.send_to_agent(prompt):
            raise RuntimeError("Failed to send prompt to agent")

        # Wait for response with polling
        start_time = time.time()
        last_content = before
        stable_count = 0

        while time.time() - start_time < timeout:
            time.sleep(self.config.poll_interval)

            current = self.capture_pane()

            # Check if output has stabilized AND we see the input marker
            # The ◇ marker indicates Claude Code is waiting for input
            if current == last_content:
                stable_count += 1
                # Need stable output + input marker
                if stable_count >= 3 and self.config.response_marker in current:
                    break
            else:
                stable_count = 0
                last_content = current

        # Extract response: everything between second-to-last ❯ and last ❯
        after = self.capture_pane()
        lines = after.splitlines()

        # Find all lines that start with the response marker
        marker_indices = [i for i, line in enumerate(lines)
                         if line.strip().startswith(self.config.response_marker)]

        if len(marker_indices) < 2:
            # Not enough markers, return everything after last marker
            if marker_indices:
                return "\n".join(lines[marker_indices[-1]+1:])
            return ""

        # Response is between second-to-last and last marker
        start_idx = marker_indices[-2] + 1  # Line after the prompt
        end_idx = marker_indices[-1]         # Line with final ❯

        response_lines = lines[start_idx:end_idx]
        return "\n".join(response_lines).strip()

    # ==================== DAEMON LIFECYCLE ====================

    def start(self):
        """Boot sequence."""
        self.running = True
        self.create_session()
        self.spawn_agent()
        # Give agent time to start
        time.sleep(2)

    def tick(self) -> list[str]:
        """One tick of the simulation - check all RNG modules."""
        if not HAS_MODULES:
            return []
        now = time.time()
        injections = []
        if self.psyche:
            injections.extend(self.psyche.tick(now))
        if self.world:
            injections.extend(self.world.tick(now))
        if self.system:
            injections.extend(self.system.tick(now))
        return injections

    def inject(self, messages: list[str]):
        """Inject messages into agent context.

        For now, we write to a hook injection file that Claude Code's
        hooks will pick up. Also emits to SSE for frontend visibility.
        """
        if not messages:
            return

        # Write to injection file (hooks pick it up)
        injection_file = Path("/tmp/paia_injection.txt")
        injection_file.write_text("\n".join(messages))

        # Also emit as event for SSE streaming
        if HAS_WATCHER:
            for msg in messages:
                event = DetectedEvent(
                    event_type=EventType.INJECTION,
                    content=msg,
                    raw_match=msg,
                    metadata={"source": "harness"}
                )
                self._emit_event(event)

        # Option 2: Direct tmux send (more intrusive)
        # for msg in messages:
        #     self.send_to_agent(msg)

    def stop(self):
        """Shutdown harness."""
        self.running = False
        # Optionally kill the session
        # self.kill_session()

    # ==================== EVENT WATCHING ====================

    def on_event(self, callback):
        """Register callback for detected events. Used by HTTP server."""
        self._event_callbacks.append(callback)

    def _emit_event(self, event):
        """Emit event to all registered callbacks."""
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception:
                pass  # Don't let bad callbacks break the daemon

    def watch_output(self) -> list:
        """Check terminal output for events and route them."""
        if not self.watcher:
            return []

        content = self.capture_pane()
        detected = self.watcher.process_output(content)

        for det in detected:
            # Emit to legacy callbacks
            self._emit_event(det)

            # Route through new event system
            if self.router and HAS_ROUTER:
                event = Event(
                    source=EventSource.DETECTED,
                    name=det.event_type.value,
                    payload={"content": det.content, "metadata": det.metadata},
                    output=EventOutput(
                        in_terminal=InTerminalObject(
                            object_type=TerminalObjectType.NOTIFICATION,
                            content=det.content[:100],
                            duration_seconds=2.0
                        ),
                        hook_injection=None,  # Detected events don't re-inject
                        sse_emit=True
                    )
                )
                self.router.route(event)

        return detected

    def run_daemon(self):
        """Main daemon loop - runs ticks, watches output, processes injections."""
        self.start()
        try:
            while self.running:
                # 1. Watch terminal output for events
                self.watch_output()

                # 2. Run RNG/event tick
                injections = self.tick()
                if injections:
                    self.inject(injections)

                time.sleep(self.config.tick_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
