"""A failure is told to a person (DESIGN.md §1): every outcome through one place, told at a run of failures' first
failure and at its first success, through the target its calendar's `.calendar/tell.json` names, never twice."""
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import cave.core.telling as telling
from cave.core.automation import AutomationRegistry, AutomationSchema
from cave.core.calendar import META_DIR, Calendar, _meta
from cave.core.cave_agent import CAVEAgent


@pytest.fixture
def blockages(tmp_path, monkeypatch):
    import cave.core.blockage_store as store
    path = tmp_path / "blockages.jsonl"
    monkeypatch.setattr(store, "STORE_PATH", path)
    return path


def heart(tmp_path, to=None):
    """A stand-in agent over a registry of its own, its calendar telling `to` (none when None)."""
    registry = AutomationRegistry(tmp_path / "store")
    if to is not None:
        meta = _meta(tmp_path / "store")
        (meta / "tell.json").write_text(json.dumps({"to": to}))
    agent = SimpleNamespace(automation_registry=registry, get_calendar=lambda: Calendar(registry),
                            config=SimpleNamespace(data_dir=tmp_path / "data"))
    return agent


def auto(tells_failures=False):
    return SimpleNamespace(schema=AutomationSchema(name="job", tells_failures=tells_failures))


FAILED = {"status": "failed", "exit_code": 3, "missing": []}


def told_file(tmp_path):
    return [json.loads(l)["event"] for l in (tmp_path / "told").read_text().splitlines()] \
        if (tmp_path / "told").exists() else []


class FileRouter:
    """A delivery router that appends what it is handed to one file, or answers an error when `refuse` is set."""
    def __init__(self, path, refuse=False):
        self.path, self.refuse = path, refuse

    def deliver(self, target, payload):
        if self.refuse:
            return {"status": "error", "reason": "unreachable"}
        with open(self.path, "a") as f:
            f.write(json.dumps(payload) + "\n")
        return {"status": "delivered"}


@pytest.fixture
def router(tmp_path, monkeypatch):
    r = FileRouter(tmp_path / "told")
    import cave.core.automation as automation
    monkeypatch.setattr(automation, "DeliveryRouter", lambda cave_agent=None: r)
    return r


def test_a_run_of_failures_is_told_once_and_its_first_success_is_told(tmp_path, blockages, router):
    agent = heart(tmp_path, to="log")
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()) == "told: log"
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()).startswith("already told")
    assert CAVEAgent.record_outcome(agent, "job", None, auto=auto()) == "told: log"
    assert CAVEAgent.record_outcome(agent, "job", None, auto=auto()) == "nothing to tell"
    assert told_file(tmp_path) == ["failed", "cleared"]
    assert json.loads((tmp_path / "store" / META_DIR / "tellings.json").read_text()) == {}
    lines = [json.loads(l) for l in blockages.read_text().splitlines()]
    assert len(lines) == 2 and all(l.get("resolved") for l in lines)     # each failure a blockage, both resolved


def test_a_job_that_tells_its_own_failures_is_recorded_and_told_by_no_one(tmp_path, blockages, router):
    agent = heart(tmp_path, to="log")
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto(tells_failures=True)) == "the job tells its own failures"
    assert told_file(tmp_path) == [] and len(blockages.read_text().splitlines()) == 1
    assert list((tmp_path / "data" / "automation_failures").iterdir())


def test_a_calendar_that_names_no_teller_records_and_tells_no_one(tmp_path, blockages, router):
    agent = heart(tmp_path)
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()) == "told no one: the calendar names no teller"
    assert told_file(tmp_path) == [] and len(blockages.read_text().splitlines()) == 1


def test_a_telling_that_cannot_reach_its_target_is_tried_again_at_the_next_failure(tmp_path, blockages, router):
    agent = heart(tmp_path, to="log")
    router.refuse = True
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()).startswith("told no one: log answered")
    router.refuse = False
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()) == "told: log"
    assert told_file(tmp_path) == ["failed"]


