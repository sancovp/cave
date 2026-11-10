# CAVE — the agent runtime

## 0. What CAVE is, what it ends as, and where the rest of its design is

CAVE is the agent runtime, the tower's L7 (the top-level design §15): the `CAVEAgent` base class an application
subclasses to become a running agent — OM's daemon, JobWorld's and HealthWorld's servers, SANCREV's WakingDreamer —
with its heart, its automations and its generic HTTP server. CAVE is a library and knows nothing of the applications
built on it; each application's own routes live in its own server, which extends `CAVEHTTPServer`.

CAVE ends as a **PROGRAM**: the Python package `cave-harness`, a library. It is released by the canonical home's
publishing manifest unit `cave`, which mirrors this folder to the public repository `sancovp/cave` and uploads the
package to PyPI; its version is stated in `pyproject.toml` and `cave/__version__`, and its history in `CHANGELOG.md`
beside this file.

**Configurable:** the calendar (§1, §2) takes every folder from its registry (`$HEAVEN_DATA_DIR/automations` unless an
application passes its own) and its sources file, and names no machine and no person. The rest of CAVE is not yet
read into this design: `CAVEAgent`'s constructor wires SANCREV's SANCTUM catch-up tick and its MiniCLI into the
library, against the library law above, and the rest of its design is held in two reference documents, rolled in
here as each part is read — [`ARCHITECTURE.md`](ARCHITECTURE.md) (the runtime, its mixins and its servers) and
[`CAVEAGENT_DESIGN.md`](CAVEAGENT_DESIGN.md) (the god object and its anatomy). That reading is owed, on the board.

## 1. The calendar — jobs, the registry and the heart's clock

A **job** is one JSON file, an `AutomationSchema`: its name, its trigger (a `schedule` — a cron expression or
`every:<seconds>` — or an `event_name`), what it runs (a `code_pointer` with its `code_args`, a `prompt_template`, or a
`chain_spec`), where its result goes (`delivery`), and its gates (`expected_deliverables`, `depends_on`, `one_shot`,
`parallel`, `enabled`). `Automation.create` makes the job's live object from it — a `CronAutomation` for a schedule,
an `EventAutomation` for an event, a `ManualAutomation` otherwise.

An `AutomationRegistry` holds the live jobs of one folder (`load_all`, `hot_reload`, `register`, `save_schema`, written
whole or not at all). A `Calendar` (`cave/core/calendar.py`) compiles a scheduling spec into a registered job
(`schedule`, through its parse → build → register chain) and manages the registry's jobs (`list_scheduled`, `view`,
`cancel`, `check_deliverables`).

The **clock** is the heart: `CAVEAgent` adds a `cron_scheduler` tick that runs `fire_due_automations` every 60 s — it
polls the jobs still running as their own processes, fires every due job whose dependencies last succeeded, checks its
deliverables, records a failure as a blockage, removes a one-shot job and fires the parallel ones — and an
`automation_hot_reload` tick that reloads the folder every 300 s. A job is due by its SDNA `CronJob`: a cron job first
fires at its next real boundary after it is loaded, an interval job at once. `CAVEAgent.get_calendar()` is the calendar
over the agent's own registry — the one its clock ticks.

## 2. The calendar tree — every calendar can be the parent of any other

**A calendar HAS jobs and HAS sources; a source IS a calendar.** Any folder of job files is a calendar — a running
application's store, a project's `.cave/automations/` — and no program has to host it. A source is listed in the
calendar's sources file as `{"name", "type": "dir", "path"}`, a folder calendar (a relative path is read from the
folder that lists it), or `{"name", "type": "http", "url"}`, a running application's calendar. So calendars join
upwards to any depth, a folder calendar is fired by whatever calendar above it has a clock, and the same calendar can
sit under one parent today and another tomorrow.

**Where a calendar keeps its tree:** its `.calendar/` folder — never read as a job — holds `sources.json`
(`{"sources": [...]}`; an application may keep its sources file elsewhere, `Calendar(registry, sources_path=…)`, the
agent's `calendar_sources_path`), `clock.json` (the clock that fires it) and `runs.json` (when each of its jobs last
ran, written by the clock that fired it); the folder makes its own `.gitignore`, so the clock and the runs are
never committed and a committed sources file is. Its **id**, the name it answers to when a loop is
checked, is the machine's name and the folder's resolved path, hashed (`calendar_id`): the same whether the folder is
reached as a folder or through the application whose store it is, and nothing is written to make it. A calendar lists
the kinds of source it takes (`source_types`): an application whose sources are added over its API by anyone who
reaches it takes only http sources, since a folder source reads the machine's own files.

**The joined view.** `Calendar.joined(via)` lists the calendar's own jobs (`own_entries`: `source` "local",
`calendar` "") and every job beneath it (`sources_joined`), each tagged with where it lives: `calendar` is the chain of
source names from here down to the calendar holding it, `source` the first of them, and a folder calendar's job also
carries `key`, the name this calendar holds it under (`<chain>/<job>`). A source that cannot be read is one entry
named `[<source>]` whose `status` says why: offline (an application that did not answer within the limits), missing (no
such folder), refused (a url that is not http or https), loop, too deep (eight calendars down). An application that
lists its own jobs its own way joins `sources_joined` to them.

