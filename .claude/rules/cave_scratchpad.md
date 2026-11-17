# cave_scratchpad — its law is `~/.claude/rules/the-host-aios-scratchpad.md` (HOW EVERY SCRATCHPAD WORKS): one line per ref, edited with the Edit tool, never over 20KB

## THE REFS

- WHEN CAVE's relays, or Codex's or Claude Code's hooks into CAVE, are next touched → fold `cave.relays` (`paia.py`,
  `loop_probe.py`) and `cave.core.hooks`' provider hook types from the outside clone of `sancovp/cave` at
  `~/Documents/New project/cave` (commit `79d4ed6`, the owner's leave given to read it) into this project by a union port,
  zero deletes, the clone's other work diffed against this one by blob first; make the relay load without the whole
  `cave` package (importing it costs about 7 CPU-seconds per hook run), its wait 5 seconds, a hard stop on the whole run,
  each with a test failing without it; then, on the owner's go, regenerate Codex's ten launchers in `~/.codex/hooks/`
  from this copy and stop anything running the clone. Until then those launchers carry a guard written by hand: CAVE's
  port tried first (nothing listening → exit 0 at once), a 5-second wait, a hard stop at 15 seconds; their originals and
  both checksums are in this session's scratch folder `codex-hooks-backup/`, the proof in `codex-hook-proof.txt` beside
  it · ✅ MEASURED 2026-11-16
- WHEN Codex works in `~/Documents/New project` → that folder's own `.codex/hooks.json` registers the same ten relays a
  second time (Codex's `config.toml` lists both sets), so each event there may start two; out of bounds, the owner's to
  clear · ✅ MEASURED 2026-11-16
- WHEN the fold of SILAS's CAVE is begun → what it holds, read whole by blob against `main`'s history: nine commits of
  June 21 on the branch `codex/silas-aios-cave-harness`, pushed to the public `sancovp/cave` as that side branch (the
  publisher mirrors `master` only, so a publish wipes none of it), on a June base whose 78 files are all blobs of ours; 35
  files changed, 5,224 lines added, every one SILAS-only — the relays, the AIOS bridge (`core/aios.py`, `mixins/aios.py`),
  cognition (`core/cognition.py`, `mixins/cognition.py`, `mcp/cognition_mcp.py`), six SILAS loops (`loops/silas_*`), six
  test files — and a 58-line change to `core/aios.py` and its test never committed, on that machine only; 9 of the files
  it changed this project changed too since (`__init__.py` · `core/cave_agent.py` · `core/config.py` · `core/hooks.py` ·
  `mixins/anatomy.py` · `mixins/hook_router.py` · `server/cave_http_server.py` · `server/http_server.py` ·
  `pyproject.toml`, 36 commits of ours since June 20), so the fold is a three-way merge, never a copy; no secret in its
  added lines · ✅ MEASURED 2026-11-16

