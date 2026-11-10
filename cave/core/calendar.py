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

THE CALENDAR TREE — a calendar HAS jobs and HAS sources; a source IS a calendar. Any folder of job files is a calendar
(a running app's store, a project's `.cave/automations/`), and no program has to host it. Its `.calendar/` folder, which
no registry reads as a job, holds `sources.json` (`{"sources": [...]}`, the calendars beneath it) and `clock.json` (the
clock that fires it); its id, what it answers to when a loop is checked, is made from the machine's name and the
folder's path. A source is `{"name", "type": "dir", "path"}` — a folder calendar, a relative path read from the folder
that lists it — or `{"name", "type": "http", "url"}` — a running app's calendar, whose url answers its joined view and
is told the ids of the calendars above in the `X-Calendar-Via` header. `joined()` lists every job of the calendar and
of every calendar beneath it, each tagged with the chain of source names it lives under, and refuses a loop. `tick_sources()`,
run by the clock before it fires what is due, makes each job fire once: by its own calendar's clock when it has one,
else by the nearest calendar above it that has one. An app's calendar has its own clock, so a calendar above it lists
its jobs and never fires them; a folder calendar's jobs that call a model are held dormant unless the source that lists
the folder says `"armed": true`.
"""
import fcntl
import hashlib
import http.client
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sdna.chain_ontology import Link, Chain, Compiler, LinkResult, LinkStatus

from cave.core.automation import (
    Automation,
    AutomationRegistry,
    AutomationSchema,
    CronAutomation,
    InputAutomation,
)

logger = logging.getLogger(__name__)

META_DIR = ".calendar"            # in a calendar's folder; not a *.json, so no registry reads it as a job
SOURCES_FILE = "sources.json"
CLOCK_FILE = "clock.json"
RUNS_FILE = "runs.json"           # when each interval job of the folder last ran, so a clock taking over waits its turn
VIA_HEADER = "X-Calendar-Via"     # the ids of the calendars above, sent to an http source so a loop is refused
CLAIM_LAPSE_S = 180.0             # a clock that has not beaten for this long has stopped: three of the heart's ticks
MAX_DEPTH = 8                     # the most calendars one chain of sources goes down
FETCH_SCHEMES = ("http", "https")
FETCH_TOTAL_S = 5.0               # the whole fetch of one http source, its redirects included
FETCH_MAX_BYTES = 1_000_000       # the most of its answer that is read
_MODEL_KEYS = ("prompt_template", "chain_spec")


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

        if "/" in str(spec["name"]):
            # a job's name is its file's name; "<chain>/<job>" is the name of a job held for a calendar beneath
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="A job's name has no '/': a job of a calendar beneath is changed in its own folder")

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
        except ImportError:
            return LinkResult(status=LinkStatus.ERROR, context=ctx,
                            error="croniter is not installed on this machine: no cron schedule can be read")
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

    def __init__(self, registry: Optional[AutomationRegistry] = None, sources_path: Optional[Path] = None,
                 source_types: Sequence[str] = ("dir", "http")):
        self._registry = registry or AutomationRegistry()
        self._sources_path = Path(sources_path) if sources_path else None
        # the kinds of source this calendar lists: an application whose sources are added over its API by anyone who
        # reaches it takes only "http", since a folder source reads the machine's own files
        self.source_types = tuple(source_types)
        self._mount_state: Dict[str, Tuple[Path, dict, bool]] = {}   # mounted name → (its file, its spec, armed)
        self._held: Dict[Path, str] = {}                              # the folder calendars this clock fires → chain
        # whether this clock fires its own folder's jobs: it does while it holds its own folder, and while it takes no
        # part in the tree's clocks; the heart fires a calendar's own jobs only when this is true
        self.own_held = True
        self._own_waited = False   # it asked for its own folder while another clock held it
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
        """Cancel a scheduled automation. A job held for a calendar beneath this one is refused: it is changed in its
        own calendar's folder, or its source is removed."""
        if name in self._registry.mounted:
            logger.info("Calendar: '%s' is a job of a calendar beneath; cancel it in its own folder", name)
            return False
        schema_path = self._registry.schema_path(name)
        removed = self._registry.unregister(name)
        if schema_path.exists():
            schema_path.unlink()
        if removed:
            logger.info("Calendar: cancelled '%s'", name)
        return removed

    def list_scheduled(self) -> List[Dict[str, Any]]:
        """List all scheduled automations."""
        result = []
        for name, auto in list(self._registry.automations.items()):
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
            if name in self._mount_state:  # held for a calendar beneath (a loader's mounts are this calendar's own)
                entry["calendar"] = name.rsplit("/", 1)[0]
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

        for name, auto in list(self._registry.automations.items()):
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

    # --- The calendar tree: sources, the joined view, the clock ---

    @property
    def store(self) -> Path:
        """The folder this calendar's own jobs live in."""
        return self._registry._dir

    @property
    def calendar_id(self) -> str:
        return calendar_id(self.store)

    def sources_path(self) -> Path:
        return self._sources_path or self.store / META_DIR / SOURCES_FILE

    def list_sources(self) -> List[Dict[str, Any]]:
        """The calendars beneath this one, as its sources file lists them."""
        return read_sources(self.sources_path())

    def _listed_sources(self) -> List[Dict[str, Any]]:
        """Its sources, a kind it does not list (written into the file by hand) made a refused one."""
        listed = []
        own = Path(self.store).resolve()
        for src in self.list_sources():
            if src.get("type", "dir") == "dir" and _source_store(src, self.store) == own:
                listed.append(src)  # the calendar listing itself (an app's "local" source): already its own
                continue
            if src.get("type", "dir") in ("dir", "http") and src.get("type", "dir") not in self.source_types:
                src = {**src, "type": "refused-kind", "refused": src.get("type", "dir")}
            listed.append(src)
        return listed

    def add_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Lists a calendar beneath this one. ValueError for a source no calendar can keep: a name that is not
        non-empty text without "/" (every source is listed, matched and removed by its name, and its name is a step in
        every job's chain), a type other than dir or http, a dir with no path, or a url that is not http or https (a
        calendar fetches it, and any other scheme would read the machine's own files or reach other kinds of service)."""
        source = dict(source or {})
        name = source.get("name")
        if not isinstance(name, str) or not name.strip() or "/" in name:
            raise ValueError("a calendar source needs a name, without '/'")
        kind = source.get("type") or ("http" if source.get("url") else "dir")
        source["type"] = kind
        if kind in ("dir", "http") and kind not in self.source_types:
            raise ValueError(f"this calendar lists only {' and '.join(self.source_types)} sources")
        if kind == "http":
            if not fetchable_url(source.get("url")):
                raise ValueError("a calendar source's url must be http or https")
        elif kind == "dir":
            if not isinstance(source.get("path"), str) or not source["path"].strip():
                raise ValueError("a folder calendar source needs a path")
        else:
            raise ValueError("a calendar source is a dir or an http calendar")
        sources = self.list_sources()
        if any(s.get("name") == name for s in sources):
            return {"error": f"Source '{name}' already exists"}
        sources.append(source)
        write_sources(self.sources_path(), sources)
        return {"success": True, "source": source}

    def remove_source(self, name: str) -> Dict[str, Any]:
        sources = self.list_sources()
        kept = [s for s in sources if s.get("name") != name]
        if len(kept) == len(sources):
            return {"error": f"Source '{name}' not found"}
        write_sources(self.sources_path(), kept)
        return {"success": True}

    def own_entries(self) -> List[Dict[str, Any]]:
        """This calendar's own jobs, tagged as its own: `source` "local", `calendar` ""."""
        own = [e for e in self.list_scheduled() if e["name"] not in self._mount_state]
        for entry in own:
            entry.update({"key": entry["name"], "source": "local", "calendar": ""})
        return own

    def joined(self, via: Sequence[str] = ()) -> List[Dict[str, Any]]:
        """Every job of this calendar and of every calendar beneath it (`own_entries` + `sources_joined`)."""
        if self.calendar_id in via:
            return [_status_entry([], "loop")]
        return self.own_entries() + self.sources_joined(via)

    def sources_joined(self, via: Sequence[str] = ()) -> List[Dict[str, Any]]:
        """Every job of every calendar beneath this one, each tagged with where it lives: `calendar` is the chain of
        source names from here down to the calendar holding it and `source` the first of them; a job of a folder
        calendar also carries `key`, the name this calendar holds it under. A source that cannot be read is one entry
        named "[<source>]" whose `status` says why: offline (an app that did not answer within its limits), missing (no
        such folder), refused (a url that is not http or https), loop (a calendar already on the way down), too deep.
        `via` is the ids of the calendars above this one — what an http source's handler is given — so a loop through
        running apps is refused as well as one through folders."""
        my_id = self.calendar_id
        if my_id in via:
            return [_status_entry([], "loop")]
        return _join(self._listed_sources(), self.store, list(via) + [my_id], [], self._registry)

    @property
    def clock_owner(self) -> str:
        """The clock's name in a claim: this machine, this process, this calendar — so a claim whose process is gone is
        known to have stopped at once."""
        return f"{socket.gethostname()}:{os.getpid()}:{self.calendar_id}"

    def tick_sources(self) -> Dict[str, Any]:
        """One beat of this calendar's clock, run before it fires what is due.

        It first records, beside each folder it held at the last beat, when that folder's jobs last ran — so a clock
        it hands the folder to waits their interval. Then it claims this calendar (so a calendar above it knows it has
        a clock) and every folder calendar beneath it, through folder sources only, that has no nearer clock; a folder
        a nearer clock asked for is handed to it, and let go this beat. It holds the jobs of each calendar it claimed in
        its registry under "<chain>/<job>", re-made only when the job's file changes, and lets go of the jobs of every
        calendar it no longer claims. `own_held` says whether it holds its own folder, and so fires its own jobs. A
        registry whose `fires_sources` is False takes no part in the tree's clocks: it claims nothing, not even its own
        folder, and writes nothing.
        """
        reg = self._registry
        owner = self.clock_owner
        held: Dict[str, Tuple[Path, Dict[str, Any]]] = {}
        if not getattr(reg, "fires_sources", True):
            self.own_held = True
        else:
            if self.own_held:
                _record_runs(self.store, {n: a for n, a in reg.automations.items() if n not in reg.mounted})
            for store, prefix in self._held.items():
                _record_runs(store, {n[len(prefix) + 1:]: reg.automations[n] for n in self._mount_state
                                     if n.startswith(prefix + "/") and n in reg.automations})
            try:
                own_now = claim(self.store, owner, 0)
            except OSError as e:
                logger.warning("Calendar: cannot beat its own clock at %s: %s", self.store, e)
                own_now = True
            if own_now and self._own_waited:  # handed back by the clock that held it: its jobs wait from their record
                runs = _read_runs(self.store)
                for name, auto in reg.automations.items():
                    if name not in reg.mounted:
                        _seed_clock(auto, runs.get(name))
            self._own_waited = not own_now
            self.own_held = own_now
            _hold(self._listed_sources(), self.store, [self.calendar_id], [], 1, owner, held, set())
        now_held = {store: prefix for prefix, (store, _) in held.items()}
        for store in set(self._held) - set(now_held):
            release(store, owner)
        self._held = now_held

        # a job file another loader already holds in this registry (OM's devdir loader) is held once, by it
        elsewhere = {path.resolve() for n, path in reg.mounted.items() if n not in self._mount_state}
        desired: Dict[str, Tuple[Path, dict, bool]] = {}
        runs_of: Dict[str, Dict[str, Any]] = {}
        for prefix, (store, src) in held.items():
            runs_of[prefix] = _read_runs(store)
            for job_file in sorted(store.glob("*.json")):
                if job_file.resolve() in elsewhere:
                    continue
                try:
                    data = AutomationSchema.from_json(job_file).to_dict()
                except Exception as e:
                    logger.warning("Calendar: %s is not a job (%s)", job_file, e)
                    continue
                own = data["name"]
                data["name"] = f"{prefix}/{own}"
                # the names a job gives its own calendar's jobs are held under the same chain
                data["depends_on"] = [f"{prefix}/{d}" for d in data.get("depends_on") or []]
                data["parallel"] = [f"{prefix}/{d}" for d in data.get("parallel") or []]
                desired[data["name"]] = (job_file, data, bool(src.get("armed")))
        for name in list(self._mount_state):
            if name not in desired:
                reg.unmount(name)
                self._mount_state.pop(name, None)
        for name, state in desired.items():
            if self._mount_state.get(name) == state and name in reg.mounted:
                continue  # unchanged
            job_file, data, armed = state
            try:
                auto = Automation.create(schema=AutomationSchema.from_dict(data))
            except Exception as e:
                logger.warning("Calendar: %s could not be made (%s)", job_file, e)
                continue
            before = reg.automations.get(name) if name in reg.mounted else None
            if before is not None:  # its file changed: it keeps its clock state (last run, run count)
                _carry_clock(before, auto)
            else:  # first held here: an interval job waits from its last run on record, wherever it ran
                prefix = name.rsplit("/", 1)[0]
                _seed_clock(auto, runs_of.get(prefix, {}).get(name[len(prefix) + 1:]))
            if not armed and any(data.get(k) for k in _MODEL_KEYS):
                # a model call from another folder is never spent unasked: never due, never fired by its event
                auto.schema.enabled = False
                auto._cron_job.enabled = False
                auto.dormant = True
            reg.mount(auto, job_file)
            self._mount_state[name] = state
        return {"held": sorted(held), "mounted": sorted(desired)}


# =============================================================================
# The calendar tree's parts — ids, sources files, the clock's claim, the http fetch
# =============================================================================


def _meta(store: Path) -> Path:
    """The calendar's `.calendar/` folder, made with a .gitignore so its clock and its runs are never committed."""
    meta = Path(store) / META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    ignore = meta / ".gitignore"
    if not ignore.exists():
        ignore.write_text(f"{CLOCK_FILE}\n{RUNS_FILE}\n")
    return meta


def _read_runs(store: Path) -> Dict[str, Any]:
    """When each job of a calendar's folder last ran, as the clocks that fired it recorded."""
    try:
        runs = json.loads((Path(store) / META_DIR / RUNS_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return runs if isinstance(runs, dict) else {}


def _record_runs(store: Path, jobs: Dict[str, InputAutomation]) -> None:
    """Records, beside a calendar's folder, when each of its jobs this clock fired last ran — by the job's own name in
    that folder — when it moved; a clock that takes the folder over reads it."""
    known = _read_runs(store)
    runs = dict(known)
    for own, auto in jobs.items():
        if auto.last_run:
            runs[own] = auto.last_run.isoformat()
    if runs == known:
        return
    try:
        path = _meta(store) / RUNS_FILE
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(runs, indent=2))
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("Calendar: cannot record the runs of %s: %s", store, e)


def _carry_clock(before: InputAutomation, after: InputAutomation) -> None:
    after.last_run, after.run_count = before.last_run, before.run_count
    after._cron_job.last_run, after._cron_job.run_count = before._cron_job.last_run, before._cron_job.run_count


def _seed_clock(auto: InputAutomation, last_run: Any) -> None:
    if not auto._cron_job.is_interval or not isinstance(last_run, str):
        return
    try:
        when = datetime.fromisoformat(last_run)
    except ValueError:
        return
    auto.last_run = auto._cron_job.last_run = when


def calendar_id(store: Path) -> str:
    """The id a calendar folder answers to when a loop is checked: the machine's name and the folder's resolved path,
    hashed — the same whether the folder is reached as a folder or through the app whose store it is, and nothing is
    written to make it."""
    where = f"{socket.gethostname()}:{Path(store).resolve()}"
    return hashlib.sha256(where.encode()).hexdigest()[:20]


def read_sources(path: Path) -> List[Dict[str, Any]]:
    """The sources a sources file lists — only an object with a name is one; anything else in it is passed over."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logger.warning("Calendar: sources file %s unreadable: %s", path, e)
        return []
    listed = data.get("sources", []) if isinstance(data, dict) else []
    return [s for s in listed if isinstance(s, dict) and isinstance(s.get("name"), str) and s["name"]]


def write_sources(path: Path, sources: List[Dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"sources": sources}, indent=2))
    os.replace(tmp, path)


def _source_store(source: Dict[str, Any], base: Path) -> Optional[Path]:
    """The folder a dir source names — `~` expanded, a relative path read from the folder that lists it."""
    raw = source.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        path = Path(base) / path
    return path.resolve()


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _owner_alive(owner: str) -> bool:
    """False only for a clock of this machine whose process is gone (`<machine>:<pid>:<calendar>`)."""
    host, _, rest = str(owner).partition(":")
    pid, _, _ = rest.partition(":")
    if host != socket.gethostname() or not pid.isdigit():
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claim(store: Path, owner: str, distance: int, now: Optional[float] = None) -> bool:
    """Takes or keeps a clock's hold on a calendar; True when that clock fires it this beat.

    `distance` is how far above the calendar the clock is: 0 its own clock, 1 the calendar just above it. A clock takes
    a calendar nobody holds, one whose holder has not beaten for CLAIM_LAPSE_S, and one whose holder's process on this
    machine is gone. A calendar held, live, from farther away is never taken at once — the holder may already have its
    jobs due this beat — so the nearer clock asks for it (`wanted_by`); at its next beat the holder hands it over and
    lets it go, and the nearer clock holds it from its own next beat. So two clocks never hold one calendar in one beat.
    """
    now = time.time() if now is None else now
    far = float(1 << 30)
    with open(_meta(store) / CLOCK_FILE, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            current = json.loads(fh.read() or "{}")
        except ValueError:
            current = {}
        if not isinstance(current, dict):
            current = {}
        holder = current.get("owner")
        wanted = current.get("wanted_by") if isinstance(current.get("wanted_by"), dict) else None
        if wanted and (now - _number(wanted.get("beat"), 0.0) > CLAIM_LAPSE_S or wanted.get("owner") == holder):
            wanted = None  # an ask whose clock stopped, or the holder's own, is no ask

        def write(state: Dict[str, Any]) -> None:
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(state))
            fh.flush()

        if not holder or now - _number(current.get("beat"), 0.0) > CLAIM_LAPSE_S or not _owner_alive(holder):
            write({"owner": owner, "distance": distance, "beat": now})
            return True
        if holder == owner:
            if wanted and _number(wanted.get("distance"), far) < distance:
                write({"owner": wanted["owner"], "distance": wanted["distance"], "beat": now})  # handed over
                return False
            write({"owner": owner, "distance": distance, "beat": now, **({"wanted_by": wanted} if wanted else {})})
            return True
        nearer_than_holder = distance < _number(current.get("distance"), far)
        nearer_than_ask = wanted is None or wanted.get("owner") == owner or distance < _number(wanted.get("distance"), far)
        if nearer_than_holder and nearer_than_ask:
            current["wanted_by"] = {"owner": owner, "distance": distance, "beat": now}
            write(current)
        return False


def release(store: Path, owner: str) -> None:
    """Lets go of a clock's hold on a calendar, when that clock holds it."""
    try:
        with open(Path(store) / META_DIR / CLOCK_FILE, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                current = json.loads(fh.read() or "{}")
            except ValueError:
                return
            if isinstance(current, dict) and current.get("owner") == owner:
                fh.seek(0)
                fh.truncate()
    except OSError as e:
        logger.warning("Calendar: cannot let go of %s: %s", store, e)


def _hold(sources, base: Path, via: List[str], chain: List[str], depth: int, owner: str,
          held: Dict[str, Tuple[Path, Dict[str, Any]]], seen: Set[str]) -> None:
    """Claims every folder calendar beneath `base` through folder sources; an http source is a running app, whose own
    clock fires it, so the walk stops there."""
    if depth > MAX_DEPTH:
        return
    for src in sources:
        if src.get("type", "dir") != "dir":
            continue
        store = _source_store(src, base)
        if store is None or not store.is_dir():
            continue
        sid = calendar_id(store)
        if sid in via or sid in seen:
            continue
        seen.add(sid)
        here = chain + [src["name"]]
        try:
            if claim(store, owner, depth):
                held["/".join(here)] = (store, src)
        except OSError as e:
            logger.warning("Calendar: cannot claim %s: %s", store, e)
        _hold(read_sources(store / META_DIR / SOURCES_FILE), store, via + [sid], here, depth + 1, owner, held, seen)


def _status_entry(chain: List[str], status: str, **more) -> Dict[str, Any]:
    return {"name": f"[{chain[-1] if chain else 'calendar'}]", "source": chain[0] if chain else "local",
            "calendar": "/".join(chain), "status": status, **more}


def _entry(name: str, auto: InputAutomation, chain: List[str], key: str) -> Dict[str, Any]:
    entry = {
        "name": name,
        "key": key,
        "type": type(auto).__name__,
        "schedule": auto.schedule,
        "enabled": auto.schema.enabled,
        "run_count": auto.run_count,
        "last_run": auto.last_run.isoformat() if auto.last_run else None,
        "source": chain[0],
        "calendar": "/".join(chain),
    }
    if getattr(auto, "dormant", False):
        entry["dormant"] = True
    if auto.schema.expected_deliverables:
        entry["expected_deliverables"] = auto.schema.expected_deliverables
    if auto.schema.chain_spec:
        entry["has_chain"] = True
    return entry


def _join(sources, base: Path, via: List[str], chain: List[str], live: AutomationRegistry) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for src in sources:
        here = chain + [src["name"]]
        if len(here) > MAX_DEPTH:
            out.append(_status_entry(here, "too deep"))
            continue
        kind = src.get("type", "dir")
        if kind == "dir":
            store = _source_store(src, base)
            if store is None or not store.is_dir():
                out.append(_status_entry(here, "missing"))
                continue
            sid = calendar_id(store)
            if sid == via[-1]:
                continue  # the calendar listing itself (a "local" source): its jobs are already its own
            if sid in via:
                out.append(_status_entry(here, "loop"))
                continue
            prefix = "/".join(here)
            jobs = AutomationRegistry(store)
            jobs.load_all()
            for name, auto in sorted(jobs.automations.items()):
                key = f"{prefix}/{name}"
                out.append(_entry(name, live.automations.get(key, auto) if key in live.mounted else auto, here, key))
            out.extend(_join(read_sources(store / META_DIR / SOURCES_FILE), store, via + [sid], here, live))
        elif kind == "http":
            url = src.get("url")
            if not fetchable_url(url):
                out.append(_status_entry(here, "refused", reason="a calendar source is fetched only over http or https"))
                continue
            try:
                remote = _listed(fetch_calendar(str(url).rstrip("/"), via))
            except Exception as e:
                logger.info("Calendar: source %s offline: %s", src["name"], e)
                out.append(_status_entry(here, "offline"))
                continue
            for job in remote:
                if not isinstance(job, dict):
                    continue
                job = dict(job)
                inner = job.get("calendar")
                if inner is None:  # an app that does not tag: its own jobs are "local", a job of its source carries it
                    inner = "" if job.get("source") in (None, "local") else str(job.get("source"))
                job["calendar"] = "/".join(here + ([inner] if inner else []))
                job["source"] = here[0]
                out.append(job)
        elif kind == "refused-kind":
            out.append(_status_entry(here, "refused", reason=f"this calendar lists no {src.get('refused')} sources"))
        else:
            out.append(_status_entry(here, "refused", reason=f"a calendar source is a dir or an http calendar, not {kind!r}"))
    return out


def _listed(answer: Any) -> List[Any]:
    """The jobs an http calendar answered: a list, or the list a status answer carries."""
    if isinstance(answer, list):
        return answer
    if isinstance(answer, dict):
        for field in ("joined", "automations", "scheduled"):
            if isinstance(answer.get(field), list):
                return answer[field]
    raise ValueError("a calendar source answered no list of jobs")


def parse_via(raw: Optional[str]) -> List[str]:
    """The ids of the calendars above, as an http calendar's handler is given them in its `X-Calendar-Via` header."""
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def fetchable_url(url: Any) -> bool:
    """An address a calendar may fetch: http or https only — never `file://`, `ftp://` or any other scheme, which would
    read the machine's own files or reach other kinds of service through the calendar."""
    try:
        return urllib.parse.urlsplit(str(url)).scheme.lower() in FETCH_SCHEMES
    except ValueError:
        return False


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a source's redirect only to another http or https address (the stdlib's own handler refuses `file:` and
    `data:`, and follows `ftp:`)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not fetchable_url(newurl):
            raise urllib.error.HTTPError(newurl, code, "a redirect away from http/https is refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _deadline_connection(base, deadline: float):
    """`base` (HTTPConnection or HTTPSConnection) whose socket is shut at `deadline`: a source answering a byte at a
    time resets a per-read timeout forever, so only a clock on the whole fetch bounds it."""

    class Connection(base):
        def connect(self):
            if isinstance(self.timeout, (int, float)):
                self.timeout = max(0.01, min(self.timeout, deadline - time.monotonic()))
            timer = threading.Timer(max(0.0, deadline - time.monotonic()), self._cut)
            timer.daemon = True
            timer.start()
            super().connect()
            self._held = self.sock  # urllib drops `self.sock` before the answer's body is read; the cut still needs it

        def _cut(self):
            sock = self.sock or getattr(self, "_held", None)
            if sock is not None:
                try:
                    socket.socket.shutdown(sock, socket.SHUT_RDWR)  # the base method: an SSLSocket's own drops its TLS
                except OSError:
                    pass

    return Connection


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, deadline: float):
        super().__init__()
        self._deadline = deadline

    def http_open(self, req):
        return self.do_open(_deadline_connection(http.client.HTTPConnection, self._deadline), req)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, deadline: float):
        super().__init__()
        self._deadline = deadline

    def https_open(self, req):
        return self.do_open(_deadline_connection(http.client.HTTPSConnection, self._deadline), req,
                            context=self._context)


def fetch_calendar(url: str, via: Sequence[str] = ()) -> Any:
    """The JSON an http or https calendar answers, told the calendars above it (`via`, in the `X-Calendar-Via` header),
    read within FETCH_TOTAL_S for the whole fetch (connect, redirects, headers and body) and FETCH_MAX_BYTES of body; a
    slower or larger answer raises, as a failed fetch does."""
    if not fetchable_url(url):
        raise ValueError("a calendar source is fetched only over http or https")
    deadline = time.monotonic() + FETCH_TOTAL_S
    opener = urllib.request.build_opener(_HttpOnlyRedirects, _DeadlineHTTPHandler(deadline),
                                         _DeadlineHTTPSHandler(deadline))
    headers = {"Accept": "application/json"}
    if via:
        headers[VIA_HEADER] = ",".join(via)
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=3) as resp:
        payload = resp.read(FETCH_MAX_BYTES + 1)
    if time.monotonic() >= deadline:
        raise TimeoutError(f"a calendar source answered for over {FETCH_TOTAL_S:g} s")
    if len(payload) > FETCH_MAX_BYTES:
        raise ValueError(f"a calendar source answered over {FETCH_MAX_BYTES} bytes")
    return json.loads(payload.decode())
