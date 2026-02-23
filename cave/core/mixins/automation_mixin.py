"""AutomationMixin - Manages Automation registry on CAVEAgent.

All scheduled execution flows through here. Heart uses this to fire due automations.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..automation import Automation, AutomationSchema, AutomationRegistry
from ..channel import Channel

logger = logging.getLogger(__name__)


class AutomationMixin:
    """Mixin that gives CAVEAgent automation management.

    Provides:
        - registry: AutomationRegistry for loading/registering automations
        - add_automation(): register with channels
        - fire_automation(): fire by name
        - fire_all_due(): fire everything that's due (called by Heart)
    """

    def _init_automations(self) -> None:
        """Initialize automation registry."""
        self.automation_registry = AutomationRegistry()
        self.automation_registry.load_all()
        logger.info(f"Loaded {len(self.automation_registry.list_all())} automations")

    def add_automation(
        self,
        name: str,
        description: str = "",
        schedule: Optional[str] = None,
        prompt_template: Optional[str] = None,
        code_pointer: Optional[str] = None,
        channels: Optional[List[Channel]] = None,
        priority: int = 5,
        tags: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Create and register an automation."""
        schema = AutomationSchema(
            name=name,
            description=description,
            schedule=schedule,
            prompt_template=prompt_template,
            code_pointer=code_pointer,
            priority=priority,
            tags=tags or [],
        )
        auto = Automation(schema=schema, channels=channels or [])
        self.automation_registry.register(auto)
        self.automation_registry.save_schema(schema)
        logger.info(f"Added automation: {name}")
        return {"status": "added", "automation": name, "schedule": schedule}

    def remove_automation(self, name: str) -> Dict[str, Any]:
        """Remove an automation by name."""
        if self.automation_registry.unregister(name):
            return {"status": "removed", "automation": name}
        return {"error": f"Automation '{name}' not found"}

    def fire_automation(self, name: str, extra_vars: Optional[dict] = None) -> Dict[str, Any]:
        """Fire a specific automation by name."""
        auto = self.automation_registry.get(name)
        if not auto:
            return {"error": f"Automation '{name}' not found"}
        return auto.fire(extra_vars)

    def fire_all_due(self) -> List[Dict[str, Any]]:
        """Fire all automations that are due. Called by Heart on rhythm."""
        results = []
        for auto in self.automation_registry.get_due():
            result = auto.fire()
            results.append(result)
        return results

    def list_automations(self) -> List[str]:
        """List all registered automation names."""
        return self.automation_registry.list_all()

    def get_automation_status(self) -> Dict[str, Any]:
        """Get status of all automations."""
        return {
            "count": len(self.automation_registry.automations),
            "automations": {
                name: {
                    "schedule": auto.schedule,
                    "channels": [c.channel_type() for c in auto.channels],
                }
                for name, auto in self.automation_registry.automations.items()
            },
        }
