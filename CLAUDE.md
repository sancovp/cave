# CAVE — the agent runtime (the `cave-harness` package)

This folder is CAVE: the `CAVEAgent` base class an application subclasses to become a running agent, its heart, its
automations and calendar, and its generic HTTP server. Its design is [`DESIGN.md`](DESIGN.md) — what CAVE is and ends
as (§0), the calendar (§1) and the calendar tree, where every calendar can be the parent of any other (§2); the rest of
its design is held in [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`CAVEAGENT_DESIGN.md`](CAVEAGENT_DESIGN.md) until it is
read into `DESIGN.md`. Its dev flow for the calendar tree is [`.claude/rules/22-seq-calendar-tree.md`](.claude/rules/22-seq-calendar-tree.md). Its board is [`.claude/rules/cave_states.md`](.claude/rules/cave_states.md), its stack
[`.claude/rules/21-architecture-diagrams.md`](.claude/rules/21-architecture-diagrams.md), its history
[`CHANGELOG.md`](CHANGELOG.md). Tests: `tests/` (`test_calendar_tree.py` holds the calendar tree's laws), run with a
Python that resolves `cave` to this folder (`find_spec("cave").origin`).
