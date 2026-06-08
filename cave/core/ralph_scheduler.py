"""Ralph Scheduler — EventSource that dispatches ralph jobs from a queue dir.

Queue dir: $HEAVEN_DATA_DIR/ralph_scheduler/
  pending/   — JSON job files waiting to run
  running/   — currently executing (max 1)
  done/      — completed jobs
  failed/    — failed jobs

Job JSON format:
{
    "id": "ralph_20260508_143022",
    "repo": "/home/GOD/gnosys-plugin-v2",
    "code_target": "add_concept_tool_func",
    "requirements": "/tmp/reqs.md",
    "n_runs": 8,
    "priority": 0,
    "submitted_at": "2026-05-08T14:30:22",
    "submitted_by": "gnosys",
    "status": "pending"
}

Usage as EventSource (add to any CAVEAgent's World):
    from cave.core.ralph_scheduler import RalphSchedulerSource
    world.add_source(RalphSchedulerSource())

Usage standalone (CLI):
    python -m cave.core.ralph_scheduler submit <repo> <code_target> <requirements> [--n-runs 8]
    python -m cave.core.ralph_scheduler list [pending|running|done|failed]
    python -m cave.core.ralph_scheduler process
    python -m cave.core.ralph_scheduler daemon --interval 30
"""
import json
import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cave.core.world import EventSource, WorldEvent

logger = logging.getLogger(__name__)

HEAVEN_DATA = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
QUEUE_DIR = HEAVEN_DATA / "ralph_scheduler"
RALPH_SCRIPT = Path("/tmp/compoctopus_repo/scripts/run_ralph.sh")


@dataclass
class RalphJob:
    """A ralph dispatch job."""
    id: str
    repo: str
    code_target: str
    requirements: str
    n_runs: int = 8
    priority: int = 0
    submitted_at: str = ""
    submitted_by: str = "unknown"
    status: str = "pending"
    every: Optional[str] = None       # cron syntax e.g. "0 3 * * *", None = one-shot
    not_before: Optional[str] = None  # ISO timestamp, skip until this time
    pid: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    run_count: int = 0                # how many times this recurring job has run
    agent_config: Optional[Dict[str, Any]] = None  # HermesConfig overrides per-run

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_file(cls, path: Path) -> "RalphJob":
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _ensure_dirs():
    for sub in ("pending", "running", "done", "failed"):
        (QUEUE_DIR / sub).mkdir(parents=True, exist_ok=True)


