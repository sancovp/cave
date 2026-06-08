"""Automation - Trigger + Process execution as a Link in the chain ontology.

An Automation IS a Link. It wraps a process (code_pointer or prompt_template)
and attaches a trigger (cron schedule, event, etc.) with a DELIVERY TARGET.

Uses SDNA primitives:
    - sdna.cron: CronJob, CronScheduler, DeliveryTarget for scheduling + routing
    - sdna.selfbot: SelfBot for tmux-based prompt delivery

Architecture:
    SDNA (primitives)  →  cave.automation (Link integration)  →  CaveAgent (live runtime)

# =============================================================================
# CAVE_REFACTOR: AUTOMATION CHANGES (Stage 4)
# =============================================================================
#
# CURRENT: Automation(Link) with SDNA CronJob + DeliveryTarget integration.
#          Already has typed delivery routing (_deliver method).
#          Trigger type still implicit ("has schedule or not").
#
# TARGET (Stage 4): InputAutomation(Chain) from SDNA chain ontology.
#   InputLink → [dovetail fn] → ProcessLink → [dovetail fn] → OutputLink
#   Homoiconic — an automation can be a Link inside another Chain.
#
#   Four typed trigger subtypes (each adds ONE filter gate in execute()):
#     CronAutomation(InputAutomation)     — schedule match (existing is_due)
#     EventAutomation(InputAutomation)    — CAVE event bus subscription
#     WebhookAutomation(InputAutomation)  — HTTP request to /webhook/{path}
#     ManualAutomation(InputAutomation)   — explicit fire() call
#
#   class Automation:
#       \"\"\"Top-level API. One function. Full dialectic polymorphism.\"\"\"
#       @staticmethod
#       def create(config: dict) -> InputAutomation: ...
#       def __call__: ...  # dispatch
#
#   SOPHIA CONNECTION:
#     SOPHIA IS the intelligent Process for Automations.
#     Chain: sophia() → sophia() → sophia()...
#     Golden chains → saved as CronAutomation configs.
#     TOOT = SOPHIA's goldenized automations on the schedule.
#
# =============================================================================
"""

import json
import importlib
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, Dict, List
from string import Template

from sdna.chain_ontology import Link, LinkResult, LinkStatus
from sdna.cron import CronJob, CronScheduler, DeliveryTarget, DeliveryType, SessionTarget
from sdna.selfbot import SelfBot

logger = logging.getLogger(__name__)


# =============================================================================
# AUTOMATION SCHEMA — JSON-serializable definition
# =============================================================================

