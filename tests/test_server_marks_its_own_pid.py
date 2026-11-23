"""A cave server marks the process that serves it, so a hook inside it never hops to it over HTTP.

A hook that posts to CAVE_URL from inside the server CAVE_URL names waits on the event loop it is blocking: every hop
times out (three seconds each, at every tool call of every agent). The server writes its pid into CAVE_SELF_PID when
it starts serving; the hook reads it and makes no hop when the pid is its own.

    python3 application/cave/tests/test_server_marks_its_own_pid.py      (exit 0 = pass)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import uvicorn
    from cave.server.cave_http_server import CAVEHTTPServer

    seen = {}

    def fake_run(app, host=None, port=None):
        seen["pid"] = os.environ.get("CAVE_SELF_PID")

    os.environ.pop("CAVE_SELF_PID", None)
    real, uvicorn.run = uvicorn.run, fake_run
    try:
        server = CAVEHTTPServer.__new__(CAVEHTTPServer)
        server.app, server.host, server.port = object(), "127.0.0.1", 0
        server.run()
    finally:
        uvicorn.run = real
    ok = seen.get("pid") == str(os.getpid())
    print(("PASS" if ok else "FAIL"), "CAVE_SELF_PID at serve time:", seen.get("pid"), "this pid:", os.getpid())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