class Issues:
    """Stands in for `gh` inside the teller: an issue read by number answers at once, 404 once deleted; `fail_on` names
    a call that answers HTTP 502."""
    def __init__(self):
        self.issues, self.calls, self.fail_on = {}, [], None

    def __call__(self, *args):
        self.calls.append(list(args))
        out = subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        out.credential = "gh's stored login"
        verb = ("create" if "POST" in args else "view") if args[0] == "api" else (args[1] if args[0] == "issue" else args[0])
        if verb == self.fail_on:
            out.returncode, out.stderr = 1, "gh: Server Error (HTTP 502)"
        elif verb == "list":
            out.stdout = json.dumps([{"number": n, "title": i["title"]} for n, i in self.issues.items()
                                     if i["state"] == "open" and telling.ISSUE_LABEL in i["labels"]])
        elif verb == "create":
            n = len(self.issues) + 1
            field = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if "=" in a}
            self.issues[n] = {"title": field["title"], "labels": [field["labels[]"]], "state": "open", "comments": []}
            out.stdout = json.dumps({"number": n})
        elif verb == "view":
            n = int(args[1].rsplit("/", 1)[1])
            if n not in self.issues:
                out.returncode, out.stderr = 1, "gh: Not Found (HTTP 404)"
            else:
                out.stdout = json.dumps({"number": n, "state": self.issues[n]["state"]})
        elif verb == "comment":
            self.issues[int(args[2])]["comments"].append(args[args.index("--body") + 1])
        elif verb == "close":
            self.issues[int(args[2])]["state"] = "closed"
            if "--comment" in args:
                self.issues[int(args[2])]["comments"].append(args[args.index("--comment") + 1])
        return out


@pytest.fixture
def gh(monkeypatch):
    fake = Issues()
    monkeypatch.setattr(telling, "run_gh", lambda *a, gh=None: fake(*a))
    monkeypatch.setattr(telling, "gh_env", lambda: ({}, "gh's stored login"))
    return fake


@pytest.fixture(autouse=True)
def fresh_memory():
    """each case is its own process, as far as the teller's memory of its tellings goes"""
    telling._MEMORY.clear()
    yield
    telling._MEMORY.clear()


def test_an_issue_teller_opens_one_labelled_issue_per_run_and_closes_it_on_the_first_success(tmp_path, blockages, gh):
    agent = heart(tmp_path, to="issue:o/r")
    assert CAVEAgent.record_outcome(agent, "child/absorber", FAILED) == "told: issue #1"
    assert CAVEAgent.record_outcome(agent, "child/absorber", FAILED).startswith("already told")
    assert len(gh.issues) == 1 and gh.issues[1]["title"] == "JOB FAILED: child/absorber"
    assert gh.issues[1]["labels"] == [telling.ISSUE_LABEL]
    assert CAVEAgent.record_outcome(agent, "child/absorber", None) == "told: issue #1 closed"
    assert gh.issues[1]["state"] == "closed" and gh.issues[1]["comments"]
    assert CAVEAgent.record_outcome(agent, "child/absorber", FAILED) == "told: issue #2"   # a new run of failures


def test_an_issue_that_cannot_open_is_tried_again_and_one_deleted_before_the_success_is_dropped(tmp_path, blockages, gh):
    agent = heart(tmp_path, to="issue:o/r")
    gh.fail_on = "create"
    assert CAVEAgent.record_outcome(agent, "job", FAILED).startswith("told no one: RuntimeError: opening the issue failed")
    gh.fail_on = None
    assert CAVEAgent.record_outcome(agent, "job", FAILED) == "told: issue #1"
    del gh.issues[1]                                                   # deleted by a person
    assert CAVEAgent.record_outcome(agent, "job", None) == "told: issue #1 closed"
    assert json.loads((tmp_path / "store" / META_DIR / "tellings.json").read_text()) == {}


def test_gh_runs_on_its_stored_login_without_the_tokens_the_heart_carries(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "a-token-that-cannot-write")
    seen = []

    def run(cmd, **kw):
        seen.append(kw.get("env", {}))
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
    monkeypatch.setattr(telling.subprocess, "run", run)
    out = telling.run_gh("api", "user")
    assert out.credential == "gh's stored login"
    assert all("GITHUB_TOKEN" not in env for env in seen)


def test_every_outcome_the_heart_reads_goes_through_record_outcome():
    """no other place in the heart writes a block report or a blockage, so no failure escapes the telling"""
    src = (Path(__file__).resolve().parent.parent / "cave" / "core" / "cave_agent.py").read_text()
    body = src[src.index("    def record_outcome("):src.index("    @staticmethod\n    def _get_pid_start_time")]
    rest = src.replace(body, "")
    assert not re.search(r"BlockageStore\(\)\.(add|mark_resolved)\(", rest), "a blockage written outside record_outcome"
    assert not re.search(r"\b_write_automation_failure\(", rest.split("    def _write_automation_failure(")[0]), \
        "a block report written outside record_outcome"


