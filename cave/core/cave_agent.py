"""CAVEAgent - The God Object (State Only).

Unified CAVE runtime state. HTTP routes are in server/http_server.py.
"""
import subprocess
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

from .config import CAVEConfig
from .models import PAIAState, AgentRegistration, RemoteAgentHandle
from .agent import ClaudeCodeAgent, ClaudeCodeAgentConfig
from .state_reader import ClaudeStateReader
from .dna import AutoModeDNA
from .mixins import (
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    LoopManagerMixin,
    RemoteAgentMixin,
    SSEMixin,
    OmnisancMixin,
    AnatomyMixin,
    AutomationMixin,
    TUIMixin,
)
from .config_snapshots import MainAgentConfigManager
from .world import World, RNGEventSource
from .discord_source import DiscordChannelSource
from .sanctum_source import SanctumRitualSource


class CAVEAgent(
    PAIAStateMixin,
    AgentRegistryMixin,
    MessageRouterMixin,
    HookRouterMixin,
    LoopManagerMixin,
    RemoteAgentMixin,
    SSEMixin,
    OmnisancMixin,
    AnatomyMixin,
    AutomationMixin,
    TUIMixin,
):
    """Unified CAVE runtime state. Routes are in http_server.py."""

    def __init__(self, config: CAVEConfig | None = None):
        self.config = config or CAVEConfig()

        # === STATE ===
        self.paia_states: Dict[str, PAIAState] = {}
        self.agent_registry: Dict[str, AgentRegistration] = {}
        self.remote_agents: Dict[str, RemoteAgentHandle] = {}

        # === LIVE MIRROR ===
        self.main_agent: Optional[ClaudeCodeAgent] = None
        self.state_reader = ClaudeStateReader(
            project_dir=self.config.main_agent_config.working_dir
        )
        self._attach_to_session()

        # === ROUTING ===
        self._init_hook_router()
        self._init_loop_manager()
        self._init_sse()

        # === OMNISANC ===
        self._init_omnisanc()

        # === ANATOMY (Heart, Blood, Ears, Organs) ===
        self._init_anatomy()

        # === WORLD (environment — event sources tick into Ears) ===
        self.world = World()
        self._register_event_sources()

        # === PERCEPTION WIRING (Heart ticks World, routes events to Ears) ===
        self._wire_perception_loop()

        # === AUTOMATIONS ===
        self._init_automations()

        # === DNA (Auto Mode) ===
        self.dna: Optional[AutoModeDNA] = None

        # === System Prompt Templating ===
        if self.config.system_prompt_template_path and self.config.system_prompt_target_path:
            self._render_system_prompt()

        # === Data directories ===
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.hook_dir.mkdir(parents=True, exist_ok=True)

        # === Main Agent Config Archives ===
        self.config_manager = MainAgentConfigManager(
            data_dir=self.config.data_dir,
            claude_home=self.config.claude_home
        )

    def _register_event_sources(self) -> None:
        """Register default event sources with World."""
        # Probabilistic: RNG world events
        self.world.add_source(RNGEventSource.default_world_events())

        # External: Discord private channel polling (auto-disables if no config)
        self.world.add_source(DiscordChannelSource.from_config())

        # Deterministic: SANCTUM ritual reminders (auto-disables if no sanctum)
        self.world.add_source(SanctumRitualSource.from_config())

    @property
    def is_paia(self) -> bool:
        return self.config.parent_url is not None

    @property
    def paia_id(self) -> str:
        return self.config.paia_id or f"paia-{self.config.port}"

    def _render_system_prompt(self) -> None:
        if not self.config.system_prompt_template_path or not self.config.system_prompt_target_path:
            return
        template = self.config.system_prompt_template_path.read_text()
        rendered = template
        for key, value in self.config.template_vars.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        self.config.system_prompt_target_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.system_prompt_target_path.write_text(rendered)

    def _attach_to_session(self) -> bool:
        session = self.config.main_agent_config.tmux_session
        result = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True)
        if result.returncode == 0:
            agent_config = ClaudeCodeAgentConfig(
                agent_command=self.config.main_agent_config.command,
                tmux_session=session,
                working_directory=str(self.config.main_agent_config.working_dir),
            )
            self.main_agent = ClaudeCodeAgent(config=agent_config)
            self._emit_event("attached", {"session": session})
            return True
        else:
            self.main_agent = None
            self._emit_event("no_session", {"session": session})
            return False

    def _ensure_attached(self) -> bool:
        if self.main_agent and self.main_agent.session_exists():
            return True
        return self._attach_to_session()

    def inspect(self) -> Dict[str, Any]:
        return {
            "paias": {k: v.model_dump() for k, v in self.paia_states.items()},
            "agents": {k: v.model_dump() for k, v in self.agent_registry.items()},
            "remote_agents": {k: v.model_dump() for k, v in self.remote_agents.items()},
            "messages": self.message_router_summary(),
            "hooks": self.get_hook_status(),
            "sse": self.sse_status(),
            "config": {
                "host": self.config.host,
                "port": self.config.port,
                "data_dir": str(self.config.data_dir),
                "hook_dir": str(self.config.hook_dir),
                "sdna_enabled": self.config.sdna_enabled,
            }
        }

    def _build_heartbeat_state(self) -> Dict[str, Any]:
        context_pct = 0
        if self.main_agent and self.main_agent.session_exists():
            output = self.main_agent.capture_pane(history_limit=50)
            context_pct = ClaudeStateReader.parse_context_pct(output) or 0
        return {
            "paia_id": self.paia_id,
            "status": "working" if self.main_agent else "idle",
            "context_pct": context_pct,
            "inbox_count": 0,
            "current_task": None,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "endpoint": f"http://{self.config.host}:{self.config.port}",
            "metadata": {"session": self.config.main_agent_config.tmux_session, "attached": self.main_agent is not None}
        }

    async def send_heartbeat(self) -> bool:
        """Send single heartbeat to parent. Called by http_server startup loop."""
        if not self.config.parent_url:
            return False
        try:
            state = self._build_heartbeat_state()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self.config.parent_url}/paias/{self.paia_id}", json=state)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return False

    # === Main Agent Config Management ===

    def archive_config(self, name: str) -> Dict[str, Any]:
        """Archive current main agent config files."""
        result = self.config_manager.archive(name)
        if "error" not in result:
            self._emit_event("config_archived", {"name": name})
        return result

    def inject_config(self, name: str) -> Dict[str, Any]:
        """Inject (restore) a named config archive. Auto-backs up current first."""
        result = self.config_manager.inject(name)
        if "error" not in result:
            self._emit_event("config_injected", {"name": name, "backup": result.get("backup")})
        return result

    def list_config_archives(self) -> Dict[str, Any]:
        """List all config archives."""
        return self.config_manager.list_archives()

    def get_active_config(self) -> Dict[str, Any]:
        """Get info about currently active config."""
        return self.config_manager.get_active_info()

    def delete_config_archive(self, name: str) -> Dict[str, Any]:
        """Delete a config archive."""
        return self.config_manager.delete_archive(name)

    def export_config_archive(self, name: str, dest_path: str) -> Dict[str, Any]:
        """Export an archive to external path."""
        return self.config_manager.export_archive(name, dest_path)

    def import_config_archive(self, source_path: str, name: str) -> Dict[str, Any]:
        """Import an archive from external path."""
        return self.config_manager.import_archive(source_path, name)

    # === DNA (Auto Mode) ===

    def start_auto_mode(self, dna: AutoModeDNA) -> Dict[str, Any]:
        """Start auto mode with given DNA."""
        self.dna = dna
        return self.dna.start(self)

    def stop_auto_mode(self) -> Dict[str, Any]:
        """Stop auto mode."""
        if not self.dna:
            return {"error": "No DNA active"}
        result = self.dna.stop(self)
        self.dna = None
        return result

    def check_dna_transition(self) -> Dict[str, Any]:
        """Check if DNA should transition to next loop. Call on each hook pass."""
        if not self.dna or not self.dna.active:
            return {"status": "no_dna"}
        return self.dna.check_and_transition(self)

    def get_dna_status(self) -> Dict[str, Any]:
        """Get current DNA status."""
        if not self.dna:
            return {"status": "no_dna"}
        return self.dna.get_status()

    # === OMNISANC Workflow (hardcoded, hack to customize) ===

    def run_omnisanc(self) -> Dict[str, Any]:
        """Run OMNISANC zone detection and activate appropriate hooks.

        This is the hardcoded OMNISANC workflow. Fork and hack if you want
        different behavior. No abstraction - just Python.

        Returns:
            Status dict with zone and active hooks
        """
        if not self.is_omnisanc_enabled():
            return {"status": "disabled", "active_hooks": []}

        state = self.get_omnisanc_state()
        mode = self.get_paia_mode()  # DAY or NIGHT
        auto = self.get_auto_mode()  # AUTO or MANUAL
        is_auto = auto == "AUTO"
        is_night = mode == "NIGHT"

        # Start with empty active hooks
        active = []

        # Zone logic - mutually exclusive
        zone = "HOME"
        if not state.get("course_plotted"):
            zone = "HOME"
            # HOME hooks only fire in AUTO mode
            if is_auto:
                if is_night:
                    # NIGHT + AUTO = maintenance mode
                    active.append("metabrainhook")
                    active.append("omnisanc_home_night")
                else:
                    # DAY + AUTO = work mode (canopy tasks)
                    active.append("omnisanc_home_day")
            # MANUAL = user driving, no HOME hooks
        elif state.get("needs_review"):
            zone = "LANDING"
            active.append("omnisanc_landing")
        elif state.get("flight_selected") or state.get("session_active"):
            zone = "SESSION"
            active.append("omnisanc_session")
        elif state.get("fly_called"):
            zone = "LAUNCH"
            active.append("omnisanc_launch")
        else:
            zone = "STARPORT"
            active.append("omnisanc_starport")

        # Set active hooks for all hook types
        # inbox_notification always fires on posttooluse (perception layer)
        self.config.main_agent_config.active_hooks = {
            "stop": active,
            "pretooluse": ["omnisanc_router_pretooluse"],
            "posttooluse": ["omnisanc_router_posttooluse", "inbox_notification"],
        }

        logger.info(f"OMNISANC: zone={zone}, mode={mode}, auto={auto}, hooks={active}")

        return {
            "status": "active",
            "zone": zone,
            "mode": mode,
            "auto": auto,
            "active_hooks": active,
            "state": state,
        }

    def get_paia_mode(self) -> str:
        """Get current PAIA mode: DAY or NIGHT.

        TODO: Implement proper mode detection (user presence, time, etc.)
        For now, reads from file or defaults to DAY.
        """
        from pathlib import Path
        mode_file = Path("/tmp/heaven_data/paia_mode.txt")
        try:
            if mode_file.exists():
                return mode_file.read_text().strip().upper()
        except Exception:
            pass
        return "DAY"

    def get_auto_mode(self) -> str:
        """Get current auto mode: AUTO or MANUAL.

        AUTO = agent works autonomously (pulls tasks, does maintenance)
        MANUAL = user is driving, agent responds to user
        """
        from pathlib import Path
        auto_file = Path("/tmp/heaven_data/paia_auto.txt")
        try:
            if auto_file.exists():
                return auto_file.read_text().strip().upper()
        except Exception:
            pass
        return "MANUAL"  # Default to MANUAL (user driving)

    def set_auto_mode(self, mode: str) -> Dict[str, Any]:
        """Set auto mode: AUTO or MANUAL."""
        from pathlib import Path
        auto_file = Path("/tmp/heaven_data/paia_auto.txt")
        mode = mode.upper()
        if mode not in ("AUTO", "MANUAL"):
            return {"success": False, "error": f"Invalid mode: {mode}"}
        auto_file.parent.mkdir(parents=True, exist_ok=True)
        auto_file.write_text(mode)
        return {"success": True, "mode": mode}

    def set_paia_mode(self, mode: str) -> Dict[str, Any]:
        """Set PAIA mode: DAY or NIGHT."""
        from pathlib import Path
        mode_file = Path("/tmp/heaven_data/paia_mode.txt")
        mode = mode.upper()
        if mode not in ("DAY", "NIGHT"):
            return {"success": False, "error": f"Invalid mode: {mode}"}
        mode_file.parent.mkdir(parents=True, exist_ok=True)
        mode_file.write_text(mode)
        return {"success": True, "mode": mode}
