# 21 — THE ARCHITECTURE MAP (CAVE, drawn from its DESIGN.md)

<docsys kind="arch-map" role="instance"/>

TRIGGER:[CAVE's `DESIGN.md` gains, loses or renames a part (⇒ redraw this stack the same commit) · a new dev flow in
CAVE (⇒ place it on the box it runs through) · about to reason about where the calendar or the heart sits]
DO:[draw only what `DESIGN.md` names · end each external system at its seam]
NOT:[draw the parts of CAVE `DESIGN.md` has not read in yet (they are in `ARCHITECTURE.md` and `CAVEAGENT_DESIGN.md`)]

## THE STACK — the calendar and the calendar tree

```mermaid
flowchart TB
  classDef app fill:#ede7f6,stroke:#4527a0;
  classDef core fill:#e3f2fd,stroke:#1565c0;
  classDef store fill:#e8f5e9,stroke:#2e7d32;
  classDef dep fill:#fff8e1,stroke:#ff8f00,stroke-dasharray:4 3;

  subgraph APPS["THE APPLICATIONS — CAVEAgent subclasses (§0)"]
    OM["OM's daemon — its calendar is this one; its heart fires the folders beneath it"]:::app
    HW["HealthWorld — joins running apps' calendars; its registry fires only its own jobs"]:::app
    JW["JobWorld — outside it: keeps its own merge; answers as a source in the untagged shape"]:::app
  end
  subgraph CAVE["CAVE — the library"]
    AGENT["CAVEAgent — get_calendar() · the heart: cron_scheduler every 60 s → fire_due_automations, ticking only a calendar over the registry it fires · hot reload every 300 s (§1, §2)"]:::core
    CAL["Calendar — compile a spec · list · view · cancel (§1) · sources · joined · sources_joined · tick_sources (§2)"]:::core
    CLAIM["the clock's claim — claim · release: its own clock, else the nearest above (§2)"]:::core
    REG["AutomationRegistry — its own jobs · the jobs it holds for calendars beneath (mount) · fires_sources (§1, §2)"]:::core
    FETCH["fetch_calendar — http/https only, redirects checked, 5 s, 1 MB, X-Calendar-Via (§2)"]:::core
    TELL["the teller — record_outcome · Teller: every outcome the heart reads recorded once; a run of failures told at its first failure and its first success, through the job's own calendar's tell.json (a delivery target, or issue:<owner>/<repo>), never for a job that tells_failures (§1)"]:::core
    FLOW["22-seq-calendar-tree — a beat of the heart holds and fires each job once; a parent lists an http source with the header (§2)"]:::core
  end
  subgraph STORES["A CALENDAR'S FOLDER — any folder of job files (§2)"]
    JOBS["<name>.json — one job each (AutomationSchema)"]:::store
    META[".calendar/ — sources.json · clock.json · runs.json · tell.json (where its failures are told) · tellings.json · .gitignore"]:::store
  end
  subgraph DEPS["EXTERNAL — their internals are not ours"]
    SDNA["SDNA · SEAM: CronJob (is_due, mark_run) and the chain ontology the Calendar compiles with"]:::dep
    CRON["croniter · SEAM: a cron expression's next time"]:::dep
    PEER["a running app's calendar · SEAM: GET <url> with X-Calendar-Via → a list of jobs"]:::dep
    GH["GitHub · SEAM: an issue opened, read by its number, commented on and closed through gh's stored login"]:::dep
  end

  OM --> AGENT
  HW --> AGENT
  JW -.->|"listed as a source over http"| FETCH
  AGENT --> CAL
  CAL --> REG
  CAL --> CLAIM
  CAL --> FETCH
  REG --> JOBS
  CAL --> META
  CLAIM --> META
  REG --> SDNA
  CAL --> CRON
  FETCH --> PEER
  AGENT --> TELL
  TELL --> META
  TELL -->|"issue:"| GH
  FLOW -.-> TELL
  FLOW -.-> AGENT
  FLOW -.-> CAL
  FLOW -.-> CLAIM
  FLOW -.-> FETCH
```
