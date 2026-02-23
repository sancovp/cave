"""Automation - Base class for scheduled agent automations.

Moved from selfbot/domain/automation.py into CAVE core where it belongs.
Schema-driven execution with Channel-based delivery.
"""

import json
import importlib
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, List
from string import Template

from .channel import Channel

logger = logging.getLogger(__name__)


@dataclass
class AutomationSchema:
    """Schema loaded from JSON defining what an automation does."""
    name: str
    description: str = ""
    schedule: Optional[str] = None  # Cron expression

    # Execution options (at least one required)
    prompt_template: Optional[str] = None  # Prompt to send to Claude
    code_pointer: Optional[str] = None     # "module.func" to import and call
    code_args: dict = field(default_factory=dict)

    # Templating
    template_vars: dict = field(default_factory=dict)

    # Metadata
    priority: int = 5
    tags: list = field(default_factory=list)

    @classmethod
    def from_json(cls, path: Path) -> 'AutomationSchema':
        """Load schema from JSON file."""
        data = json.loads(path.read_text())
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict) -> 'AutomationSchema':
        """Create schema from dict."""
        return cls(**data)

    def to_dict(self) -> dict:
        """Export to dict."""
        return {
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule,
            "prompt_template": self.prompt_template,
            "code_pointer": self.code_pointer,
            "code_args": self.code_args,
            "template_vars": self.template_vars,
            "priority": self.priority,
            "tags": self.tags,
        }


class Automation:
    """Base automation class — loads schema, delivers through Channel."""

    def __init__(
        self,
        schema: Optional[AutomationSchema] = None,
        schema_path: Optional[Path] = None,
        channels: Optional[List[Channel]] = None,
    ):
        if schema:
            self.schema = schema
        elif schema_path:
            self.schema = AutomationSchema.from_json(schema_path)
        else:
            raise ValueError("Must provide schema or schema_path")

        self.channels: List[Channel] = channels or []

    @property
    def name(self) -> str:
        return self.schema.name

    @property
    def schedule(self) -> Optional[str]:
        return self.schema.schedule

    def render_prompt(self, extra_vars: Optional[dict] = None) -> Optional[str]:
        """Render prompt template with variables."""
        if not self.schema.prompt_template:
            return None

        vars_dict = {**self.schema.template_vars}
        if extra_vars:
            vars_dict.update(extra_vars)

        return Template(self.schema.prompt_template).safe_substitute(vars_dict)

    def get_code_callable(self) -> Optional[Callable]:
        """Import and return the code pointer function."""
        if not self.schema.code_pointer:
            return None

        try:
            parts = self.schema.code_pointer.rsplit(".", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid code_pointer: {self.schema.code_pointer}")
            module_path, func_name = parts
            module = importlib.import_module(module_path)
            return getattr(module, func_name)
        except Exception as e:
            logger.exception(f"Failed to import {self.schema.code_pointer}: {e}")
            return None

    def execute_code(self, extra_args: Optional[dict] = None) -> Any:
        """Execute the code pointer with args."""
        func = self.get_code_callable()
        if not func:
            return None

        args = {**self.schema.code_args}
        if extra_args:
            args.update(extra_args)

        return func(**args)

    def fire(self, extra_vars: Optional[dict] = None) -> dict:
        """Fire the automation. Execute code + deliver through channels."""
        result = {
            "name": self.name,
            "code_result": None,
            "delivery_results": [],
        }

        # Execute code if present
        if self.schema.code_pointer:
            try:
                result["code_result"] = self.execute_code(extra_vars)
            except Exception as e:
                logger.exception(f"Code execution failed for {self.name}: {e}")
                result["code_error"] = str(e)

        # Build payload
        payload = {"automation": self.name, "priority": self.schema.priority}
        prompt = self.render_prompt(extra_vars)
        if prompt:
            payload["message"] = prompt
            payload["prompt"] = prompt

        # Deliver through all channels
        for channel in self.channels:
            try:
                delivery = channel.deliver(payload)
                result["delivery_results"].append(delivery)
            except Exception as e:
                logger.exception(f"Channel delivery failed for {self.name}: {e}")
                result["delivery_results"].append({"status": "error", "error": str(e)})

        return result

    def __repr__(self):
        ch_types = [c.channel_type() for c in self.channels]
        return f"Automation({self.name}, channels={ch_types})"


class AutomationRegistry:
    """Registry of loaded automations."""

    def __init__(self, automations_dir: Optional[Path] = None):
        self.automations: dict[str, Automation] = {}
        self._dir = automations_dir or Path("/tmp/heaven_data/automations")
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_all(self):
        """Load all automation JSONs from directory."""
        for json_file in self._dir.glob("*.json"):
            try:
                auto = Automation(schema_path=json_file)
                self.automations[auto.name] = auto
                logger.info(f"Loaded automation: {auto.name}")
            except Exception as e:
                logger.exception(f"Failed to load {json_file}: {e}")

    def get(self, name: str) -> Optional[Automation]:
        return self.automations.get(name)

    def register(self, automation: Automation):
        self.automations[automation.name] = automation

    def unregister(self, name: str) -> bool:
        if name in self.automations:
            del self.automations[name]
            return True
        return False

    def save_schema(self, schema: AutomationSchema) -> Path:
        path = self._dir / f"{schema.name}.json"
        path.write_text(json.dumps(schema.to_dict(), indent=2))
        return path

    def list_all(self) -> list[str]:
        return list(self.automations.keys())

    def get_due(self) -> list[Automation]:
        """Get all automations that are due to fire based on cron."""
        due = []
        for auto in self.automations.values():
            if auto.schedule:
                try:
                    from croniter import croniter
                    # TODO: track last_run per automation for proper cron checking
                    due.append(auto)
                except ImportError:
                    pass
        return due