def submit_job(
    repo: str,
    code_target: str,
    requirements: str,
    n_runs: int = 8,
    priority: int = 0,
    submitted_by: str = "unknown",
    every: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Submit a ralph job to the queue. Returns job ID.

    Args:
        every: Cron syntax string for recurring jobs (e.g. "0 3 * * *").
               None = one-shot job.
        agent_config: HermesConfig overrides (model, mcp_servers, tools, etc.)
    """
    _ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"ralph_{ts}"
    job = RalphJob(
        id=job_id,
        repo=repo,
        code_target=code_target,
        requirements=requirements,
        n_runs=n_runs,
        priority=priority,
        submitted_at=datetime.now().isoformat(),
        submitted_by=submitted_by,
        every=every,
        agent_config=agent_config,
    )
    (QUEUE_DIR / "pending" / f"{job_id}.json").write_text(job.to_json())
    kind = f"recurring ({every})" if every else "one-shot"
    logger.info("Ralph job submitted: %s %s (repo=%s, target=%s)", job_id, kind, repo, code_target)
    return job_id


def list_jobs(status: str = "pending") -> List[RalphJob]:
    """List jobs by status."""
    _ensure_dirs()
    jobs = []
    for f in sorted((QUEUE_DIR / status).glob("*.json")):
        try:
            jobs.append(RalphJob.from_file(f))
        except Exception as e:
            logger.warning("Bad job file %s: %s", f, e)
    return jobs


def _pick_next() -> Optional[Path]:
    """Pick highest priority (then oldest) pending job, skipping not-yet-ready."""
    _ensure_dirs()
    now = datetime.now()
    ready = []
    for p in (QUEUE_DIR / "pending").glob("*.json"):
        try:
            data = json.loads(p.read_text())
            nb = data.get("not_before")
            if nb and datetime.fromisoformat(nb) > now:
                continue  # not ready yet
            ready.append((p, data))
        except Exception:
            continue
    if not ready:
        return None
    ready.sort(key=lambda x: (-x[1].get("priority", 0), x[0].name))
    return ready[0][0]


def _is_running() -> Optional[RalphJob]:
    """Check if a job is currently running."""
    files = list((QUEUE_DIR / "running").glob("*.json"))
    if not files:
        return None
    return RalphJob.from_file(files[0])


def _move_job(job: RalphJob, src_dir: str, dest_dir: str):
    """Move a job file between queue subdirs."""
    src = QUEUE_DIR / src_dir / f"{job.id}.json"
    dest = QUEUE_DIR / dest_dir / f"{job.id}.json"
    dest.write_text(job.to_json())
    if src.exists():
        src.unlink()


def _check_running() -> Optional[WorldEvent]:
    """Check if running job has finished."""
    files = list((QUEUE_DIR / "running").glob("*.json"))
    if not files:
        return None

    job = RalphJob.from_file(files[0])
    if not job.pid:
        job.status = "failed"
        job.error = "No PID recorded"
        job.finished_at = datetime.now().isoformat()
        _move_job(job, "running", "failed")
        return WorldEvent(source="ralph_scheduler", content=f"Ralph job {job.id} failed: no PID",
                         priority=3, metadata={"job_id": job.id, "event": "failed"})

    # Check if process still alive
    try:
        os.kill(job.pid, 0)
        return None  # still running
    except ProcessLookupError:
        pass  # finished
    except PermissionError:
        return None  # still running

    # Process done
    job.finished_at = datetime.now().isoformat()
    job.run_count += 1

    if job.every:
        # Recurring — requeue with next cron fire time
        from croniter import croniter
        cron = croniter(job.every, datetime.now())
        next_fire = cron.get_next(datetime)
        job.status = "pending"
        job.not_before = next_fire.isoformat()
        job.pid = None
        job.started_at = None
        job.finished_at = None
        job.result = None
        _move_job(job, "running", "pending")
        logger.info("Ralph job %s completed run #%d, next at %s", job.id, job.run_count, job.not_before)
        return WorldEvent(source="ralph_scheduler",
                         content=f"Ralph job {job.id} completed (run #{job.run_count}), next: {next_fire.strftime('%Y-%m-%d %H:%M')}",
                         priority=5, metadata={"job_id": job.id, "event": "recurring_complete", "next": job.not_before})
    else:
        # One-shot — move to done
        job.status = "done"
        job.result = "completed"
        _move_job(job, "running", "done")
        logger.info("Ralph job %s completed (pid=%s)", job.id, job.pid)
        return WorldEvent(source="ralph_scheduler", content=f"Ralph job {job.id} completed",
                         priority=5, metadata={"job_id": job.id, "event": "completed"})


def _dispatch_next() -> Optional[WorldEvent]:
    """Dispatch next pending job."""
    next_file = _pick_next()
    if not next_file:
        return None

    job = RalphJob.from_file(next_file)

    # Validate repo
    if not Path(job.repo).is_dir():
        job.status = "failed"
        job.error = f"Repo not found: {job.repo}"
        job.finished_at = datetime.now().isoformat()
        _move_job(job, "pending", "failed")
        return WorldEvent(source="ralph_scheduler", content=f"Ralph job {job.id} failed: repo not found",
                         priority=3, metadata={"job_id": job.id, "event": "failed"})

    # Validate requirements doc
    if not Path(job.requirements).is_file():
        job.status = "failed"
        job.error = f"Requirements not found: {job.requirements}"
        job.finished_at = datetime.now().isoformat()
        _move_job(job, "pending", "failed")
        return WorldEvent(source="ralph_scheduler", content=f"Ralph job {job.id} failed: reqs not found",
                         priority=3, metadata={"job_id": job.id, "event": "failed"})

    # Launch ralph
    cmd = ["bash", str(RALPH_SCRIPT), job.repo, job.code_target, job.requirements, str(job.n_runs)]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        job.pid = proc.pid
        job.status = "running"
        job.started_at = datetime.now().isoformat()
        _move_job(job, "pending", "running")
        logger.info("Ralph job %s dispatched (pid=%s, target=%s)", job.id, proc.pid, job.code_target)
        return WorldEvent(source="ralph_scheduler", content=f"Ralph job {job.id} started: {job.code_target} in {job.repo}",
                         priority=5, metadata={"job_id": job.id, "pid": proc.pid, "event": "started"})
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.now().isoformat()
        _move_job(job, "pending", "failed")
        logger.error("Ralph job %s failed to launch: %s", job.id, e)
        return WorldEvent(source="ralph_scheduler", content=f"Ralph job {job.id} failed: {e}",
                         priority=3, metadata={"job_id": job.id, "event": "failed"})


class RalphSchedulerSource(EventSource):
    """EventSource that dispatches ralph jobs from queue dir.

    On each tick:
    1. If a job is running, check if it finished
    2. If no job running, dispatch next pending job
    """

    def __init__(self, enabled: bool = True):
        super().__init__(name="ralph_scheduler", enabled=enabled)
        _ensure_dirs()

    def poll(self, current_time: float) -> List[WorldEvent]:
        events = []
        event = _check_running()
        if event:
            events.append(event)
        if not _is_running():
            event = _dispatch_next()
            if event:
                events.append(event)
        return events

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "pending": len(list_jobs("pending")),
            "running": len(list_jobs("running")),
            "done": len(list_jobs("done")),
            "failed": len(list_jobs("failed")),
        }


# --- CLI ---

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Ralph Scheduler")
    sub = parser.add_subparsers(dest="command")

    p_sub = sub.add_parser("submit")
    p_sub.add_argument("repo")
    p_sub.add_argument("code_target")
    p_sub.add_argument("requirements")
    p_sub.add_argument("--n-runs", type=int, default=8)
    p_sub.add_argument("--priority", type=int, default=0)
    p_sub.add_argument("--by", default="cli")
    p_sub.add_argument("--every", default=None, help="Cron syntax for recurring (e.g. '0 3 * * *')")

    p_list = sub.add_parser("list")
    p_list.add_argument("status", nargs="?", default="pending",
                        choices=["pending", "running", "done", "failed", "all"])

    sub.add_parser("process")

    p_daemon = sub.add_parser("daemon")
    p_daemon.add_argument("--interval", type=int, default=30)

    sub.add_parser("status")

    args = parser.parse_args()

    if args.command == "submit":
        job_id = submit_job(args.repo, args.code_target, args.requirements,
                           n_runs=args.n_runs, priority=args.priority, submitted_by=args.by,
                           every=args.every)
        print(f"Submitted: {job_id}")

    elif args.command == "list":
        statuses = ["pending", "running", "done", "failed"] if args.status == "all" else [args.status]
        for s in statuses:
            jobs = list_jobs(s)
            if jobs:
                print(f"\n=== {s.upper()} ({len(jobs)}) ===")
                for j in jobs:
                    print(f"  {j.id} | {j.repo} | {j.code_target} | pri={j.priority} | {j.submitted_at}")

    elif args.command == "process":
        src = RalphSchedulerSource()
        events = src.poll(time.time())
        for e in events:
            print(f"[{e.source}] {e.content}")
        if not events:
            print("No events.")

    elif args.command == "daemon":
        print(f"Ralph scheduler daemon (interval={args.interval}s)")
        src = RalphSchedulerSource()
        while True:
            events = src.poll(time.time())
            for e in events:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {e.content}")
            time.sleep(args.interval)

    elif args.command == "status":
        src = RalphSchedulerSource()
        s = src.status()
        print(f"Pending: {s['pending']}  Running: {s['running']}  Done: {s['done']}  Failed: {s['failed']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