@dataclass
class AutomationSchema:
    """Schema loaded from JSON defining what an automation does.

    Now includes delivery target for routing results.
    """
    name: str
    description: str = ""
    schedule: Optional[str] = None  # Cron expression (trigger)

    # Execution options (at least one required)
    prompt_template: Optional[str] = None  # Prompt string (rendered with template_vars)
    code_pointer: Optional[str] = None     # "module.func" to import and call
    code_args: dict = field(default_factory=dict)

    # Templating
    template_vars: dict = field(default_factory=dict)

    # Delivery — WHERE the result goes
    delivery: Optional[dict] = None        # Serialized DeliveryTarget
    session_target: str = "main"           # "main" or "isolated"

    # Chain — full chain spec for ChainTool execution
    chain_spec: Optional[dict] = None  # ChainTool JSON spec (config_link, chain, eval_chain)

    # Deliverable gate — paths that must exist after execution for success
    expected_deliverables: list = field(default_factory=list)

    # Dependencies — automation names that must have last succeeded before this fires
    depends_on: list = field(default_factory=list)

    # One-shot — auto-unregister after firing once
    one_shot: bool = False

    # Parallel — list of automation names to fire simultaneously with this one
    parallel: list = field(default_factory=list)

    # Metadata
    priority: int = 5
    tags: list = field(default_factory=list)
    enabled: bool = True

    @classmethod
    def from_json(cls, path: Path) -> 'AutomationSchema':
        """Load schema from JSON file."""
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict) -> 'AutomationSchema':
        """Create schema from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

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
            "delivery": self.delivery,
            "session_target": self.session_target,
            "priority": self.priority,
            "chain_spec": self.chain_spec,
            "expected_deliverables": self.expected_deliverables,
            "depends_on": self.depends_on,
            "one_shot": self.one_shot,
            "parallel": self.parallel,
            "tags": self.tags,
            "enabled": self.enabled,
        }

    def to_cron_job(self) -> CronJob:
        """Convert this schema to an SDNA CronJob primitive."""
        delivery = None
        if self.delivery:
            delivery = DeliveryTarget.from_dict(self.delivery)

        return CronJob(
            name=self.name,
            schedule=self.schedule or "every:900",  # Default 15min if no schedule
            prompt=self.prompt_template,
            code_pointer=self.code_pointer,
            code_args=self.code_args,
            delivery=delivery,
            session_target=SessionTarget(self.session_target),
            enabled=self.enabled,
            tags=self.tags,
            priority=self.priority,
        )


# =============================================================================
# AUTOMATION — A Link with trigger + delivery
# =============================================================================

class InputAutomation(Link):
    """Base automation — a Link with process + delivery.

    Trigger = when to fire — defined by subtypes:
      CronAutomation  — cron schedule match
      EventAutomation — CAVE event bus subscription
      WebhookAutomation — HTTP request to /webhook/{path}
      ManualAutomation — explicit fire() call

    Process = what to run (code_pointer or prompt_template)
    Delivery = where the result goes (discord, agent, file, tmux, webhook)

    Homoiconic — an automation can be a Link inside another Chain.
    """

    def __init__(
        self,
        schema: Optional[AutomationSchema] = None,
        schema_path: Optional[Path] = None,
    ):
        if schema:
            self.schema = schema
        elif schema_path:
            self.schema = AutomationSchema.from_json(schema_path)
        else:
            raise ValueError("Must provide schema or schema_path")

        # Create the underlying SDNA CronJob
        self._cron_job = self.schema.to_cron_job()

        # SelfBot for tmux delivery
        self._selfbot = SelfBot()

        self.last_run: Optional[datetime] = None
        self.run_count: int = 0

    @property
    def name(self) -> str:
        return self.schema.name

    @property
    def schedule(self) -> Optional[str]:
        return self.schema.schedule

    @property
    def delivery(self) -> Optional[DeliveryTarget]:
        return self._cron_job.delivery

    @property
    def session_target(self) -> SessionTarget:
        return self._cron_job.session_target

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

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs) -> LinkResult:
        """Execute this automation's process. Satisfies the Link contract."""
        ctx = dict(context) if context else {}
        result_data = {"name": self.name}

        # Execute code_pointer if present
        if self.schema.code_pointer:
            func = self.get_code_callable()
            if func:
                try:
                    args = {**self.schema.code_args}
                    args.update(ctx.get("extra_args", {}))
                    code_result = func(**args)
                    result_data["code_result"] = code_result
                    ctx["code_result"] = code_result
                except Exception as e:
                    logger.exception(f"Code execution failed for {self.name}: {e}")
                    return LinkResult(
                        status=LinkStatus.ERROR,
                        context=ctx,
                        error=f"Code execution failed: {e}",
                    )

        # Render prompt if present
        prompt = self.render_prompt(ctx.get("extra_vars"))
        if prompt:
            result_data["prompt"] = prompt
            ctx["prompt"] = prompt

        self.last_run = datetime.now()
        self.run_count += 1
        self._cron_job.mark_run()
        ctx["automation_result"] = result_data

        # DELIVER the result
        await self._deliver(result_data, ctx)

        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)

    async def _deliver(self, result_data: dict, ctx: dict):
        """Route the result to the delivery target.

        This is where cron becomes CHAINING — the output goes somewhere.
        """
        delivery = self.delivery
        if not delivery:
            # Default to tmux (legacy behavior)
            prompt = result_data.get("prompt")
            if prompt:
                self._selfbot.prompt(prompt)
            return

        if delivery.type == DeliveryType.TMUX:
            prompt = result_data.get("prompt")
            if prompt:
                self._selfbot.prompt(prompt, session=delivery.session)

        elif delivery.type == DeliveryType.FILE:
            if delivery.path:
                Path(delivery.path).parent.mkdir(parents=True, exist_ok=True)
                Path(delivery.path).write_text(
                    json.dumps(result_data, indent=2, default=str)
                )
                logger.info(f"Delivered to file: {delivery.path}")

        elif delivery.type == DeliveryType.DISCORD:
            # Discord delivery goes through agent_registry → discord MCP
            ctx["_delivery_pending"] = {
                "type": "discord",
                "channel_id": delivery.channel_id,
                "content": result_data,
            }
            logger.info(f"Queued discord delivery to channel {delivery.channel_id}")

        elif delivery.type == DeliveryType.AGENT:
            # Agent delivery goes through agent_registry
            ctx["_delivery_pending"] = {
                "type": "agent",
                "agent_id": delivery.agent_id,
                "content": result_data,
            }
            logger.info(f"Queued agent delivery to {delivery.agent_id}")

        elif delivery.type == DeliveryType.WEBHOOK:
            if delivery.url:
                try:
                    import httpx
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            delivery.url,
                            json=result_data,
                            timeout=30,
                        )
                    logger.info(f"Delivered to webhook: {delivery.url}")
                except Exception as e:
                    logger.error(f"Webhook delivery failed: {e}")

        elif delivery.type == DeliveryType.CALLBACK:
            if delivery.callback:
                try:
                    delivery.callback(result_data)
                except Exception as e:
                    logger.error(f"Callback delivery failed: {e}")

    def fire(self, extra_vars: Optional[dict] = None) -> dict:
        """Synchronous fire for backwards compatibility with AutomationMixin."""
        import asyncio
        ctx = {"extra_vars": extra_vars} if extra_vars else {}

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(asyncio.run, self.execute(ctx)).result()
            else:
                result = asyncio.run(self.execute(ctx))
        except RuntimeError:
            result = asyncio.run(self.execute(ctx))

        return result.context.get("automation_result", {"name": self.name, "status": result.status.value})

    def is_due(self) -> bool:
        """Check if this automation is due to fire based on schedule."""
        return self._cron_job.is_due()

    def describe(self, depth: int = 0) -> str:
        indent = "  " * depth
        parts = [f'Automation "{self.name}"']
        if self.schema.schedule:
            parts.append(f"trigger={self.schema.schedule}")
        if self.schema.code_pointer:
            parts.append(f"process={self.schema.code_pointer}")
        if self.schema.prompt_template:
            preview = self.schema.prompt_template[:40]
            parts.append(f'prompt="{preview}..."')
        if self.delivery:
            parts.append(f"delivery={self.delivery.type.value}")
        return f"{indent}{' | '.join(parts)}"

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name}, schedule={self.schedule}, delivery={self.delivery})"


