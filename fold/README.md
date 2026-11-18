# The fold's input — removed by the fold itself, never merged to main

`silas-uncommitted.patch` is the one change of the outside CAVE work that was never committed: 58 added lines to its
`cave/core/aios.py` and `tests/test_aios_bridge.py`, taken by `git diff` from the clone where it was written, on top of
that clone's branch `codex/silas-aios-cave-harness` at `51156a5` (on `sancovp/cave`). The fold applies it to that
branch's files as it merges them into this CAVE, then removes this folder before its pull request.
