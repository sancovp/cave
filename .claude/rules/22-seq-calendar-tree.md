# 22-seq-calendar-tree — CAVE's calendar tree: sources, the joined view, and the clock that holds each job once
<docsys kind="dev-flow" role="instance"/>

PROCEDURE flow (rule 28b): every stage runs on every change to this feature, and nothing sits in a stage. The design is
`DESIGN.md` §1 (the calendar) and §2 (the calendar tree); OM's side is `base/onionmorph/.claude/rules/22-seq-calendar-and-heartbeat.md`.
Board row: `cave_states.md`, THE RELEASE LINE. Three parts, one execution boundary: a calendar's `.calendar/` folder holds
its sources, its clock and its jobs' last runs; the heart's `cron_scheduler` tick runs `tick_sources` on the calendar
over the registry it fires, before it fires what is due, so each job is held by one clock in every beat — a nearer clock
asks for a folder and is handed it at the holder's next beat, never takes it at once; a parent lists an
http source over the wire and tells it, in the `X-Calendar-Via` header, which calendars are above.

TRIGGER:[editing cave's `calendar.py` (`ParseSpecLink`'s name check, `cancel`, anything from `Calendar.store` down) ·
`automation.py` `AutomationRegistry` (`mount`, `unmount`, `schema_path`, `save_schema`, `hot_reload`, `fires_sources`) ·
`cave_agent.py` `get_calendar` / `fire_due_automations` · `mixins/automation_mixin.py` · OM's `automations.py` /
`server.py` `/api/automations*` and `/api/calendar-sources*` / `woom_automations.py` / the `manage-the-calendar` skill ·
HealthWorld's `get_calendar` / `list_automations` / the sources methods / `OwnJobsRegistry` · any `CAVEAgent` subclass
that defines `get_calendar` or builds its own `AutomationRegistry` · any loader that puts a folder's jobs into a registry
· a report of "a job fired twice", "a job never fired", "a job fired again after an edit", "a source shows offline though
it is up", "a loop was not refused", "my job file changed by itself", "a cancel did nothing"]
DO:[run RETRIEVE → COHERENCE SET → THE CHANGE → THE PROOF in order · read every range whole before you edit · prove each
change on temporary folders and local test servers, with a registry and a stand-in heart of your own
(`SimpleNamespace(automation_registry=…, get_calendar=…)` handed to `CAVEAgent.fire_due_automations`), never on a running
daemon · measure every store in THE PROOF before and after · tick only the calendar over the registry the heart fires ·
hand a folder over, never take one held live from farther away (`claim`'s `wanted_by`) · fire a calendar's own jobs only
while it holds its own folder (`own_held`) · record every held folder's runs at the start of the beat, before any claim ·
name a held job `<chain>/<job>`, which no `Calendar.schedule` can produce (a name with "/" is refused there) · prefix a
held job's `depends_on` and `parallel` with its chain · carry a held job's clock state across a re-made file, and seed
an interval job from its folder's `runs.json` when a clock takes the folder over · keep every job that spends a model dormant
on every path that can fire it (`schema.enabled` and its `CronJob` both off) · mount every job a loader holds with its
file (`registry.mount`), so the calendar holds that file once, and list it as the calendar's own job — "held from
beneath" is only what the calendar itself mounted (`_mount_state`) · read each http answer as untrusted: a list, or an
object holding one under `joined`, `automations` or `scheduled`]
NOT:[add a second clock, scheduler or registry for a source · tick a calendar whose registry is not the one the heart
fires (an application with a calendar of its own, JobWorld's, is left as it was) · fire a folder's job twice from one
registry · change a held job from the calendar above it (save, cancel or schedule it) — it is changed in its own folder ·
unmount another loader's jobs · write into a calendar's folder anything but its jobs and its `.calendar/` folder · read a
path, a scheme or a kind of source the calendar's `source_types` does not list · fetch with a header, redirect or body
limit of your own (use `fetch_calendar`) · let a source's failure stop the calendar's own jobs (it is one entry with a
`status`) · list a running application's own job folder as a folder source — list the application over http]

## RETRIEVE — read each range whole before you change anything (lines at the current code)

| file | lines | what it holds |
|---|---|---|
| `application/cave/cave/core/calendar.py` | 1-92 | the tree's statement and its constants: `META_DIR`, `SOURCES_FILE`, `CLOCK_FILE`, `RUNS_FILE`, `VIA_HEADER`, `CLAIM_LAPSE_S` 180, `MAX_DEPTH` 8, the fetch limits, `_MODEL_KEYS` |
| `application/cave/cave/core/calendar.py` | 94-141 · 225-316 | `ParseSpecLink` (a name with "/" refused) · `Calendar.__init__` (`source_types`, `_mount_state`, `_held`, `own_held`, `_own_waited`) · `schedule` · `cancel` (a held job refused) · `list_scheduled` (`calendar` only for its own mounts; `last_outcome`, `last_exit`) |
| `application/cave/cave/core/calendar.py` | 378-569 | `store` · `calendar_id` · `sources_path` · `list_sources` · `_listed_sources` · `add_source` · `remove_source` · `own_entries` · `joined` · `sources_joined` · `clock_owner` (machine:pid:calendar) · `tick_sources` (runs recorded first; own claim → `own_held`, own jobs seeded when handed back; hold, release; a file another loader holds skipped; `depends_on` and `parallel` prefixed; mount, unmount of its own mounts only; clock state carried or seeded; dormancy) |
| `application/cave/cave/core/calendar.py` | 571-776 | `_meta` (the `.calendar/` folder and its `.gitignore`) · `_read_runs` · `_record_runs` · `_carry_clock` (the outcome carried too) · `_seed_clock` · `calendar_id` · `read_sources` · `write_sources` · `_source_store` · `_number` · `_owner_alive` · `claim` (take, renew, hand over, ask) · `release` · `_hold` |
| `application/cave/cave/core/calendar.py` | 777-883 | `_status_entry` · `_entry` (`dormant`, `last_outcome`, `last_exit`) · `_join` (folder and http branches, loops, depth) · `_listed` · `parse_via` · `fetchable_url` |
| `application/cave/cave/core/calendar.py` | 884-957 | `_HttpOnlyRedirects` · the deadline connection and handlers · `fetch_calendar` |
| `application/cave/cave/core/automation.py` | 70-170 · 555-680 | `AutomationSchema` (`tells_failures`, written by `to_dict` only when set; `from_json`, `to_cron_job`: a job with no schedule gets `every:900`) · `DeliveryRouter` (`deliver`; each target's answer, `log` and `self` answering `logged`) |
| `application/cave/cave/core/automation.py` | 166-441 | `render_args` (`${CALENDAR_DIR}`, `${PYTHON}`) · `InputAutomation` (`calendar_dir`, `_process`, `last_outcome`, `last_exit`, `keep_outcome`, `execute` — a `subprocess.Popen` returned is kept and its `pid` named —, `last_run`, `run_count`, `fire`, `is_due`) |
| `application/cave/cave/core/automation.py` | 442-548 | `CronAutomation` · `EventAutomation` (`is_due` False, `matches_event`) · `ManualAutomation` · `Automation.create` |
| `application/cave/cave/core/automation.py` | 676-837 | `AutomationRegistry`: `fires_sources` · `mounted` · `load_all` · `hot_reload` (skips a held name; an updated job keeps its outcome) · `register` · `unregister` · `mount` · `unmount` · `schema_path` · `save_schema` (a held job refused) · `get_due` · `get_by_event` |
| `application/cave/cave/core/cave_agent.py` | 109-243 | init order: `start_heart`, `_init_automations`, the `cron_scheduler` tick, the `automation_hot_reload` tick |
| `application/cave/cave/core/cave_agent.py` | 546-816 | `get_calendar` (over `self.automation_registry`) · `fire_due_automations`: Phase 1 follows each process a job started — the `Popen` it kept says whether it runs and its exit code, nonzero `failed` (written, a blockage, the job's `last_outcome` and `last_exit`), else the pid and `/proc` start time —; Phase 2 ticks the calendar only when its `.registry` is the heart's, reads `own_held`, then fires `registry.get_due()` — its own jobs only while it holds its own folder — with `depends_on`, results, `parallel`, one-shot cleanup through `schema_path` · `_get_pid_start_time` · `_write_automation_failure` (each "/" of a held name written "__") |
| `application/cave/cave/core/telling.py` | 1-229 | the teller: `GH_TIMEOUT_S` 20 · `TOLD` (delivered, logged, ok, sent) · `_MEMORY` · `gh_env` 34-48 (the login check cut short) · `run_gh` 50-60 · `Teller` 86-229: `target` · `_tellings` 98 (file and memory; an unreadable file set aside) · `_keep` 119 · `failed` 134 · `cleared` 158 · `forget` 179 · `_open_issue` 194 (an open issue of the job's title taken up) · `_close_issue` 216 (closed with its comment in one call) |
| `application/cave/cave/core/cave_agent.py` | 555-789 · 791-835 | `fire_due_automations`'s three outcome sites (Phase 1's process end, given the process's kept `calendar_dir`, `tells_failures` and `one_shot`; the in-process result, every status but success recorded; the parallel job, an error or blocked result a failure) · `record_outcome`: the block report, the blockage, the teller of the job's own calendar unless it `tells_failures`, a one-shot's record dropped |
| `application/cave/cave/core/mixins/automation_mixin.py` | 1-116 | `_init_automations` · `add_automation` · `remove_automation` · `fire_event` (checks `schema.enabled`) · `fire_all_due` |
| `application/cave/cave/core/mixins/anatomy.py` | 52-75 · 79-150 | `Tick` · `Heart` and its tick loop (ticks run in series: one long job delays every beat) |
| `base/sdna/sdna/cron.py` | 106-187 | `CronJob`: a cron expression anchored at creation, an interval due at once with no `last_run`, `enabled`, `mark_run` |
| `base/onionmorph/onionmorph/automations.py` | 94-99 · 101-287 | `_NOT_CANCELLABLE` (names with "/" refused) · `AutomationService`: `calendar` is the cave's `get_calendar()` · `sources` · `add_source` · `remove_source` · `status(via)` with `sources` and `joined` |
| `base/onionmorph/onionmorph/server.py` | 266-300 · 1399-1420 · 1477-1479 | `build_app` wiring · `GET /api/automations` reads `X-Calendar-Via` · `/api/calendar-sources` · `POST /api/automations/{name:path}/cancel` (a held name, "/" included, reaches the refusal) |
| `base/onionmorph/onionmorph/om_cave.py` | 71-80 | `OMCave._init_automations`: the heart's registry |
| `base/onionmorph/onionmorph/woom_automations.py` | 56-232 | `DevdirAutomationLoader`: `guard_hot_reload`, `sync`, `_register` — `woom:<place>:<name>` entries mounted with their file |
| `base/onionmorph/onionmorph/woom_extension.py` | 137-175 | the loader's wiring at mount and at every watcher swap |
| `application/cave-teams/cave_teams/rpg/loading.py` | 177-209 | `read_cave_automations`: the top-level `*.json` of a place's `.cave/automations/` only |
| `base/onionmorph/onionmorph/skills/manage-the-calendar/SKILL.md` | whole | how an owner adds a source with curl |
| `base/onionmorph/app/src/components/panels/AutomationsPanel.tsx` · `base/onionmorph/app/src/components/CalendarSpace.tsx` · `base/onionmorph/onionmorph/web/automations.js` | the `cancel` handlers · the meta line | the 🗑 posts `/api/automations/<encodeURIComponent(name)>/cancel` · a failed job's meta line says `failed, exit <n>` |
| `application/healthworld/server/healthworld_agent.py` | `get_calendar` · `list_automations` · the sources methods | `source_types=("http",)`, `sources_joined(via)` |
| `application/healthworld/server/healthworld_server.py` | `GET /api/automations` · `/api/calendar-sources` | the header read; the sources routes |
| `application/healthworld/server/healthworld_automations.py` | 95-200 | `OwnJobsRegistry`: `fires_sources = False`, its own `get_due` and run record |
| `application/jobworld/avi-jw/server/jobworld_agent.py` · `kiki/server/jobworld_agent.py` | `get_calendar` · `list_automations` | read only (the owner's ruling: this work does not touch JobWorld): a `Calendar()` over a registry its heart does not fire, so the heart leaves it alone; its merge ignores the header |
| `application/cave/pyproject.toml` · `cave/__init__.py` · `cave/server/cave_http_server.py` · `cave/server/http_server.py` | version lines | 0.1.3 in four places |
| `application/cave/tests/test_calendar_tree.py` · `test_calendar_tree_review.py` · `base/onionmorph/onionmorph/tests/test_one_calendar.py` · `test_calendar_tree_review.py` | whole | the laws, and the cases each law must meet; run with `cave` and `onionmorph` both resolved to the checkout under test (`PYTHONPATH=<checkout>/application/cave:<checkout>/base/onionmorph`), or OM's venv answers with the main checkout's loader |
| `application/cave/DESIGN.md` · `base/onionmorph/DESIGN.md` §28.3 · `application/healthworld/DESIGN.md` (the calendar sources paragraph) | the calendar sections | what each states the code does |

## COHERENCE SET — when one of these changes, change the rest in the same commit

| when this changes | also change |
|---|---|
| a source's shape (`name`, `type`, `path`, `url`, `armed`) or `add_source`'s refusals | `_listed_sources` · `_hold` · `_join` · `DESIGN.md` §2 · OM's `/api/calendar-sources` · HealthWorld's sources methods · `manage-the-calendar/SKILL.md` · `test_calendar_tree.py` |
| the claim (`claim`, `release`, `CLAIM_LAPSE_S`, a distance, `wanted_by`, `clock_owner`, `_owner_alive`) | `tick_sources` · `_hold` · `own_held` and the heart's gate of own jobs · every loader that holds a calendar's folder (`woom_automations.py`, which takes no claim yet: cross-project-fixes' O69) · `DESIGN.md` §2 "Each job fires once" · the clock rows of THE PROOF |
| the runs record (`RUNS_FILE`, `_read_runs`, `_record_runs`, `_seed_clock`, `_carry_clock`) | `_meta`'s `.gitignore` · its place at the start of the beat, before any claim · `DESIGN.md` §2 · the takeover, handover, stop and edit tests |
| the heart's tick order or period, or `fire_due_automations` | `tick_sources`'s place before `get_due` · the registry check before it · `CLAIM_LAPSE_S` (three of the heart's ticks) · OM's `22-seq-calendar-and-heartbeat.md` · every job that can run longer than the lapse |
| how a held job is named, made or kept (`<chain>/<job>`, `_mount_state`, `mount`, `unmount`) | `ParseSpecLink`'s name check · `list_scheduled` and `own_entries` (only `_mount_state` is held from beneath) · `hot_reload` · `schema_path` · `save_schema` · `cancel` · the one-shot cleanups · `_NOT_CANCELLABLE` · OM's `{name:path}` cancel route and the panels' 🗑 · `depends_on` and `parallel` · OM's devdir loader |
| the joined view or an http answer's shape (`joined`, `sources_joined`, the entry fields) | `_listed` · OM's `status` · HealthWorld's `list_automations` · `AutomationsPanel.tsx` · `CalendarSpace.tsx` · `web/automations.js` · `manage-the-calendar/SKILL.md` |
| the `X-Calendar-Via` header or an id (`calendar_id`, `parse_via`) | every route that answers a calendar's jobs (OM's, HealthWorld's) · `fetch_calendar` · `DESIGN.md` §2 "An http calendar's wire" |
| `source_types` or `fires_sources` | the registries that set them (HealthWorld's) · `add_source` · `_hold` · `DESIGN.md` §2 · `test_calendar_tree.py` |
| a job's outcome (`_process`, `last_outcome`, `last_exit`, `keep_outcome`, Phase 1's exit read, the Phase 2 `running` mark) | `_carry_clock` · `hot_reload`'s update · `list_scheduled` · `_entry` · `_write_automation_failure` · the blockage · OM's three meta lines · `DESIGN.md` §1 "A job that starts a process" · the process tests |
| a job's args (`render_args`, `calendar_dir` set by `load_all`, `hot_reload`, `register`, `mount`) | `DESIGN.md` §1 · every job file that names a path by `${CALENDAR_DIR}` (`scalable-publishing/.cave/automations/absorber.json`) · the args tests |
| the telling (`record_outcome`, `Teller`, `tell.json`, `tellings.json`, `tells_failures`, `IGNORED`) | every site in `fire_due_automations` that reads an outcome goes through `record_outcome` (a test refuses any other) · every answer a delivery target gives when it delivered is in `TOLD` · `hot_reload`'s comparison holds `tells_failures` · `_running_processes` keeps what a telling needs · the time a telling can hold a beat (`GH_TIMEOUT_S`) · `_meta`'s `.gitignore` · `DESIGN.md` §1 "A failure is told to a person" and §2's `.calendar/` folder · every job file that tells its own failures (`scalable-publishing/.cave/automations/absorber.json`) · each calendar's `tell.json` · PROOF row 10 |
| the version | `pyproject.toml` · `cave/__init__.py` · both servers' `version` and `/health` · `CHANGELOG.md` · the board's VERSIONED column |
| any `CAVEAgent` subclass's `get_calendar` or registry | `DESIGN.md` §1 and §2 "Who stands on it" · THE PROOF's row 7 |
| any live proof | the board row · the changelog entry |

## THE CHANGE — a beat of the heart, end to end

```mermaid
sequenceDiagram
    autonumber
    participant HT as heart thread (anatomy.py)
    participant AG as CAVEAgent.fire_due_automations (cave_agent.py)
    participant CAL as Calendar (calendar.py)
    participant CK as claim / release (clock.json)
    participant RG as AutomationRegistry (automation.py)
    participant FD as a folder calendar (jobs, .calendar/)
    participant UI as OM route / HealthWorld route
    participant PE as a running app's calendar
    HT->>AG: cron_scheduler tick, every 60 s, ticks run in series
    AG->>AG: Phase 1 follows each process a job started: its Popen's poll() gives the exit code, nonzero = failed (written, a blockage, last_outcome and last_exit on the job)
    AG->>CAL: get_calendar(); tick_sources() only when its .registry is the heart's registry
    CAL->>FD: record runs.json of its own folder and of each folder it held at the last beat, before any claim
    CAL->>CK: claim(own folder, owner, 0) unless the registry's fires_sources is False → own_held (own jobs seeded from runs.json when handed back)
    CAL->>FD: _hold walks the folder sources only: read_sources, claim at depth, skip an id already on the way or already seen
    CK-->>CAL: True when it holds it, nobody does, or the holder lapsed or its process is gone; a holder asked by a nearer clock hands it over (False); a nearer clock finding a live holder asks (wanted_by, False)
    CAL->>FD: release what it held and no longer holds; read runs.json of each held folder
    CAL->>FD: glob *.json of each held folder, skip a file another loader holds; name := chain/job, depends_on and parallel prefixed
    CAL->>RG: unmount its own mounts no longer wanted · mount a job whose file or armed flag changed — its clock state carried, or an interval job seeded from runs.json; a model call dormant (schema and CronJob off) unless armed
    CAL->>FD: write runs.json when an interval job's last run moved
    AG->>RG: get_due() snapshot: every held job, and its own jobs only while own_held, whose CronJob is due
    AG->>RG: auto.fire() for each, depends_on read from the results by name; a returned Popen tracked as running, its pid followed; one-shot file found through schema_path before unregister
    UI->>CAL: GET /api/automations with X-Calendar-Via → status(via) / list_automations(via) → joined(via)
    CAL->>CAL: joined: own_entries + sources_joined; a calendar whose id is in via answers one loop entry
    CAL->>FD: _join, folder source: AutomationRegistry(store).load_all, tag each job with the chain, recurse into its sources
    CAL->>PE: _join, http source: fetch_calendar(url, via + own id) over http or https, redirects checked, 5 s, 1 MB
    PE-->>CAL: a list, or an object holding one under joined / automations / scheduled
    CAL-->>UI: every job beneath, tagged calendar (the chain of source names) and source (the first of them), or one status entry per source that cannot be read
```

## THE PROOF — measure every store before and after, on folders and servers of your own

| store | measure | pass |
|---|---|---|
| 1. `<folder>/.calendar/clock.json`, `runs.json` and its `.gitignore` | `cat` them through the beats of two Calendars (over different registries) that list one folder at distances 2 and 1, the far one beating first · through the beats of a parent holding a folder whose own clock then starts · after a clock's process is gone · after a held job fires and the next beat runs · `cat .calendar/.gitignore` · the same with a calendar whose registry has `fires_sources` False | after the first beat `owner` is `<machine>:<pid>:<id>`, `distance` how far above, `beat` the time; the nearer clock's beat adds `wanted_by` and holds nothing; the holder's next beat hands it over (`owner` the nearer clock) and unmounts; the nearer clock holds it from its next beat; in no beat is a job due in two registries, and the job fired once over all beats; a gone process's claim is taken at once; `runs.json` holds the job's last run; `.gitignore` holds every name of `IGNORED` (`clock.json`, `runs.json`, `tellings.json` and its `.tmp` and `.unreadable` files), a hand-written one keeping its lines; the `fires_sources` False calendar writes no file anywhere |
| 2. `<folder>/.calendar/sources.json` (or an app's sources file) | `cat` it after `add_source` and `remove_source` · `read_cave_automations(<folder>)` over a folder that holds a `.calendar/` | the file holds `{"sources": [...]}` with the added source and none after the remove; a name with "/", a kind the calendar does not list, a dir with no path and a url that is not http or https are refused with `ValueError`; the devdir read returns only the top-level `*.json` jobs |
| 3. `AutomationRegistry.automations` and `.mounted` | print `sorted(reg.mounted)` and `[a.name for a in reg.get_due()]` before and after `tick_sources` · after `hot_reload` · with OM's devdir loader and a dir source over the same folder · with a job whose `depends_on` names a job of its own calendar · after an edit of a held interval job's file · after a clock takes over a folder | each job file is held once; `hot_reload` keeps every held job; a job whose dependency is in its own calendar fires after it; an edited or taken-over interval job is not due before its interval; an event job from an unarmed folder does not fire on its event; `list_scheduled` gives a held job its `calendar` |
| 4. a child folder's job files | the file before and after `save_schema` and `cancel` of a held job, `Calendar.schedule` of a name with "/", and a one-shot's fire · `git -C <the folder's project> status --short` | `save_schema` raises and `cancel` returns False, the file unchanged; `schedule` answers an error; a one-shot removes only its own file; the project's `git status` shows only `.calendar/` |
| 5. the outgoing GET and its header | a local test server that records `(path, X-Calendar-Via)` for each request · one that redirects to `ftp:` · one that answers slowly a byte at a time · one that answers over 1 MB · an app that lists its caller | the header is the ids of the calendars above, and the path is the url as listed; a redirect away from http or https, a slow or large answer and a missing app each end as one entry with a `status`; a loop through apps ends as one `loop` entry |
| 6. the `/api/automations` answer | `GET` on a test app of your own, with and without the header · `POST /api/automations/<encoded key>/cancel` for a held job | the answer holds `scheduled`, `sources` and `joined` (HealthWorld: `automations`); with the calendar's own id in the header `joined` is one `loop` entry; the cancel of a held job answers the refusal and the file stays |
| 7. every `CAVEAgent` subclass | for each subclass in RETRIEVE: is `agent.get_calendar().registry` the agent's `automation_registry`? Then a stand-in heart over a source folder, through `fire_due_automations` | where it is (OM, HealthWorld, PromptWorld, WakingDreamer, cave-teams, `AppCAVEAgent`, twi-jobworld): the folder's job ran once, in the heart's registry; where it is not (JobWorld's avi and kiki): nothing claimed, mounted or written, and a calendar that lists the folder takes it |
| 8. the version | `grep -rn '0.1.3' pyproject.toml cave/__init__.py cave/server/cave_http_server.py cave/server/http_server.py` · `publish_package.sh application/cave --dry-run` | the same version in all four files; the dry run builds `cave_harness-0.1.3` and checks it |
| 9. a job's outcome — the job object, `<data_dir>/automation_failures/`, the blockage store | a held job whose `subprocess.Popen` exits 3, one that exits 0, and one re-made while its process runs, each over two beats of a stand-in heart with its own data folder and blockage file · its `list_scheduled` and `sources_joined` entries · `ls automation_failures/` | the first beat marks it `running`; the beat after the exit gives `failed`, exit 3 (or `success`, exit 0) on the job and in both listings; one report, named `<chain>__<job>_<time>.json`, and one blockage for the failure, none for the success; the re-made job reports its process's exit |
| 10. the telling — `<job's folder>/.calendar/tellings.json`, the target, the blockage store | `CAVEAgent.record_outcome` on a stand-in heart, its calendar's `tell.json` naming a file router, then an issue target over a fake `gh`: two failures and two successes · a job with `tells_failures` · a calendar naming none · a target that refuses, then answers · a held job whose process exits 3, over two beats, its own folder naming the teller and the parent another · a `log` target over three failures and a success · a record the file cannot keep, then a new process · an unreadable `tellings.json` · `hot_reload` after `tells_failures` flips · a job gone from the registry before its process ends · a one-shot · a parallel job answering error · an in-process run left awaiting input · a hand-written `.gitignore` · a telling in a folder no clock claimed · a job whose file now says `tells_failures` after a told run · `pytest tests/test_job_failure_telling.py` and its twenty-four mutants | told once at the first failure and once at the first success, `tellings.json` `{}` after; one issue `JOB FAILED: <job>` labelled `job-failed`, closed with a comment; a refused telling not recorded and told at the next failure; the job that tells itself and the calendar naming none record a blockage and deliver nothing; the held job told by its own folder's teller, the parent's untouched; `log` written twice, not at every beat; one issue across a lost record (memory, then the open issue's title); the unreadable file kept as `tellings.json.unreadable`; `hot_reload` lists the job `updated`; the gone job told by the calendar its process kept; the one-shot's record `{}` after; the parallel error and the awaiting run told `failed`; the hand-written file's comment line kept whole; the unclaimed folder's `.gitignore` written; the told run cleared though the job now tells itself; every mutant caught |

⛔ `pytest application/cave/tests` green proves the calendars, the registries and the heart's firing pass over a stand-in
agent; no test builds a real `CAVEAgent` subclass or runs a daemon, so a live run on a daemon of your own is the evidence
for row 7.
