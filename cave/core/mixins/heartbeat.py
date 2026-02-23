"""HeartbeatMixin - Scheduled prompts for CAVEAgent.

Integrates SDNA's Heartbeat system into CAVE.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import from SDNA
try:
    from sdna import Heartbeat, HeartbeatScheduler, heartbeat as create_heartbeat
    SDNA_AVAILABLE = True
except ImportError:
    SDNA_AVAILABLE = False
    logger.warning("SDNA not available - heartbeat features disabled")


class HeartbeatMixin:
    """Mixin that adds heartbeat scheduling to CAVEAgent.
    
    Heartbeats are scheduled prompts that run on intervals.
    They use SDNA's Ariadne system to build context-rich prompts.
    
    Usage:
        # In CAVEAgent or via API
        cave_agent.add_heartbeat(
            name="daily_sync",
            session="cave",
            ariadne=ariadne(inject_file("/notes.md")),
            prompt="Review and summarize",
            every=3600
        )
        
        cave_agent.start_heartbeats()  # Start scheduler
        cave_agent.stop_heartbeats()   # Stop scheduler
    """
    
    def _init_heartbeat_manager(self) -> None:
        """Initialize heartbeat scheduler."""
        if not SDNA_AVAILABLE:
            self._heartbeat_scheduler = None
            return
            
        self._heartbeat_scheduler = HeartbeatScheduler()
    
    def add_heartbeat(
        self,
        name: str,
        session: str,
        ariadne: 'AriadneChain',
        every: Optional[int] = None,
        cron: Optional[str] = None,
        prompt: Optional[str] = None,
        on_deliver: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Add a heartbeat to the agent.

        Args:
            name: Unique identifier
            session: Target tmux session (ignored if on_deliver set)
            ariadne: AriadneChain to build prompt context
            every: Interval in seconds
            cron: Cron expression
            prompt: Optional prompt to inject
            on_deliver: Custom delivery callback(ariadne, prompt, heartbeat).
                        If set, bypasses tmux delivery — use for RemoteAgent routing.

        Returns:
            Status dict
        """
        if not SDNA_AVAILABLE:
            return {"error": "SDNA not available"}

        if self._heartbeat_scheduler is None:
            self._init_heartbeat_manager()

        hb = create_heartbeat(
            name=name,
            session=session,
            ariadne=ariadne,
            every=every,
            cron=cron,
            prompt=prompt,
            on_deliver=on_deliver
        )
        
        self._heartbeat_scheduler.add(hb)
        
        logger.info(f"Added heartbeat: {name} (every={every}, cron={cron})")
        
        return {
            "status": "added",
            "heartbeat": name,
            "session": session,
            "every": every,
            "cron": cron
        }
    
    def remove_heartbeat(self, name: str) -> Dict[str, Any]:
        """Remove a heartbeat by name."""
        if not self._heartbeat_scheduler:
            return {"error": "No heartbeat scheduler"}
        
        if self._heartbeat_scheduler.remove(name):
            return {"status": "removed", "heartbeat": name}
        return {"error": f"Heartbeat '{name}' not found"}
    
    def enable_heartbeat(self, name: str) -> Dict[str, Any]:
        """Enable a heartbeat."""
        if not self._heartbeat_scheduler:
            return {"error": "No heartbeat scheduler"}
        
        if self._heartbeat_scheduler.enable(name):
            return {"status": "enabled", "heartbeat": name}
        return {"error": f"Heartbeat '{name}' not found"}
    
    def disable_heartbeat(self, name: str) -> Dict[str, Any]:
        """Disable a heartbeat without removing it."""
        if not self._heartbeat_scheduler:
            return {"error": "No heartbeat scheduler"}
        
        if self._heartbeat_scheduler.disable(name):
            return {"status": "disabled", "heartbeat": name}
        return {"error": f"Heartbeat '{name}' not found"}
    
    def start_heartbeats(self, check_interval: float = 1.0) -> Dict[str, Any]:
        """Start the heartbeat scheduler in background."""
        if not self._heartbeat_scheduler:
            self._init_heartbeat_manager()
            
        if not self._heartbeat_scheduler:
            return {"error": "SDNA not available"}
        
        self._heartbeat_scheduler.start(check_interval)
        return {"status": "started", "check_interval": check_interval}
    
    def stop_heartbeats(self) -> Dict[str, Any]:
        """Stop the heartbeat scheduler."""
        if not self._heartbeat_scheduler:
            return {"error": "No heartbeat scheduler"}
        
        self._heartbeat_scheduler.stop()
        return {"status": "stopped"}
    
    def get_heartbeat_status(self) -> Dict[str, Any]:
        """Get status of all heartbeats."""
        if not self._heartbeat_scheduler:
            return {"error": "No heartbeat scheduler", "heartbeats": {}}
        
        return self._heartbeat_scheduler.status()
    
    def list_heartbeats(self) -> List[str]:
        """List all heartbeat names."""
        if not self._heartbeat_scheduler:
            return []
        
        return list(self._heartbeat_scheduler.heartbeats.keys())