def test_a_failed_process_job_is_told_through_the_heart(tmp_path, blockages, router):
    """end to end: a held job whose process exits 3, over two beats of a stand-in heart, is told once"""
    parent = Calendar(AutomationRegistry(tmp_path / "parent"))
    (_meta(tmp_path / "parent") / "tell.json").write_text(json.dumps({"to": "file:never-used"}))
    child = tmp_path / "child"
    child.mkdir()
    (_meta(child) / "tell.json").write_text(json.dumps({"to": "log"}))       # the job's own calendar says where
    (child / "run.json").write_text(json.dumps({"name": "run", "schedule": "every:3600",
                                                 "code_pointer": "subprocess.Popen",
                                                 "code_args": {"args": ["${PYTHON}", "-c", "import sys; sys.exit(3)"]}}))
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    agent = SimpleNamespace(automation_registry=parent.registry, get_calendar=lambda: parent,
                            config=SimpleNamespace(data_dir=tmp_path / "data"),
                            _get_pid_start_time=CAVEAgent._get_pid_start_time)
    CAVEAgent.fire_due_automations(agent)
    parent.registry.get("child/run")._process.wait()
    CAVEAgent.fire_due_automations(agent)
    assert told_file(tmp_path) == ["failed"]
    assert json.loads((child / META_DIR / "tellings.json").read_text())["child/run"]["to"] == "log"
    assert not (tmp_path / "parent" / META_DIR / "tellings.json").exists()   # the firing calendar's teller is not asked


def test_a_calendar_folder_made_before_the_tellings_ignores_them_too(tmp_path):
    meta = tmp_path / META_DIR
    meta.mkdir()
    (meta / ".gitignore").write_text("clock.json\nruns.json\n")
    _meta(tmp_path)
    from cave.core.calendar import IGNORED
    assert (meta / ".gitignore").read_text().split() == list(IGNORED)


def test_the_log_target_is_told_once_and_its_recovery_once(tmp_path, blockages, monkeypatch):
    """`log` answers `logged`, which is a telling: the run of failures is told once, not at every beat"""
    monkeypatch.setenv("HEAVEN_DATA_DIR", str(tmp_path / "heaven"))
    agent = heart(tmp_path, to="log")
    answers = [CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()) for _ in range(3)]
    answers.append(CAVEAgent.record_outcome(agent, "job", None, auto=auto()))
    assert answers[0] == "told: log" and answers[1].startswith("already told") and answers[3] == "told: log", answers
    assert len((tmp_path / "heaven" / "automation_log.jsonl").read_text().splitlines()) == 2


def test_a_telling_whose_record_is_lost_takes_up_the_issue_it_opened(tmp_path, blockages, gh, monkeypatch):
    """a record the file could not keep is held in memory; a record lost with the process is found again by the open
    issue's title, so one run of failures has one issue"""
    agent = heart(tmp_path, to="issue:o/r")
    real_replace = Path.replace
    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError("read-only")))
    first = CAVEAgent.record_outcome(agent, "job", FAILED)
    assert first.startswith("told: issue #1; the telling not recorded")
    assert CAVEAgent.record_outcome(agent, "job", FAILED).startswith("already told")      # memory holds it
    monkeypatch.setattr(Path, "replace", real_replace)
    telling._MEMORY.clear()                                                               # a new process
    assert CAVEAgent.record_outcome(agent, "job", FAILED) == "told: issue #1"             # the open issue taken up
    assert len(gh.issues) == 1


def test_an_unreadable_record_is_set_aside_never_overwritten(tmp_path, blockages, router):
    agent = heart(tmp_path, to="log")
    meta = tmp_path / "store" / META_DIR
    (meta / "tellings.json").write_text("{not json")
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()) == "told: log"
    assert (meta / "tellings.json.unreadable").read_text() == "{not json"
    assert "job" in json.loads((meta / "tellings.json").read_text())


def test_hot_reload_takes_a_changed_tells_failures(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "x.json").write_text(json.dumps({"name": "x", "schedule": "every:900"}))
    registry = AutomationRegistry(store)
    registry.load_all()
    (store / "x.json").write_text(json.dumps({"name": "x", "schedule": "every:900", "tells_failures": True}))
    assert "x" in registry.hot_reload()["updated"] and registry.get("x").schema.tells_failures is True


def test_a_job_file_that_says_nothing_of_tells_failures_is_saved_as_it_was():
    assert "tells_failures" not in AutomationSchema(name="x").to_dict()
    assert AutomationSchema.from_dict(AutomationSchema(name="x", tells_failures=True).to_dict()).tells_failures is True


def test_a_process_whose_job_is_gone_is_told_by_the_calendar_its_process_kept(tmp_path, blockages, router):
    agent = heart(tmp_path, to="file:the-heart-s-own")
    child = tmp_path / "child"
    (_meta(child) / "tell.json").write_text(json.dumps({"to": "log"}))
    kept = {"calendar_dir": str(child), "tells_failures": False, "one_shot": False}
    assert CAVEAgent.record_outcome(agent, "child/run", FAILED, auto=None, tracked=kept) == "told: log"
    assert "child/run" in json.loads((child / META_DIR / "tellings.json").read_text())
    selfish = {"calendar_dir": str(child), "tells_failures": True, "one_shot": False}
    assert CAVEAgent.record_outcome(agent, "child/other", FAILED, auto=None, tracked=selfish) == \
        "the job tells its own failures"


