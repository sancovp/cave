"""Bounded probe loop for verifying provider relays against a CAVE server."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .paia import DEFAULT_CAVE_URL, call_cave


DEFAULT_EVENT = "UserPromptSubmit"


def run_probe_loop(
    *,
    event: str = DEFAULT_EVENT,
    provider: str = "codex",
    cave_url: str = DEFAULT_CAVE_URL,
    iterations: int = 5,
    delay: float = 1.0,
    forever: bool = False,
    output_path: str | Path | None = None,
    call: Callable[..., Mapping[str, Any]] = call_cave,
) -> list[dict[str, Any]]:
    """Send synthetic hook pulses to CAVE and record what came back.

    The default is deliberately bounded. Use ``forever=True`` only when an
    external process supervisor is expected to own shutdown.
    """
    if iterations < 1 and not forever:
        raise ValueError("iterations must be >= 1 unless forever=True")
    if delay < 0:
        raise ValueError("delay must be >= 0")

    path = Path(output_path) if output_path else None
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    index = 0
    while forever or index < iterations:
        payload = {
            "source": provider,
            "hook_event_name": event,
            "prompt": f"SILAS loop probe pulse {index + 1}",
            "loop_probe": {
                "iteration": index + 1,
                "forever": forever,
            },
        }
        response = dict(call(event, payload, cave_url=cave_url))
        record = {
            "iteration": index + 1,
            "event": event,
            "provider": provider,
            "cave_url": cave_url,
            "response": response,
            "ts": time.time(),
        }
        records.append(record)
        if path:
            with path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")

        index += 1
        if forever or index < iterations:
            time.sleep(delay)

    return records


def cli_main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Probe CAVE hook connectivity in a guarded loop.")
    parser.add_argument("--event", default=DEFAULT_EVENT)
    parser.add_argument("--provider", default="codex")
    parser.add_argument("--cave-url", default=DEFAULT_CAVE_URL)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--forever", action="store_true")
    parser.add_argument("--output", default=None, help="Optional JSONL path for probe records.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    records = run_probe_loop(
        event=args.event,
        provider=args.provider,
        cave_url=args.cave_url,
        iterations=args.iterations,
        delay=args.delay,
        forever=args.forever,
        output_path=args.output,
    )
    sys.stdout.write(json.dumps({"records": records}, indent=2) + "\n")


if __name__ == "__main__":
    cli_main()