# =============================================================================
# TYPED TRIGGER SUBTYPES — each adds ONE filter gate
# =============================================================================


class CronAutomation(InputAutomation):
    """Fires on cron schedule match. is_due() checks the schedule."""
    pass  # is_due() already on InputAutomation via _cron_job


class EventAutomation(InputAutomation):
    """Fires on CAVE event bus event.

    event_name is matched against events emitted by CAVEAgent/agents.
    CAVEAgent wiring subscribes this to the event bus.
    """

    def __init__(self, event_name: str = "", **kwargs):
        super().__init__(**kwargs)
        self.event_name = event_name

    def matches_event(self, event: str) -> bool:
        """Check if this automation should fire for given event."""
        return self.event_name and event == self.event_name


class WebhookAutomation(InputAutomation):
    """Fires on HTTP request to /webhook/{path}.

    CAVEHTTPServer registers the route automatically.
    """

    def __init__(self, webhook_path: str = "", **kwargs):
        super().__init__(**kwargs)
        self.webhook_path = webhook_path


class ManualAutomation(InputAutomation):
    """Fires only when explicitly called via fire().

    No automatic trigger. Used for:
    - User-initiated actions
    - SOPHIA calling it as part of a chain
    - Another automation chaining to it
    """

    def is_due(self) -> bool:
        """Manual automations are never 'due' — only fired explicitly."""
        return False


# =============================================================================
# AUTOMATION FACTORY — top-level API, full dialectic polymorphism
# =============================================================================


class Automation:
    """Top-level Automation API. Factory + dispatch.

    Automation.create(config) → correct InputAutomation subtype.
    Determines trigger type from config and returns the right class.
    """

    @staticmethod
    def create(
        schema: Optional[AutomationSchema] = None,
        schema_path: Optional[Path] = None,
        config: Optional[dict] = None,
    ) -> InputAutomation:
        """Create the right automation subtype from config.

        Trigger type is inferred:
          - has 'schedule' → CronAutomation
          - has 'event_name' → EventAutomation
          - has 'webhook_path' → WebhookAutomation
          - none of the above → ManualAutomation
        """
        if config:
            schema = AutomationSchema.from_dict(config)
        if schema_path and not schema:
            schema = AutomationSchema.from_json(schema_path)
        if not schema:
            raise ValueError("Must provide schema, schema_path, or config")

        # Determine trigger type from schema
        if schema.schedule:
            return CronAutomation(schema=schema)
        else:
            return ManualAutomation(schema=schema)

    @staticmethod
    def create_event(event_name: str, schema: AutomationSchema) -> EventAutomation:
        """Create an event-triggered automation."""
        return EventAutomation(event_name=event_name, schema=schema)

    @staticmethod
    def create_webhook(webhook_path: str, schema: AutomationSchema) -> WebhookAutomation:
        """Create a webhook-triggered automation."""
        return WebhookAutomation(webhook_path=webhook_path, schema=schema)


