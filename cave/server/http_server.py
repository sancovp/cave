"""
CAVE HTTP Server - Entry point for CAVE daemon.

Run: python -m cave.server.http_server [--port 8080]
"""
import argparse
import threading
from typing import Any, Dict

from fastapi import FastAPI
from starlette.responses import StreamingResponse

from ..core.cave_agent import CAVEAgent
from ..core.config import CAVEConfig
from ..core.state_reader import ClaudeStateReader
from ..core.organ_daemon import run as run_organ_daemon

app = FastAPI(
    title="CAVE Harness",
    description="Code Agent Virtualization Environment - Live Mirror",
    version="0.1.0"
)

# Global CAVEAgent instance - initialized on startup
cave: CAVEAgent = None


_organ_thread: threading.Thread = None


@app.on_event("startup")
async def startup():
    global cave, _organ_thread
    cave = CAVEAgent(CAVEConfig.load())
    _organ_thread = threading.Thread(target=run_organ_daemon, daemon=True, name="organ_daemon")
    _organ_thread.start()


@app.on_event("shutdown")
async def shutdown():
    pass


# === Main Agent Config Archives ===
@app.get("/configs")
def list_configs():
    """List all config archives."""
    return cave.list_config_archives()


@app.get("/configs/active")
def get_active_config():
    """Get info about currently active config."""
    return cave.get_active_config()


@app.post("/configs/archive")
def archive_config(data: Dict[str, Any]):
    """Archive current main agent config files."""
    name = data.get("name", "")
    if not name:
        return {"error": "name required"}
    return cave.archive_config(name)


@app.post("/configs/inject")
def inject_config(data: Dict[str, Any]):
    """Inject (restore) a named config. Auto-backs up current first."""
    name = data.get("name", "")
    if not name:
        return {"error": "name required"}
    return cave.inject_config(name)


@app.delete("/configs/{name}")
def delete_config(name: str):
    """Delete a config archive."""
    return cave.delete_config_archive(name)


@app.post("/configs/export")
def export_config(data: Dict[str, Any]):
    """Export an archive to external path."""
    name = data.get("name", "")
    dest_path = data.get("dest_path", "")
    if not name or not dest_path:
        return {"error": "name and dest_path required"}
    return cave.export_config_archive(name, dest_path)


@app.post("/configs/import")
def import_config(data: Dict[str, Any]):
    """Import an archive from external path."""
    source_path = data.get("source_path", "")
    name = data.get("name", "")
    if not source_path or not name:
        return {"error": "source_path and name required"}
    return cave.import_config_archive(source_path, name)


# === Loop Manager Endpoints ===
@app.get("/loops/state")
def get_loop_state():
    """Get current loop state."""
    return cave.get_loop_state()


@app.post("/loops/start")
def start_loop(data: Dict[str, Any]):
    """Start a loop (autopoiesis, guru, ralph, etc.)."""
    loop_type = data.get("loop", "autopoiesis")
    config = data.get("config")
    return cave.start_loop(loop_type, config)


@app.post("/loops/stop")
def stop_loop():
    """Stop current loop."""
    return cave.stop_loop()


@app.post("/loops/trigger")
def trigger_transition(data: Dict[str, Any]):
    """Trigger a loop transition event."""
    event = data.get("event", "continue")
    return cave.trigger_transition(event, data.get("data"))


@app.post("/loops/pause")
def pause_loop():
    """Pause current loop (allows exit without meeting conditions)."""
    return cave.pause_loop()


@app.post("/loops/resume")
def resume_loop():
    """Resume paused loop."""
    return cave.resume_loop()


@app.get("/loops/available")
def list_available_loops():
    """List all available loop configurations."""
    return cave.list_available_loops()


# === DNA (Auto Mode) Endpoints ===
@app.get("/dna/status")
def get_dna_status():
    """Get current DNA/auto mode status."""
    return cave.get_dna_status()


@app.post("/dna/start")
def start_auto_mode(data: Dict[str, Any]):
    """Start auto mode with DNA.

    Pass loop_names and exit_behavior:
    {"loop_names": ["autopoiesis", "guru"], "exit_behavior": "cycle"}
    """
    from ..core.dna import create_dna

    loop_names = data.get("loop_names", ["autopoiesis"])
    exit_behavior = data.get("exit_behavior", "cycle")
    name = data.get("name", "auto")

    dna = create_dna(name=name, loop_names=loop_names, exit_behavior=exit_behavior)
    return cave.start_auto_mode(dna)