def test_a_one_shot_job_s_record_is_dropped_once_told(tmp_path, blockages, router):
    agent = heart(tmp_path, to="log")
    one = SimpleNamespace(schema=AutomationSchema(name="once", one_shot=True))
    assert CAVEAgent.record_outcome(agent, "once", FAILED, auto=one) == "told: log"
    assert json.loads((tmp_path / "store" / META_DIR / "tellings.json").read_text()) == {}
    assert CAVEAgent.record_outcome(agent, "once", FAILED, auto=one) == "told: log"      # a later job of its name


def _jobs(store, **files):
    store.mkdir(parents=True, exist_ok=True)
    for name, spec in files.items():
        (store / f"{name}.json").write_text(json.dumps({"name": name, **spec}))
    registry = AutomationRegistry(store)
    registry.load_all()
    return registry


def test_a_parallel_job_whose_run_answers_an_error_is_a_failure(tmp_path, blockages, router):
    registry = _jobs(tmp_path / "store", a={"schedule": "every:3600", "parallel": ["b"]}, b={})
    registry.get("a").fire = lambda *x, **k: {"status": "success"}
    registry.get("b").fire = lambda *x, **k: {"status": "error", "error": "it broke"}
    (_meta(tmp_path / "store") / "tell.json").write_text(json.dumps({"to": "log"}))
    agent = SimpleNamespace(automation_registry=registry, get_calendar=lambda: Calendar(registry),
                            config=SimpleNamespace(data_dir=tmp_path / "data"))
    CAVEAgent.fire_due_automations(agent)
    assert registry.get("b").last_outcome == "failed" and told_file(tmp_path) == ["failed"]


def test_an_in_process_run_left_awaiting_input_is_recorded_and_told(tmp_path, blockages, router):
    registry = _jobs(tmp_path / "store", a={"schedule": "every:3600"})
    registry.get("a").fire = lambda *x, **k: {"status": "awaiting_input"}
    (_meta(tmp_path / "store") / "tell.json").write_text(json.dumps({"to": "log"}))
    agent = SimpleNamespace(automation_registry=registry, get_calendar=lambda: Calendar(registry),
                            config=SimpleNamespace(data_dir=tmp_path / "data"))
    CAVEAgent.fire_due_automations(agent)
    assert told_file(tmp_path) == ["failed"] and len(blockages.read_text().splitlines()) == 1


def test_gh_s_login_check_is_cut_short(monkeypatch):
    seen = []
    monkeypatch.setattr(telling.subprocess, "run",
                        lambda cmd, **kw: seen.append(kw.get("timeout")) or subprocess.CompletedProcess(cmd, 0, "", ""))
    telling.run_gh("api", "user")
    assert seen and all(t is not None and t <= telling.GH_TIMEOUT_S for t in seen), seen


def test_a_hand_written_ignore_file_keeps_its_lines_and_gains_the_names_it_lacks(tmp_path):
    meta = tmp_path / META_DIR
    meta.mkdir()
    (meta / ".gitignore").write_text("# never commit these\nclock.json")
    _meta(tmp_path)
    lines = (meta / ".gitignore").read_text().splitlines()
    assert lines[:2] == ["# never commit these", "clock.json"] and "tellings.json.tmp" in lines


def test_a_telling_in_a_folder_no_clock_claimed_writes_its_ignore_file(tmp_path, blockages, router):
    agent = heart(tmp_path)
    child = tmp_path / "devdir" / ".cave" / "automations"
    child.mkdir(parents=True)
    (child / META_DIR).mkdir()
    (child / META_DIR / "tell.json").write_text(json.dumps({"to": "log"}))       # named by hand: no .gitignore yet
    assert CAVEAgent.record_outcome(agent, "w", FAILED, auto=None, tracked={"calendar_dir": str(child)}) == "told: log"
    assert "tellings.json" in (child / META_DIR / ".gitignore").read_text().split()


def test_a_job_that_now_tells_its_own_failures_still_clears_a_run_told_before(tmp_path, blockages, router):
    agent = heart(tmp_path, to="log")
    assert CAVEAgent.record_outcome(agent, "job", FAILED, auto=auto()) == "told: log"
    assert CAVEAgent.record_outcome(agent, "job", None, auto=auto(tells_failures=True)) == "told: log"
    assert told_file(tmp_path) == ["failed", "cleared"]

