# CAVE — Code Agent Virtualization Environment

<!-- SCALABLE-PUBLISHING:AUTOGEN START (managed block — do not edit between these markers) -->

![License](https://img.shields.io/badge/license-Other-blue.svg) ![Stars](https://img.shields.io/github/stars/sancovp/cave.svg?style=social) ![Updated](https://img.shields.io/badge/updated-2026_07_08-lightgrey.svg)

⭐ 0 stars • 🕑 Updated 2026-07-08

[Marketplace](https://github.com/sancovp/sancrev-marketplace) • [Docs](https://sancovp.github.io/aisaac/)

📦 Auto-published from the monorepo • [CHANGELOG](./CHANGELOG.md) • [sancovp/cave](https://github.com/sancovp/cave)

<!-- SCALABLE-PUBLISHING:AUTOGEN END -->

**Package:** `cave-harness`

CAVE virtualizes any terminal-based code agent (e.g. Claude Code) behind an HTTP server, so it can be
driven, observed, and orchestrated as a service instead of an interactive terminal. It is the agent
runtime that PromptWorld and the other *Worlds are built on.

## What it gives you

- **An HTTP server around a code agent** — start a long-lived agent process and talk to it over HTTP
  instead of a TTY: inject prompts, stream output, and run it inside a loop.
- **A hook harness** — a registry + dispatch layer for Claude Code hooks (session-start / per-turn /
  stop), so behavior can be layered onto the agent from outside.
- **Loop infrastructure** — the autopoiesis / guru loops that keep an agent working across turns.

## Install

```bash
pip install cave-harness
```

Optional extras:

```bash
pip install "cave-harness[sdna]"   # + sanctuary-dna integration
pip install "cave-harness[dev]"    # + pytest / pytest-asyncio
```

## Run the server

```bash
cave-server
```

This launches the HTTP server (`cave.server.http_server:run_server`, FastAPI + uvicorn). Point your
client at it to register hooks, inject prompts, and drive the virtualized agent.

## Where it sits

CAVE is the **runtime** layer of the SANCREV / GNOSYS stack: the *Worlds (PromptWorld, …) compile their
agents and run them on top of the CAVE harness. See the ecosystem docs for the full picture.

## Docs

Full documentation and the ecosystem map: **https://sancovp.github.io/aisaac/**

## License

GPBL-1.0 — see `LICENSE`.