@app.post("/dna/stop")
def stop_auto_mode():
    """Stop auto mode."""
    return cave.stop_auto_mode()


# === Module Hot-Load Endpoints ===
@app.get("/modules")
def list_modules():
    """List available and loaded modules."""
    return cave.list_modules()


@app.post("/modules/load")
def load_module(data: Dict[str, Any]):
    """Hot-load a module. Optionally provide code to write first."""
    name = data.get("name", "")
    code = data.get("code")
    if not name:
        return {"error": "name required"}
    return cave.load_module(name, code)


@app.post("/modules/unload")
def unload_module(data: Dict[str, Any]):
    """Unload a module."""
    name = data.get("name", "")
    if not name:
        return {"error": "name required"}
    return cave.unload_module(name)


@app.get("/modules/history")
def get_module_history():
    """Get history of module load attempts."""
    return cave.get_module_history()


# === Hook Signal Endpoint ===
@app.post("/hook/{hook_type}")
def handle_hook_signal(hook_type: str, data: Dict[str, Any]):
    """
    Receives hook signals from paia_* hooks.

    Hook scripts call this, we process, return decision.
    Checks if hook is enabled in config, then runs registered handlers.
    """
    # Update OMNISANC zone detection + active hooks before processing
    cave.run_omnisanc()
    return cave.handle_hook(hook_type, data)


@app.post("/hooks/scan")
def scan_hooks():
    """Rescan cave_hooks directory and update registry."""
    return cave.scan_hooks()


@app.get("/hooks")
def list_hooks():
    """List all hooks in registry."""
    return cave.list_hooks()


@app.get("/hooks/status")
def get_hooks_status():
    """Get full hook system status (registry + enabled + history)."""
    return cave.get_hook_status()


@app.get("/hooks/active")
def get_active_hooks():
    """Get currently active hooks from main agent config."""
    return {"active_hooks": cave.config.main_agent_config.active_hooks}


@app.post("/hooks/active")
def set_active_hooks(data: Dict[str, Any]):
    """Set active hooks for main agent. Pass {"stop": ["brainhook"], ...}"""
    cave.config.main_agent_config.active_hooks = data
    cave.config.save()  # Persist to disk
    cave.scan_hooks()  # Rescan to ensure hooks exist
    return {"active_hooks": cave.config.main_agent_config.active_hooks}


# === Omnisanc ===
@app.get("/omnisanc/state")
def get_omnisanc_state():
    """Get raw omnisanc course state."""
    return cave.get_omnisanc_state()


@app.get("/omnisanc/status")
def get_omnisanc_status():
    """Get complete omnisanc + metabrainhook status."""
    return cave.get_omnisanc_status()


@app.get("/omnisanc/zone")
def get_omnisanc_zone():
    """Get current omnisanc zone (HOME/STARPORT/SESSION/etc)."""
    return {"zone": cave.get_omnisanc_zone()}


@app.get("/omnisanc/enabled")
def is_omnisanc_enabled():
    """Check if omnisanc logic is enabled."""
    return {"enabled": cave.is_omnisanc_enabled()}


@app.post("/omnisanc/enable")
def enable_omnisanc():
    """Enable omnisanc logic."""
    return cave.enable_omnisanc()


@app.post("/omnisanc/disable")
def disable_omnisanc():
    """Disable omnisanc logic."""
    return cave.disable_omnisanc()


@app.get("/metabrainhook/state")
def get_metabrainhook_state():
    """Get metabrainhook on/off state."""
    return {"enabled": cave.get_metabrainhook_state()}


@app.post("/metabrainhook/state")
def set_metabrainhook_state(data: Dict[str, Any]):
    """Set metabrainhook on/off state."""
    on = data.get("on", data.get("enabled", False))
    return cave.set_metabrainhook_state(on)


@app.get("/metabrainhook/prompt")
def get_metabrainhook_prompt():
    """Get metabrainhook prompt content."""
    content = cave.get_metabrainhook_prompt()
    return {"content": content, "exists": content is not None}


@app.post("/metabrainhook/prompt")
def set_metabrainhook_prompt(data: Dict[str, Any]):
    """Set metabrainhook prompt content."""
    content = data.get("content", "")
    return cave.set_metabrainhook_prompt(content)


# === PAIA Mode Control ===

