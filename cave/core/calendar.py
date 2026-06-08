"""Calendar(Compiler) — compiles scheduling specs into live CronAutomations.

Calendar IS a Compiler: takes a JSON spec, produces a running CronAutomation(Link)
registered in AutomationRegistry. Management (list, cancel, view) goes through
the registry — Calendar compiles, registry manages.

Spec format:
{
    "name": "daily_ralph_carton",
    "schedule": "0 3 * * *",
    "description": "Run ralph on carton-mcp daily",
    "chain_spec": {
        "type": "config_link",
        "name": "ralph_carton",
        "goal": "Fix add_concept validation",
        "model": "minimax",
        "mcp_servers": {...}
    },
    "expected_deliverables": ["/tmp/ralph_results/result.json"],
    "delivery": {"type": "file", "path": "/tmp/results/{date}.json"},
    "code_pointer": "cave.core.ralph_scheduler.dispatch_ralph",
    "code_args": {"repo": "/home/GOD/gnosys-plugin-v2", "code_target": "add_concept"}
}

Usage:
    calendar = Calendar(registry)
    result = await calendar.execute({"spec": spec_dict})
    automation = calendar.get_compiled(result.context)  # CronAutomation(Link)

    # Management via registry
    calendar.list_scheduled()
    calendar.view(days=7)
    calendar.cancel("daily_ralph_carton")
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from sdna.chain_ontology import Link, Chain, Compiler, LinkResult, LinkStatus

from cave.core.automation import (
    Automation,
    AutomationRegistry,
    AutomationSchema,
    CronAutomation,
    InputAutomation,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Compilation Links — the steps Calendar runs to compile a spec
# =============================================================================


class ParseSpecLink(Link):
    """Validate and normalize a scheduling spec from context["spec"]."""

    name = "parse_spec"

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        ctx = dict(context or {})
        spec = ctx.get("spec")

        if not spec:
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="No 'spec' in context")

        if not isinstance(spec, dict):
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="'spec' must be a dict")

        if not spec.get("name"):
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="Spec must have 'name'")

        if not spec.get("schedule"):
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="Spec must have 'schedule' (cron expression)")

        if not spec.get("code_pointer") and not spec.get("prompt_template") and not spec.get("chain_spec"):
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="Spec must have at least one of: code_pointer, prompt_template, chain_spec")

        # Validate cron syntax
        try:
            from croniter import croniter
            croniter(spec["schedule"])
        except (ValueError, KeyError) as e:
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error=f"Invalid cron schedule '{spec.get('schedule')}': {e}")

        ctx["parsed_spec"] = spec
        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)


class BuildAutomationLink(Link):
    """Build a CronAutomation from the parsed spec."""

    name = "build_automation"

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        ctx = dict(context or {})
        spec = ctx.get("parsed_spec")

        if not spec:
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="No parsed_spec in context")

        schema = AutomationSchema.from_dict(spec)
        automation = Automation.create(schema=schema)

        ctx["compiled"] = automation
        ctx["schema"] = schema
        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)


class RegisterLink(Link):
    """Register the compiled automation in the AutomationRegistry."""

    name = "register"

    def __init__(self, registry: AutomationRegistry):
        self._registry = registry

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        ctx = dict(context or {})
        automation = ctx.get("compiled")
        schema = ctx.get("schema")

        if not automation:
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="No compiled automation in context")

        # Register live instance
        self._registry.register(automation)

        # Persist schema to disk for hot-reload
        if schema:
            self._registry.save_schema(schema)

        ctx["registered"] = True
        ctx["automation_name"] = automation.name
        logger.info("Calendar: registered automation '%s' (schedule=%s)",
                    automation.name, automation.schedule)
        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)


class CheckDeliverablesLink(Link):
    """Check if expected deliverables exist after an automation run."""

    name = "check_deliverables"

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        ctx = dict(context or {})
        deliverables = ctx.get("expected_deliverables", [])

        if not deliverables:
            ctx["deliverables_ok"] = True
            return LinkResult(status=LinkStatus.SUCCESS, context=ctx)

        missing = [p for p in deliverables if not Path(p).exists()]

        if missing:
            ctx["deliverables_ok"] = False
            ctx["missing_deliverables"] = missing
            return LinkResult(status=LinkStatus.BLOCKED, context=ctx,
                            error=f"Missing deliverables: {missing}")

        ctx["deliverables_ok"] = True
        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)


# =============================================================================
# Calendar(Compiler) — the main thing
# =============================================================================


class Calendar(Compiler):
    """Compiler that takes scheduling specs and produces live CronAutomations.

    Calendar.execute({"spec": {...}}) → CronAutomation registered in registry.
    Calendar.get_compiled(result.context) → the CronAutomation.

    Management methods delegate to AutomationRegistry.
    """

    def __init__(self, registry: Optional[AutomationRegistry] = None):
        self._registry = registry or AutomationRegistry()
        super().__init__(
            chain_name="calendar",
            links=[
                ParseSpecLink(),
                BuildAutomationLink(),
                RegisterLink(self._registry),
            ],
            output_key="compiled",
        )

    @property
    def registry(self) -> AutomationRegistry:
        return self._registry

    # --- Convenience: schedule from spec dict ---

    async def schedule(self, spec: dict) -> Dict[str, Any]:
        """Schedule an automation from a spec dict. Returns result with status."""
        result = await self.execute({"spec": spec})
        if result.status == LinkStatus.SUCCESS:
            return {
                "status": "scheduled",
                "name": result.context.get("automation_name"),
                "schedule": spec.get("schedule"),
            }
        return {"status": "error", "error": result.error}

    def schedule_sync(self, spec: dict) -> Dict[str, Any]:
        """Synchronous schedule."""
        import asyncio
        return asyncio.run(self.schedule(spec))

    # --- Management (delegates to registry) ---

    def cancel(self, name: str) -> bool:
        """Cancel a scheduled automation."""
        # Remove from registry
        removed = self._registry.unregister(name)
        # Remove persisted schema
        schema_path = self._registry._dir / f"{name}.json"
        if schema_path.exists():
            schema_path.unlink()
        if removed:
            logger.info("Calendar: cancelled '%s'", name)
        return removed

    def list_scheduled(self) -> List[Dict[str, Any]]:
        """List all scheduled automations."""
        result = []
        for name, auto in self._registry.automations.items():
            entry = {
                "name": name,
                "type": type(auto).__name__,
                "schedule": auto.schedule,
                "enabled": auto.schema.enabled,
                "run_count": auto.run_count,
                "last_run": auto.last_run.isoformat() if auto.last_run else None,
            }
            if auto.schema.expected_deliverables:
                entry["expected_deliverables"] = auto.schema.expected_deliverables
            if auto.schema.chain_spec:
                entry["has_chain"] = True
            result.append(entry)
        return result

    def view(self, days: int = 7) -> str:
        """Calendar view — show what fires when over the next N days."""
        try:
            from croniter import croniter
        except ImportError:
            return "croniter not installed"

        now = datetime.now()
        end = now + timedelta(days=days)
        events = []

        for name, auto in self._registry.automations.items():
            if not auto.schema.enabled or not auto.schedule:
                continue
            try:
                cron = croniter(auto.schedule, now)
                while True:
                    next_fire = cron.get_next(datetime)
                    if next_fire > end:
                        break
                    events.append((next_fire, name, auto.schedule))
            except Exception:
                continue

        events.sort(key=lambda x: x[0])

        if not events:
            return f"No events scheduled in next {days} days."

        lines = [f"Calendar: next {days} days ({len(events)} events)"]
        current_day = None
        for fire_time, name, schedule in events:
            day = fire_time.strftime("%Y-%m-%d (%A)")
            if day != current_day:
                lines.append(f"\n  {day}")
                current_day = day
            lines.append(f"    {fire_time.strftime('%H:%M')}  {name}  [{schedule}]")

        return "\n".join(lines)

    def check_deliverables(self, name: str) -> Dict[str, Any]:
        """Check if an automation's expected deliverables exist."""
        auto = self._registry.get(name)
        if not auto:
            return {"status": "error", "error": f"Unknown automation: {name}"}

        deliverables = auto.schema.expected_deliverables
        if not deliverables:
            return {"status": "ok", "message": "No expected deliverables"}

        missing = [p for p in deliverables if not Path(p).exists()]
        present = [p for p in deliverables if Path(p).exists()]

        return {
            "status": "ok" if not missing else "incomplete",
            "present": present,
            "missing": missing,
        }