# =============================================================================
# DELIVERY ROUTER — parse target strings and route results
# =============================================================================


class DeliveryRouter:
    """Parse delivery target strings and route results.

    Target formats:
        "agent:conductor"          → enqueue to agent's inbox
        "channel:discord:123456"   → post to Discord channel
        "file:/reports/{date}.md"  → write to file
        "webhook:https://..."      → POST to URL
        "tmux:session_name"        → send to tmux session
        "log"                      → write to automation log
        "self"                     → deliver to own agent

    Used by automations to route results without knowing the delivery mechanism.
    CAVEAgent passes itself so the router can access the agent registry.
    """

    def __init__(self, cave_agent=None):
        self._cave = cave_agent

    def deliver(self, target: str, result: Any) -> dict:
        """Parse target string and deliver result. Returns status dict."""
        if not target:
            return {"status": "no_target"}

        parts = target.split(":", 1)
        target_type = parts[0].lower()
        target_value = parts[1] if len(parts) > 1 else ""

        if target_type == "agent":
            return self._deliver_agent(target_value, result)
        elif target_type == "channel":
            return self._deliver_channel(target_value, result)
        elif target_type == "file":
            return self._deliver_file(target_value, result)
        elif target_type == "webhook":
            return self._deliver_webhook(target_value, result)
        elif target_type == "tmux":
            return self._deliver_tmux(target_value, result)
        elif target_type == "log":
            return self._deliver_log(result)
        elif target_type == "self":
            return self._deliver_self(result)
        else:
            logger.warning("Unknown delivery target type: %s", target_type)
            return {"status": "error", "reason": f"unknown target type: {target_type}"}

    def _deliver_agent(self, agent_name: str, result: Any) -> dict:
        """Deliver to agent's inbox via CAVEAgent registry."""
        if not self._cave:
            return {"status": "error", "reason": "no cave_agent reference"}
        from .agent import UserPromptMessage, IngressType
        content = result.get("prompt", json.dumps(result, default=str)) if isinstance(result, dict) else str(result)
        msg = UserPromptMessage(content=content, ingress=IngressType.SYSTEM, priority=3)
        success = self._cave.route_to_agent(agent_name, msg)
        return {"status": "delivered" if success else "error", "agent": agent_name}

    def _deliver_channel(self, channel_spec: str, result: Any) -> dict:
        """Deliver to a specific channel. Format: discord:channel_id or agent_name:channel_name."""
        parts = channel_spec.split(":", 1)
        if len(parts) == 2 and parts[0] == "discord":
            from .channel import UserDiscordChannel
            ch = UserDiscordChannel(channel_id=parts[1])
            content = result.get("prompt", str(result)) if isinstance(result, dict) else str(result)
            return ch.deliver({"message": content})
        elif len(parts) == 2 and self._cave:
            # agent_name:channel_name
            cc = self._cave.central_channels.get(parts[0])
            if cc:
                channel = cc.get(parts[1])
                if channel:
                    content = result.get("prompt", str(result)) if isinstance(result, dict) else str(result)
                    return channel.deliver({"message": content})
        return {"status": "error", "reason": f"cannot resolve channel: {channel_spec}"}

    def _deliver_file(self, path_template: str, result: Any) -> dict:
        """Write result to file. Supports {date}, {hour} templates."""
        from datetime import datetime
        now = datetime.now()
        path = path_template.format(
            date=now.strftime("%Y-%m-%d"),
            hour=now.strftime("%H"),
            timestamp=now.isoformat(),
        )
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, indent=2, default=str) if isinstance(result, dict) else str(result))
        logger.info("Delivered to file: %s", path)
        return {"status": "delivered", "path": path}

    def _deliver_webhook(self, url: str, result: Any) -> dict:
        """POST result to webhook URL."""
        try:
            import httpx
            resp = httpx.post(url, json=result if isinstance(result, dict) else {"result": str(result)}, timeout=30)
            logger.info("Delivered to webhook: %s (%d)", url, resp.status_code)
            return {"status": "delivered", "url": url, "status_code": resp.status_code}
        except Exception as e:
            logger.error("Webhook delivery failed: %s", e)
            return {"status": "error", "reason": str(e)}

    def _deliver_tmux(self, session: str, result: Any) -> dict:
        """Send prompt to tmux session."""
        from sdna.selfbot import SelfBot
        prompt = result.get("prompt", str(result)) if isinstance(result, dict) else str(result)
        SelfBot().prompt(prompt, session=session)
        return {"status": "delivered", "session": session}

    def _deliver_log(self, result: Any) -> dict:
        """Append to automation log."""
        # CONNECTS_TO: /tmp/heaven_data/automation_log.jsonl (write)
        log_path = Path("/tmp/heaven_data/automation_log.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        entry = {"timestamp": datetime.now().isoformat(), "result": result}
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return {"status": "logged"}

    def _deliver_self(self, result: Any) -> dict:
        """Deliver to the automation's own agent (if known)."""
        return self._deliver_log(result)  # Fallback to log for now


# =============================================================================
# AUTOMATION REGISTRY — loads, stores, queries live InputAutomation instances
# =============================================================================

class AutomationRegistry:
    """Registry of loaded automations.

    Every automation is a LIVE CLASS INSTANCE. You look at
    registry.automations and see EXACTLY what the system does.

    Uses Automation.create() factory to load JSONs into the correct subtype.
    """

    def __init__(self, automations_dir: Optional[Path] = None):
        self.automations: dict[str, InputAutomation] = {}
        # TRIGGERS: CronAutomation hot-reload via file write to /tmp/heaven_data/automations/
        self._dir = automations_dir or Path("/tmp/heaven_data/automations")
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_all(self):
        """Load all automation JSONs from directory via factory."""
        for json_file in self._dir.glob("*.json"):
            try:
                auto = Automation.create(schema_path=json_file)
                self.automations[auto.name] = auto
                logger.info(f"Loaded automation: {auto.name} ({auto.__class__.__name__})")
            except Exception as e:
                logger.exception(f"Failed to load {json_file}: {e}")

    def get(self, name: str) -> Optional[InputAutomation]:
        return self.automations.get(name)

    def hot_reload(self) -> Dict[str, Any]:
        """Diff current JSON files vs loaded automations. Add/remove/update.

        Called by Heart tick or manually. Returns what changed.
        """
        on_disk = {}
        for json_file in self._dir.glob("*.json"):
            try:
                schema = AutomationSchema.from_json(json_file)
                on_disk[schema.name] = (json_file, schema)
            except Exception as e:
                logger.error("Hot-reload: failed to parse %s: %s", json_file, e)

        added = []
        removed = []
        updated = []

        # Add new / update changed
        for name, (path, schema) in on_disk.items():
            if name not in self.automations:
                try:
                    auto = Automation.create(schema=schema)
                    self.automations[name] = auto
                    added.append(name)
                    logger.info("Hot-reload: added %s", name)
                except Exception as e:
                    logger.error("Hot-reload: failed to create %s: %s", name, e)
            else:
                # Check if schema changed (compare enabled, schedule, code_pointer)
                existing = self.automations[name]
                if (existing.schema.enabled != schema.enabled or
                    existing.schema.schedule != schema.schedule or
                    existing.schema.code_pointer != schema.code_pointer or
                    existing.schema.prompt_template != schema.prompt_template):
                    try:
                        auto = Automation.create(schema=schema)
                        self.automations[name] = auto
                        updated.append(name)
                        logger.info("Hot-reload: updated %s", name)
                    except Exception as e:
                        logger.error("Hot-reload: failed to update %s: %s", name, e)

        # Remove deleted
        for name in list(self.automations.keys()):
            if name not in on_disk:
                del self.automations[name]
                removed.append(name)
                logger.info("Hot-reload: removed %s", name)

        return {"added": added, "removed": removed, "updated": updated}

    def register(self, automation: InputAutomation):
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

    def get_due(self) -> list[InputAutomation]:
        """Get all CronAutomations that are due to fire."""
        return [auto for auto in self.automations.values() if auto.is_due()]

    def get_by_event(self, event_name: str) -> list[EventAutomation]:
        """Get all EventAutomations matching an event."""
        return [
            auto for auto in self.automations.values()
            if isinstance(auto, EventAutomation) and auto.matches_event(event_name)
        ]

    def get_webhook(self, path: str) -> Optional[WebhookAutomation]:
        """Get WebhookAutomation by path."""
        for auto in self.automations.values():
            if isinstance(auto, WebhookAutomation) and auto.webhook_path == path:
                return auto
        return None