@app.get("/paia/mode")
def get_paia_mode():
    """Get current PAIA mode (DAY/NIGHT) and auto mode (AUTO/MANUAL)."""
    return {
        "mode": cave.get_paia_mode(),
        "auto": cave.get_auto_mode(),
    }


@app.post("/paia/mode")
def set_paia_mode(data: Dict[str, Any]):
    """Set PAIA mode: DAY or NIGHT."""
    mode = data.get("mode", "DAY")
    return cave.set_paia_mode(mode)


@app.post("/paia/auto")
def set_auto_mode(data: Dict[str, Any]):
    """Set auto mode: AUTO or MANUAL."""
    mode = data.get("mode", "MANUAL")
    return cave.set_auto_mode(mode)


# === Health ===
@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


# === Live Mirror Endpoints ===
@app.get("/output")
def get_output(lines: int = 100):
    if not cave._ensure_attached():
        return {"error": "not attached", "session": cave.config.main_agent_session}
    output = cave.main_agent.capture_pane(history_limit=lines)
    context_pct = ClaudeStateReader.parse_context_pct(output)
    return {"output": output, "context_pct": context_pct, "session": cave.config.main_agent_session}


@app.post("/input")
def send_input(data: Dict[str, Any]):
    if not cave._ensure_attached():
        return {"error": "not attached", "session": cave.config.main_agent_session}
    text = data.get("text", "")
    press_enter = data.get("press_enter", True)
    if press_enter:
        cave.main_agent.send_keys(text, "Enter")
    else:
        cave.main_agent.send_keys(text)
    return {"sent": True, "text": text[:100]}


@app.get("/state")
def get_live_state():
    terminal_state = {}
    if cave._ensure_attached():
        output = cave.main_agent.capture_pane(lines=50)
        terminal_state = {
            "attached": True,
            "session": cave.config.main_agent_session,
            "output_tail": output[-2000:] if len(output) > 2000 else output,
            "context_pct": ClaudeStateReader.parse_context_pct(output),
        }
    else:
        terminal_state = {"attached": False, "session": cave.config.main_agent_session}

    claude_state = cave.state_reader.get_complete_state()
    return {
        "terminal": terminal_state,
        "claude": claude_state,
        "runtime": {
            "paias": {k: v.model_dump() for k, v in cave.paia_states.items()},
            "agents": {k: v.model_dump() for k, v in cave.agent_registry.items()},
            "remote_agents": {k: v.model_dump() for k, v in cave.remote_agents.items()},
        }
    }


@app.post("/command")
def send_command(data: Dict[str, Any]):
    if not cave._ensure_attached():
        return {"error": "not attached", "session": cave.config.main_agent_session}
    command = data.get("command", "")
    if not command.startswith("/"):
        command = "/" + command
    cave.main_agent.send_keys(command, "Enter")
    return {"sent": command}


@app.post("/attach")
def attach_session(data: Dict[str, Any] = None):
    data = data or {}
    if "session" in data:
        cave.config.main_agent_session = data["session"]
    success = cave._attach_to_session()
    return {"attached": success, "session": cave.config.main_agent_session}


@app.get("/inspect")
def inspect():
    return cave.inspect()


# === Inbox ===
@app.get("/messages/inbox/{inbox_id}/count")
def get_inbox_count(inbox_id: str):
    """Get message count for an inbox."""
    messages = cave.get_inbox(inbox_id)
    return {"inbox_id": inbox_id, "count": len(messages)}


# === PAIA State ===
@app.get("/paias")
def list_paias():
    return {k: v.model_dump() for k, v in cave.paia_states.items()}


@app.post("/paias/{paia_id}")
def update_paia(paia_id: str, data: Dict[str, Any]):
    state = cave.update_paia_state(paia_id, **data)
    return state.model_dump()


# === Remote Agents ===
@app.post("/run_agent")
async def run_agent(request: Dict[str, Any]):
    return await cave.spawn_remote(**request)


@app.get("/remote_agents")
def list_remote_agents():
    return {k: v.model_dump() for k, v in cave.remote_agents.items()}


@app.get("/remote_agents/{agent_id}")
def get_remote_agent(agent_id: str):
    handle = cave.get_remote_status(agent_id)
    return handle.model_dump() if handle else {"error": "not found"}


# === SSE Events ===
@app.get("/events")
async def events():
    return StreamingResponse(cave.event_generator(), media_type="text/event-stream")


# === Entry Point ===
def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="CAVE HTTP Server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