**An http calendar's wire.** A parent fetches `<url>` with the ids of the calendars above, comma-separated, in the
`X-Calendar-Via` header (never in the url, so the path the application sees is the one listed), and reads the answer as
a list of jobs, or as an object carrying one under `joined`, `automations` or `scheduled`. The application's handler
gives `parse_via(<its X-Calendar-Via header>)` to `joined` or `sources_joined`; a calendar whose id is in
`via` answers one `loop` entry, so a loop through running applications ends as surely as one through folders. A job
from an application that does not tag is read as its own when its `source` is "local", else as its source's. The
fetch is http or https only, follows a redirect only to http or https, is cut at 5 s for the whole fetch and reads at
most 1 MB (`fetch_calendar`, `fetchable_url`); `add_source` refuses a nameless source, a name with "/", a folder with no
path, any other type, and any other scheme.

**Each job fires once.** `Calendar.tick_sources()` is one beat of a calendar's clock, run by the heart before it fires
what is due. It claims the calendar itself at distance 0 — so a calendar above knows it has a clock — and, through
folder sources only, every folder calendar beneath it at its distance, how far above that calendar the clock is (1 for
a source, 2 for a source's source). The heart ticks only a calendar over the registry it fires: an application whose
`get_calendar()` answers a calendar over another registry keeps that calendar as it was, and nothing is claimed,
mounted or written for it. `claim` takes a calendar nobody holds, one whose holder has not beaten for 180 s (three
ticks), and one whose holder's process on this machine is gone (a clock is named by its machine, its process and its
calendar), so a restarted application takes its folder back at once. A calendar held, live, from farther away is never
taken at once, because the holder may already have its jobs due in this beat: the nearer clock asks for it
(`wanted_by` in `clock.json`), the holder hands it over at its next beat and lets it go, and the nearer clock holds it
from its own next beat. So two clocks never hold one calendar in the same beat, a job fires by its own calendar's clock
when it has one, else by the nearest calendar above it that has one, and a folder reached twice is held once. A
calendar's own jobs are fired by its heart only while it holds its own folder (`own_held`): while a calendar above still
holds it, that calendar fires them, until it hands them back.

**When a job last ran is kept with its folder.** At the start of every beat a clock records, in the `runs.json` of each
folder it held at the last beat (its own included), when each of that folder's jobs last ran. A clock that takes a
folder over — handed to it, or after its holder stopped — starts each interval job from that record, so it waits its
interval wherever it last ran; a calendar handed its own folder back does the same for its own jobs. A cron job is
anchored where it is made, as SDNA's `CronJob` anchors it, never caught up. What this leaves: a job fired by a clock
that then stops before its next beat is not on the record, so the clock that takes the folder over may fire it once
more; and a cron time that falls inside the beat of a handover is not fired.

**The jobs of a calendar beneath.** The jobs of each calendar a clock holds are mounted into its registry under
`<chain>/<job>` (`AutomationRegistry.mount`), the names they give their own calendar's jobs (`depends_on`, `parallel`)
under the same chain, so a dependency is met as it is in its own calendar. A job is re-made only when its file changes,
keeping its clock state (its last run, its run count). A job file another loader already holds in the same registry,
mounted with its file (OM's devdir loader), is held once, by that loader, and is listed as this calendar's own job.
`hot_reload` keeps every held job, and a calendar no longer held is let go (`release`) and its jobs unmounted; the
calendar unmounts only what it mounted. An http source is a running application with its own clock: the calendar above
lists its jobs and never fires them.

**A held job is changed only in its own folder:** `save_schema` refuses one, `Calendar.cancel` refuses one (OM's 🗑 says
where its switch is), and `Calendar.schedule` refuses any name with "/", so no job can be scheduled under a held job's
name; the one thing a holding clock does to a child's file is what the job does in its own calendar — a one-shot,
fired, removes its own file.

**What it never spends unasked:** a job of another folder that calls a model (`prompt_template`, `chain_spec`) is held
dormant — listed with `dormant: true`, its clock and its `enabled` both off, so it is never due and never fired by its
event — unless the source that lists the folder says `"armed": true`. A registry that fires only its own kind of job
sets `fires_sources = False`, so it claims no calendar whose jobs it would refuse, and takes no part in the tree's clocks
— it claims nothing, its own folder included, and writes nothing (HealthWorld's own-jobs registry). Such an
application's folder carries no claim, so it is listed by a calendar above as an http source, never as a folder: listed
as a folder, its jobs would be held above and fire twice, and nothing refuses that listing.

**Who stands on it:** OM's daemon and HealthWorld are `CAVEAgent`s whose calendar is this one: OM's heart ticks its
sources and fires the folders beneath it; HealthWorld's own-jobs registry fires only its own jobs and joins running
apps' calendars to its listing; each serves its joined view at its own `GET /api/automations` and its sources at
`/api/calendar-sources`. JobWorld is outside this calendar: it keeps its own one-level merge and its own
`get_calendar()`, a calendar over a registry its heart does not fire, so the heart leaves it as it was; listed as
another calendar's source, it answers in the untagged shape (its jobs read as its own, a source's as that source's).

ASPIRATIONAL: OM's devdir loader takes no claim for the `.cave/automations` folders it holds, so a folder under OM's
onion that another calendar's clock lists as a source fires there too; the loader takes the claim for each folder it
holds. ASPIRATIONAL: an application whose registry fires only its own jobs claims its folder without writing into it,
so a folder listing of it is refused.
