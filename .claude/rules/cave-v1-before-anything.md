# CAVE v1 Before ANYTHING — NUCLEAR NON-NEGOTIABLE

## What Happened

Agent moved on to Observatory SDNA refactor while CAVE v1 was NOT DONE. The old sancrev monolith http_server.py (2548 lines) is STILL the running server. CAVEHTTPServer exists but is NOT wired as the actual entry point. Task #92 (migrate all routes) is PENDING.

## The Rule

**CAVE v1 must be FULLY COMPLETE before touching Observatory, Autobiographer, or any other system.**

CAVE v1 is complete when:
1. CAVEHTTPServer IS the running server (not the old monolith)
2. ALL ~60 routes from old http_server.py exist on CAVEHTTPServer
3. start_sancrev.sh uses WakingDreamer + CAVEHTTPServer entry point
4. The old http_server.py is DEPRECATED and not running

## Why

Isaac said "we were not to move on to observatory until cave v1 is done." Agent ignored this.
