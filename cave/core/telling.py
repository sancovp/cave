"""Telling a person when a job fails — the heart's teller (DESIGN.md §1, A failure is told to a person).

A calendar names where its failures are told in `.calendar/tell.json` (`{"to": "<target>"}`): one of the delivery
router's targets (`agent:` · `channel:` · `file:` · `webhook:` · `log` · `self`), or `issue:<owner>/<repo>`, which keeps
one open GitHub issue per failing job. The heart tells twice in a run of failures — at the first failure and at the
first success after it — and `.calendar/tellings.json` keeps which runs were told, and the issue that told each, so an
issue is read back by its number (GitHub's listings miss an issue made seconds before) and a telling that could not
reach its target is tried again at the next failure. Telling never raises: what it did, or why it told no one, is its
answer.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TELL_FILE = "tell.json"            # where a calendar's failures are told; committed with its folder
TELLINGS_FILE = "tellings.json"    # which failures were told, and by which issue; never committed
ISSUE_LABEL = "job-failed"
GH_TIMEOUT_S = 20                  # each `gh` call is cut here: a telling happens only at a run's two changes, but the
                                   # heart's ticks run in series, so a hung GitHub must not hold a beat for long
TOLD = ("delivered", "logged", "ok", "sent")   # what a delivery router target answers when it delivered
_MEMORY: Dict[str, Dict[str, Any]] = {}       # every telling of this process, by calendar: kept when the file is not
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
# ↑ the variables `gh` takes a token from ahead of its own stored login


def gh_env() -> tuple[dict, str]:
    """The environment a `gh` call runs in, and the credential it leaves `gh`, in words. `gh` takes a token from any of
    `TOKEN_VARS` ahead of its stored login, and the process running the heart can carry one that reads a repository and
    cannot write it; so with a stored login, every call runs without them. The token itself is never read."""
    bare = {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}
    try:
        logged_in = subprocess.run(["gh", "auth", "token"], capture_output=True, env=bare,
                                   timeout=GH_TIMEOUT_S).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logged_in = False
    if logged_in:
        return bare, "gh's stored login"
    carried = [k for k in TOKEN_VARS if os.environ.get(k)]
    return dict(os.environ), f"the token in {carried[0]}" if carried else "no credential"


def run_gh(*args: str, gh: Optional[tuple] = None) -> subprocess.CompletedProcess:
    """`gh <args>` in `gh_env`'s environment (`gh`, when the caller computed it once for several calls), its output
    captured as text, cut at `GH_TIMEOUT_S`; `.credential` names what it ran on."""
    env, credential = gh or gh_env()
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, env=env, timeout=GH_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        out = subprocess.CompletedProcess(["gh", *args], 1, stdout="", stderr=f"{type(e).__name__}: {e}")
    out.credential = credential
    return out


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _issue_title(job: str) -> str:
    return f"JOB FAILED: {job}"


def _message(job: str, failure: Dict[str, Any]) -> str:
    lines = [f"The job `{job}` failed: {failure.get('status', 'failed')}"
             + (f", exit {failure['exit_code']}" if failure.get("exit_code") not in (None, "") else "") + "."]
    if failure.get("missing"):
        lines.append(f"Missing deliverables: {', '.join(map(str, failure['missing']))}.")
    if failure.get("error"):
        lines.append(f"Error: {str(failure['error'])[:500]}")
    lines.append("Its block report is in the agent's `automation_failures/`; the job is told again only when it works,"
                 " and again if it fails after that.")
    return "\n".join(lines)


class Teller:
    """The teller of one calendar: its `.calendar/` folder's `tell.json` says where, `tellings.json` what was told."""

    def __init__(self, meta: Path, router: Any = None):
        self.meta = Path(meta)
        self.router = router

    @property
    def target(self) -> Optional[str]:
        to = _read(self.meta / TELL_FILE).get("to")
        return to.strip() if isinstance(to, str) and to.strip() else None

    def _tellings(self) -> Dict[str, Any]:
        """The record: the file, with this process's own tellings over it, so a record the file could not keep still
        holds. A file that cannot be read is set aside beside it (`tellings.json.unreadable`) for a person, never
        overwritten with the other jobs' records lost."""
        path = self.meta / TELLINGS_FILE
        on_disk: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    raise ValueError("not an object")
                on_disk = data
            except (OSError, ValueError) as e:
                logger.warning("%s is unreadable (%s); set aside, and the record starts again", path, e)
                try:
                    path.replace(path.with_name(TELLINGS_FILE + ".unreadable"))
                except OSError:
                    pass
        merged = {**on_disk, **_MEMORY.get(str(self.meta), {})}
        return {k: v for k, v in merged.items() if v is not None}

    def _keep(self, tellings: Dict[str, Any]) -> str:
        """Writes the record whole, and holds it in this process's memory too; "" when written, else what could not be
        kept on disk."""
        mem = _MEMORY.setdefault(str(self.meta), {})
        for job in set(mem) | set(tellings):
            mem[job] = tellings.get(job)          # None marks a job cleared, so the file's stale entry is not read back
        try:
            from cave.core.calendar import _meta
            _meta(self.meta.parent)   # the folder and its .gitignore, for a folder no clock has claimed yet
            tmp = self.meta / (TELLINGS_FILE + ".tmp")
            tmp.write_text(json.dumps(tellings, indent=2, sort_keys=True) + "\n")
            tmp.replace(self.meta / TELLINGS_FILE)
        except OSError as e:
            return f"; the telling not recorded: {type(e).__name__}: {e}"
        return ""

    def failed(self, job: str, failure: Dict[str, Any]) -> str:
        """A failure of `job`: told when this run of failures is not yet told, else nothing new."""
        try:
            target = self.target
            if not target:
                return "told no one: the calendar names no teller"
            tellings = self._tellings()
            if job in tellings:
                return f"already told ({tellings[job].get('to')})"
            told: Dict[str, Any] = {"to": target, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if target.startswith("issue:"):
                n = self._open_issue(target.split(":", 1)[1], job, failure)
                told["issue"] = n
                answer = f"told: issue #{n}"
            else:
                out = self._deliver(target, {"prompt": _message(job, failure), "job": job, "event": "failed"})
                if out.get("status") not in TOLD:
                    return f"told no one: {target} answered {out}"
                answer = f"told: {target}"
            tellings[job] = told
            return answer + self._keep(tellings)
        except Exception as e:   # telling never fails a beat
            return f"told no one: {type(e).__name__}: {e}"

    def cleared(self, job: str) -> str:
        """A success of `job`: when a run of its failures was told, it is told that the job works again."""
        try:
            tellings = self._tellings()
            told = tellings.get(job)
            if not told:
                return "nothing to tell"
            target = told.get("to") or ""
            if target.startswith("issue:") and told.get("issue"):
                self._close_issue(target.split(":", 1)[1], int(told["issue"]), job)
                answer = f"told: issue #{told['issue']} closed"
            else:
                out = self._deliver(target, {"prompt": f"The job `{job}` works again.", "job": job, "event": "cleared"})
                if out.get("status") not in TOLD:
                    return f"told no one: {target} answered {out}"
                answer = f"told: {target}"
            del tellings[job]
            return answer + self._keep(tellings)
        except Exception as e:
            return f"told no one: {type(e).__name__}: {e}"

    def forget(self, job: str) -> str:
        """Drops the record of a job that will not run again (a one-shot, removed after it fired): no success can follow
        its told failure, and a job given its name later starts a run of its own."""
        tellings = self._tellings()
        if job not in tellings:
            return ""
        del tellings[job]
        return self._keep(tellings)

    def _deliver(self, target: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.router is None:
            from cave.core.automation import DeliveryRouter
            self.router = DeliveryRouter()
        return self.router.deliver(target, payload) or {}

    def _open_issue(self, repo: str, job: str, failure: Dict[str, Any]) -> int:
        """The job's open issue, else one opened; answers its number and raises when GitHub refuses, so nothing is
        recorded as told. An open issue with the job's title and label is the job's — opened by a telling whose record
        was lost — and is taken up, not opened again; GitHub's listings miss only an issue made seconds before, and two
        failures of one job are a beat apart at least."""
        gh = gh_env()
        found = run_gh("issue", "list", "--repo", repo, "--state", "open", "--label", ISSUE_LABEL, "--json",
                       "number,title", gh=gh)
        if found.returncode == 0:
            mine = sorted(i["number"] for i in json.loads(found.stdout or "[]") if i.get("title") == _issue_title(job))
            if mine:
                return mine[0]
        label = run_gh("label", "create", ISSUE_LABEL, "--repo", repo, "--force", "--color", "B60205",
                       "--description", "a calendar job's failure, told by its heart", gh=gh)
        if label.returncode != 0:
            raise RuntimeError(f"making the label failed on {label.credential}: {label.stderr.strip()[-200:]}")
        out = run_gh("api", "-X", "POST", f"repos/{repo}/issues", "-f", f"title={_issue_title(job)}",
                     "-f", f"body={_message(job, failure)}", "-f", f"labels[]={ISSUE_LABEL}", gh=gh)
        if out.returncode != 0:
            raise RuntimeError(f"opening the issue failed on {out.credential}: {out.stderr.strip()[-200:]}")
        return int(json.loads(out.stdout)["number"])

    def _close_issue(self, repo: str, number: int, job: str) -> None:
        """Closes the job's issue with its comment, in one call; an issue already closed, or one GitHub says is gone
        (404, 410), needs nothing more."""
        gh = gh_env()
        done = run_gh("api", f"repos/{repo}/issues/{number}", gh=gh)
        if done.returncode != 0:
            if "(HTTP 404)" in done.stderr or "(HTTP 410)" in done.stderr:
                return
            raise RuntimeError(f"reading #{number} failed on {done.credential}: {done.stderr.strip()[-200:]}")
        if json.loads(done.stdout).get("state") == "closed":
            return
        out = run_gh("issue", "close", str(number), "--repo", repo, "--comment", f"The job `{job}` works again.", gh=gh)
        if out.returncode != 0:
            raise RuntimeError(f"closing #{number} failed on {out.credential}: {out.stderr.strip()[-200:]}")
