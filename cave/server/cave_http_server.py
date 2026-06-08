"""CAVEHTTPServer - Facade over CAVEAgent.

CAVE_REFACTOR Stage 6: Every route = ONE method call on self.cave.
No business logic in routes. No global variable. Agent passed IN.

Usage:
    wd = WakingDreamer()  # or any CAVEAgent subclass
    server = CAVEHTTPServer(cave=wd, port=8080)
    uvicorn.run(server.app)
"""

import logging
import threading
from typing import Any, Dict

from fastapi import FastAPI
from starlette.responses import StreamingResponse

from ..core.cave_agent import CAVEAgent
from ..core.state_reader import ClaudeStateReader
from ..core.organ_daemon import run as run_organ_daemon
from ..core.automation import WebhookAutomation

logger = logging.getLogger(__name__)


class CAVEHTTPServer:
    """HTTP facade over a CAVEAgent instance.

    Takes port + CAVEAgent impl. That's it.
    Every route calls ONE method on self.cave.
    No logic in routes. No global state.
    """

    def __init__(self, cave: CAVEAgent, port: int = 8080, host: str = "0.0.0.0"):
        self.cave = cave
        self.port = port
        self.host = host
        self._organ_thread = None

        self.app = FastAPI(
            title="CAVE Harness",
            description="Code Agent Virtualization Environment",
            version="0.1.0",
        )

        self._register_lifecycle()
        self._register_routes()
        self._register_webhook_routes()

    def _register_lifecycle(self):
        @self.app.on_event("startup")
        async def startup():
            self._organ_thread = threading.Thread(
                target=run_organ_daemon, daemon=True, name="organ_daemon"
            )
            self._organ_thread.start()

        @self.app.on_event("shutdown")
        async def shutdown():
            pass

    def _register_routes(self):
        cave = self.cave  # closure capture

        # === Health ===
        @self.app.get("/health")
        def health():
            return {"status": "ok", "version": "0.1.0"}

        # === Bash Exec ===
        @self.app.post("/exec")
        async def bash_exec(data: Dict[str, Any]):
            """Execute a bash command and return output.

            Available on every CAVEHTTPServer — the universal escape hatch.
            """
            import subprocess
            command = data.get("command", "")
            timeout = data.get("timeout", 60)
            if not command:
                return {"error": "No command provided"}
            try:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=timeout,
                )
                return {
                    "success": result.returncode == 0,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": f"Command timed out after {timeout}s"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # === Self Inject ===
        @self.app.post("/self/inject")
        async def self_inject(data: Dict[str, Any]):
            import time
            message = data.get("message", "")
            press_enter = data.get("press_enter", True)
            if cave.main_agent is None:
                return {"error": "Main agent not attached"}
            cave.main_agent.send_keys(message)
            if press_enter:
                time.sleep(0.5)
                cave.main_agent.send_keys("Enter")
                time.sleep(0.5)
                cave.main_agent.send_keys("Enter")
            return {"status": "delivered", "session": cave.config.main_agent_config.tmux_session}

        # === Config Archives ===
        @self.app.get("/configs")
        def list_configs():
            return cave.list_config_archives()

        @self.app.get("/configs/active")
        def get_active_config():
            return cave.get_active_config()

        @self.app.post("/configs/archive")
        def archive_config(data: Dict[str, Any]):
            return cave.archive_config(data.get("name", ""))

        @self.app.post("/configs/inject")
        def inject_config(data: Dict[str, Any]):
            return cave.inject_config(data.get("name", ""))

        @self.app.delete("/configs/{name}")
        def delete_config(name: str):
            return cave.delete_config_archive(name)

        @self.app.post("/configs/export")
        def export_config(data: Dict[str, Any]):
            return cave.export_config_archive(data.get("name", ""), data.get("dest_path", ""))

        @self.app.post("/configs/import")
        def import_config(data: Dict[str, Any]):
            return cave.import_config_archive(data.get("source_path", ""), data.get("name", ""))

        # === Loops ===
        @self.app.get("/loops/state")
        def get_loop_state():
            return cave.get_loop_state()

        @self.app.post("/loops/start")
        def start_loop(data: Dict[str, Any]):
            return cave.start_loop(data.get("loop", "autopoiesis"), data.get("config"))

        @self.app.post("/loops/stop")
        def stop_loop():
            return cave.stop_loop()

        @self.app.post("/loops/trigger")
        def trigger_transition(data: Dict[str, Any]):
            return cave.trigger_transition(data.get("event", "continue"), data.get("data"))

        @self.app.post("/loops/pause")
        def pause_loop():
            return cave.pause_loop()

        @self.app.post("/loops/resume")
        def resume_loop():
            return cave.resume_loop()

        @self.app.get("/loops/available")
        def list_available_loops():
            return cave.list_available_loops()

        # === DNA ===
        @self.app.get("/dna/status")
        def get_dna_status():
            return cave.get_dna_status()

        @self.app.post("/dna/start")
        def start_auto_mode(data: Dict[str, Any]):
            from ..core.dna import create_dna
            dna = create_dna(
                name=data.get("name", "auto"),
                loop_names=data.get("loop_names", ["autopoiesis"]),
                exit_behavior=data.get("exit_behavior", "cycle"),
            )
            return cave.start_auto_mode(dna)

        @self.app.post("/dna/stop")
        def stop_auto_mode():
            return cave.stop_auto_mode()

        # === Modules ===
        @self.app.get("/modules")
        def list_modules():
            return cave.list_modules()

        @self.app.post("/modules/load")
        def load_module(data: Dict[str, Any]):
            return cave.load_module(data.get("name", ""), data.get("code"))

        @self.app.post("/modules/unload")
        def unload_module(data: Dict[str, Any]):
            return cave.unload_module(data.get("name", ""))

        @self.app.get("/modules/history")
        def get_module_history():
            return cave.get_module_history()

        # === Hooks ===
        @self.app.post("/hook/{hook_type}")
        def handle_hook_signal(hook_type: str, data: Dict[str, Any]):
            cave.run_omnisanc()
            return cave.handle_hook(hook_type, data)

        @self.app.post("/hooks/scan")
        def scan_hooks():
            return cave.scan_hooks()

        @self.app.get("/hooks")
        def list_hooks():
            return cave.list_hooks()

        @self.app.get("/hooks/status")
        def get_hooks_status():
            return cave.get_hook_status()

        @self.app.get("/hooks/active")
        def get_active_hooks():
            return {"active_hooks": cave.config.main_agent_config.active_hooks}

        @self.app.post("/hooks/active")
        def set_active_hooks(data: Dict[str, Any]):
            cave.config.main_agent_config.active_hooks = data
            cave.config.save()
            cave.scan_hooks()
            return {"active_hooks": cave.config.main_agent_config.active_hooks}

        # === Omnisanc ===
        @self.app.get("/omnisanc/state")
        def get_omnisanc_state():
            return cave.get_omnisanc_state()

        @self.app.get("/omnisanc/status")
        def get_omnisanc_status():
            return cave.get_omnisanc_status()

        @self.app.get("/omnisanc/zone")
        def get_omnisanc_zone():
            return {"zone": cave.get_omnisanc_zone()}

        @self.app.get("/omnisanc/enabled")
        def is_omnisanc_enabled():
            return {"enabled": cave.is_omnisanc_enabled()}

        @self.app.post("/omnisanc/enable")
        def enable_omnisanc():
            return cave.enable_omnisanc()

        @self.app.post("/omnisanc/disable")
        def disable_omnisanc():
            return cave.disable_omnisanc()

        @self.app.get("/metabrainhook/state")
        def get_metabrainhook_state():
            return {"enabled": cave.get_metabrainhook_state()}

        @self.app.post("/metabrainhook/state")
        def set_metabrainhook_state(data: Dict[str, Any]):
            return cave.set_metabrainhook_state(data.get("on", data.get("enabled", False)))

        @self.app.get("/metabrainhook/prompt")
        def get_metabrainhook_prompt():
            content = cave.get_metabrainhook_prompt()
            return {"content": content, "exists": content is not None}

        @self.app.post("/metabrainhook/prompt")
        def set_metabrainhook_prompt(data: Dict[str, Any]):
            return cave.set_metabrainhook_prompt(data.get("content", ""))

        # === PAIA Mode ===
        @self.app.get("/paia/mode")
        def get_paia_mode():
            return {"mode": cave.get_paia_mode(), "auto": cave.get_auto_mode()}

        @self.app.post("/paia/mode")
        def set_paia_mode(data: Dict[str, Any]):
            return cave.set_paia_mode(data.get("mode", "DAY"))

        @self.app.post("/paia/auto")
        def set_auto_mode(data: Dict[str, Any]):
            return cave.set_auto_mode(data.get("mode", "MANUAL"))

        # === Live Mirror ===
        @self.app.get("/output")
        def get_output(lines: int = 100):
            if not cave._ensure_attached():
                return {"error": "not attached"}
            output = cave.main_agent.capture_pane(history_limit=lines)
            return {"output": output, "context_pct": ClaudeStateReader.parse_context_pct(output)}

        @self.app.post("/input")
        def send_input(data: Dict[str, Any]):
            if not cave._ensure_attached():
                return {"error": "not attached"}
            text = data.get("text", "")
            if data.get("press_enter", True):
                cave.main_agent.send_keys(text, "Enter")
            else:
                cave.main_agent.send_keys(text)
            return {"sent": True, "text": text[:100]}

        @self.app.get("/state")
        def get_live_state():
            terminal_state = {}
            if cave._ensure_attached():
                output = cave.main_agent.capture_pane(history_limit=50)
                terminal_state = {
                    "attached": True,
                    "output_tail": output[-2000:] if len(output) > 2000 else output,
                    "context_pct": ClaudeStateReader.parse_context_pct(output),
                }
            else:
                terminal_state = {"attached": False}
            return {
                "terminal": terminal_state,
                "claude": cave.state_reader.get_complete_state(),
                "runtime": cave.inspect(),
            }

        @self.app.post("/command")
        def send_command(data: Dict[str, Any]):
            if not cave._ensure_attached():
                return {"error": "not attached"}
            command = data.get("command", "")
            if not command.startswith("/"):
                command = "/" + command
            cave.main_agent.send_keys(command, "Enter")
            return {"sent": command}

        @self.app.post("/attach")
        def attach_session(data: Dict[str, Any] = None):
            cave._attach_to_session()
            return {"attached": cave.main_agent is not None}

        @self.app.get("/inspect")
        def inspect():
            return cave.inspect()

        # === Inbox ===
        @self.app.get("/messages/inbox/{inbox_id}/count")
        def get_inbox_count(inbox_id: str):
            messages = cave.get_inbox(inbox_id)
            return {"inbox_id": inbox_id, "count": len(messages)}

        # === PAIA State ===
        @self.app.get("/paias")
        def list_paias():
            return {k: v.model_dump() for k, v in cave.paia_states.items()}

        @self.app.post("/paias/{paia_id}")
        def update_paia(paia_id: str, data: Dict[str, Any]):
            return cave.update_paia_state(paia_id, **data).model_dump()

        # === Remote Agents ===
        @self.app.post("/run_agent")
        async def run_agent(request: Dict[str, Any]):
            return await cave.spawn_remote(**request)

        @self.app.get("/remote_agents")
        def list_remote_agents():
            return {k: v.model_dump() for k, v in cave.remote_agents.items()}

        @self.app.get("/remote_agents/{agent_id}")
        def get_remote_agent(agent_id: str):
            handle = cave.get_remote_status(agent_id)
            return handle.model_dump() if handle else {"error": "not found"}

        # === Hot-Reload ===
        @self.app.post("/reload_agents")
        def reload_agents():
            if hasattr(cave, 'reload_agents'):
                return cave.reload_agents()
            return {"error": "CAVEAgent does not support reload — use WakingDreamer"}

        @self.app.post("/reload_automations")
        def reload_automations():
            if hasattr(cave, 'automation_registry'):
                return cave.automation_registry.hot_reload()
            return {"error": "no automation_registry"}

        # === CAVE Agent Registry (Stage 5) ===
        @self.app.get("/cave_agents")
        def list_cave_agents():
            return cave.list_cave_agents()

        @self.app.post("/cave_agents/{agent_name}/send")
        def send_to_cave_agent(agent_name: str, data: Dict[str, Any]):
            from ..core.agent import UserPromptMessage, IngressType
            msg = UserPromptMessage(
                content=data.get("message", ""),
                ingress=IngressType(data.get("ingress", "frontend")),
                priority=data.get("priority", 0),
            )
            result = cave.route_to_agent(agent_name, msg)
            return {"routed": result, "agent": agent_name}

        # === SSE Events ===
        @self.app.get("/events")
        async def events():
            return StreamingResponse(cave.event_generator(), media_type="text/event-stream")

    def _register_webhook_routes(self):
        """Register routes for WebhookAutomations dynamically."""
        if not hasattr(self.cave, '_automations'):
            return
        for auto in getattr(self.cave, '_automations', {}).values():
            if isinstance(auto, WebhookAutomation):
                path = f"/webhook/{auto.webhook_path}"

                @self.app.post(path)
                async def webhook_handler(data: Dict[str, Any], _auto=auto):
                    return _auto.fire(data)

                logger.info(f"Registered webhook route: {path}")

    def run(self):
        """Run the server."""
        import uvicorn
        uvicorn.run(self.app, host=self.host, port=self.port)
