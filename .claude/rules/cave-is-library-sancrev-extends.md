# CAVE Is Library, Sancrev Extends — NUCLEAR NON-NEGOTIABLE

## The Problem

Agent tried to put sancrev-specific routes (GEAR, PAIAB, SANCTUM, messaging, conductor, automations, persona, agent registry) INTO CAVEHTTPServer. Isaac: "why the fuck would CAVEHTTPSERVER **EVER** HAVE SANCREV PARTS? FUCK YOU."

## The Rule

**CAVEHTTPServer = PURE CAVE LIBRARY.** It has ONLY generic CAVE routes (health, config, loops, DNA, modules, hooks, omnisanc, metabrainhook, PAIA mode, live mirror, inbox, remote agents, SSE).

**Sancrev EXTENDS CAVEHTTPServer.** A sancrev-specific server class (e.g. `SancrevHTTPServer` or `WakingDreamerHTTPServer`) inherits from or wraps CAVEHTTPServer and adds sancrev-domain routes on top.

## The Architecture

```
CAVEHTTPServer (CAVE library — generic, reusable)
       ↑ extends
SancrevHTTPServer (sancrev implementation — domain-specific)
       ↑ uses
WakingDreamer(CAVEAgent) (the god object, passed IN)
```

Entry point:
```python
wd = WakingDreamer()
server = SancrevHTTPServer(cave=wd, port=8080)
uvicorn.run(server.app)
```

## NEVER

- NEVER put sancrev routes in CAVEHTTPServer
- NEVER put GEAR, PAIAB, SANCTUM, messaging, conductor, persona, agent registry routes in CAVE
- CAVE is a LIBRARY. It knows NOTHING about sancrev, sanctum, GEAR, PAIAB, etc.
- Sancrev-specific code lives in sancrev, not in CAVE
