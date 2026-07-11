# Route Migration Rule — NUCLEAR NON-NEGOTIABLE

## What Happened

Agent created cave_http_server.py with only ~30 CAVE-core routes and LEFT OUT all sanctuary-revolution routes (/sanctum/*, /gear/*, /paiab/*, /messages/send, /event, /automations/*, /persona/*, etc). This broke Conductor Discord notifications, message processing, sanctum ritual completion, gear system, paiab builder — EVERYTHING that was working.

## The Rule

The old http_server.py at /tmp/sanctuary-revolution/sanctuary_revolution/harness/server/http_server.py has 2521 lines with ~60+ routes. EVERY SINGLE ROUTE must exist on cave_http_server.py. Each route calls ONE method on self.cave (CAVEAgent/WakingDreamer).

## The Architecture

```
CAVEAgent = GOD OBJECT. Knows everything. Everything programmable from one context.
CAVEHTTPServer = THIN SKIN. Every route = one method call on self.cave.
```

The inline logic from old routes becomes METHODS on CAVEAgent (or its mixins). Routes are one-liners.

## How To Do It

1. Read ENTIRE old http_server.py (2521 lines)
2. List every route
3. For each route: move inline logic to a CAVEAgent method
4. In cave_http_server.py: add route that calls self.cave.method()
5. Test that every route works

## NEVER AGAIN

- NEVER create a "new server" that drops existing routes
- NEVER assume routes are "old code" that can be skipped
- EVERY route is a capability. Dropping a route = dropping a capability.
- The server should GAIN routes, never LOSE them
