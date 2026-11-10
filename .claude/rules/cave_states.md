# cave — TASKS

<docsys kind="states" role="instance"/>

TRIGGER:[work in `application/cave`] · N tables, one per WORKFLOW TYPE · prose → `../../DESIGN.md`

## THE RELEASE LINE

Every feature of CAVE goes through the release line (cross-project-fixes' `22-seq-release-a-feature.md`):
**DESIGNED** (`DESIGN.md` states it) → **BUILT** (the code does it, its tests pass) → **PROVEN** (the release proof:
`publish_package.sh --dry-run`) → **VERSIONED** (the version raised in the change) → **RELEASED** (on PyPI as
`cave-harness` and in `sancovp/cave`) → **SHOWN** (its showcase row). One `●` per row, moved.

| feature | DESIGNED | BUILT | PROVEN | VERSIONED | RELEASED | SHOWN |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| the calendar tree — every calendar the parent of any other (DESIGN §2) |  |  |  |  | ● |  |
| a job file names no path of its machine: `${CALENDAR_DIR}` and `${PYTHON}` in its args (DESIGN §1) |  |  |  | ● |  |  |
| a job that starts a process is followed to its end: its exit code is its outcome, shown in every listing (DESIGN §1) |  |  |  | ● |  |  |
| OM's devdir loader takes the claim for each folder it holds (DESIGN §2, ASPIRATIONAL) | ● |  |  |  |  |  |
| an application whose registry fires only its own jobs claims its folder without writing into it (DESIGN §2, ASPIRATIONAL) | ● |  |  |  |  |  |
