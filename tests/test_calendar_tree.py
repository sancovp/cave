"""The calendar tree: a calendar HAS jobs and HAS sources, a source IS a calendar (cave.core.calendar).

Each test builds folder calendars in a temporary directory, and running apps as local http servers, and checks one
law: the joined view and its tags, loops refused, the http source's limits, the clock's claim, and each job firing
once — by its own calendar's clock, else by the nearest calendar above it that has one.
"""
import http.server
import json
import os
import socket
import threading
from pathlib import Path

import pytest

from cave.core.automation import AutomationRegistry
from cave.core.calendar import (
    CLAIM_LAPSE_S,
    CLOCK_FILE,
    META_DIR,
    RUNS_FILE,
    VIA_HEADER,
    Calendar,
    calendar_id,
    claim,
    parse_via,
)


def job(store: Path, name: str, **spec) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "schedule": "every:1", "code_pointer": "os.getcwd", **spec}
    path = store / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


def calendar(store: Path) -> Calendar:
    store.mkdir(parents=True, exist_ok=True)
    registry = AutomationRegistry(store)
    registry.load_all()
    return Calendar(registry)


def by_name(entries):
    return {e["name"]: e for e in entries}


@pytest.fixture
def served():
    """Runs local http calendars: `serve({"/a": answer})`, where an answer is a list, or a function of the `via` ids."""
    servers = []

    def serve(routes):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                via = parse_via(self.headers.get(VIA_HEADER))
                seen.append((self.path, via))
                answer = routes.get(self.path)
                body = json.dumps(answer(via) if callable(answer) else answer).encode()
                self.send_response(200 if answer is not None else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}", seen

    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


# --- the joined view ---------------------------------------------------------------------------------------------


def test_joined_tags_every_job_with_the_chain_it_lives_under(tmp_path):
    top, mid, low = tmp_path / "top", tmp_path / "mid", tmp_path / "low"
    job(top, "own")
    job(mid, "mid-job")
    job(low, "low-job")
    cal = calendar(top)
    cal.add_source({"name": "mid", "type": "dir", "path": str(mid)})
    calendar(mid).add_source({"name": "low", "type": "dir", "path": "../low"})  # relative to the folder listing it

    entries = by_name(cal.joined())
    assert (entries["own"]["source"], entries["own"]["calendar"]) == ("local", "")
    assert (entries["mid-job"]["source"], entries["mid-job"]["calendar"], entries["mid-job"]["key"]) == \
        ("mid", "mid", "mid/mid-job")
    assert (entries["low-job"]["source"], entries["low-job"]["calendar"], entries["low-job"]["key"]) == \
        ("mid", "mid/low", "mid/low/low-job")


def test_a_folder_loop_is_refused_and_a_calendar_listing_itself_is_its_own(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    job(a, "a-job")
    job(b, "b-job")
    cal = calendar(a)
    cal.add_source({"name": "local", "type": "dir", "path": str(a)})   # the "local" source an app lists for itself
    cal.add_source({"name": "b", "type": "dir", "path": str(b)})
    calendar(b).add_source({"name": "a", "type": "dir", "path": str(a)})

    entries = cal.joined()
    assert [e["name"] for e in entries if e.get("name") == "a-job"] == ["a-job"]   # listed once, as its own
    loops = [e for e in entries if e.get("status") == "loop"]
    assert [(e["name"], e["calendar"]) for e in loops] == [("[a]", "b/a")]


def test_a_missing_folder_is_one_status_entry(tmp_path):
    cal = calendar(tmp_path / "top")
    cal.add_source({"name": "gone", "type": "dir", "path": str(tmp_path / "nowhere")})
    assert cal.joined() == [{"name": "[gone]", "source": "gone", "calendar": "gone", "status": "missing"}]


def test_an_http_source_is_tagged_and_told_the_calendars_above_it(tmp_path, served):
    url, seen = served({"/cal": [{"name": "remote-own", "source": "local"},
                                 {"name": "remote-child", "source": "sub"},
                                 {"name": "remote-deep", "calendar": "sub/deeper"}]})
    cal = calendar(tmp_path / "top")
    cal.add_source({"name": "app", "type": "http", "url": f"{url}/cal"})

    entries = by_name(cal.joined())
    assert entries["remote-own"]["calendar"] == "app"
    assert entries["remote-child"]["calendar"] == "app/sub"
    assert entries["remote-deep"]["calendar"] == "app/sub/deeper"
    assert {e["source"] for e in entries.values()} == {"app"}
    assert seen == [("/cal", [cal.calendar_id])]


def test_a_loop_through_running_apps_is_refused(tmp_path, served):
    a, b = calendar(tmp_path / "a"), calendar(tmp_path / "b")
    job(a.store, "a-job")
    a.registry.load_all()
    routes = {}
    url, _ = served(routes)
    routes["/a"] = lambda via: a.joined(via)
    routes["/b"] = lambda via: b.joined(via)
    a.add_source({"name": "b", "type": "http", "url": f"{url}/b"})
    b.add_source({"name": "a", "type": "http", "url": f"{url}/a"})

    entries = a.joined()
    assert [e["status"] for e in entries if e.get("status")] == ["loop"]
    assert [e["calendar"] for e in entries if e.get("status")] == ["b/a"]
    assert [e["calendar"] for e in entries if e.get("name") == "a-job"] == [""]   # its jobs only once, as its own


def test_an_app_that_lists_its_own_jobs_its_own_way_still_refuses_a_loop(tmp_path, served):
    app = calendar(tmp_path / "app")
    routes = {}
    url, _ = served(routes)
    routes["/app"] = lambda via: [{"name": "app-own", "source": "local"}] + app.sources_joined(via)
    app.add_source({"name": "me-again", "type": "http", "url": f"{url}/app"})

    entries = app.sources_joined()
    assert [(e["calendar"], e.get("status")) for e in entries] == [("me-again", None), ("me-again", "loop")]


def test_a_source_that_is_not_http_or_https_is_refused_and_never_read(tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps([{"name": "read-from-outside"}]))
    cal = calendar(tmp_path / "top")
    with pytest.raises(ValueError):
        cal.add_source({"name": "leak", "type": "http", "url": f"file://{secret}"})
    cal.sources_path().parent.mkdir(parents=True, exist_ok=True)   # written by hand, as no add_source would
    cal.sources_path().write_text(json.dumps({"sources": [{"name": "leak", "type": "http", "url": f"file://{secret}"}]}))
    entries = cal.joined()
    assert [(e["name"], e["status"]) for e in entries] == [("[leak]", "refused")]
    assert "read-from-outside" not in json.dumps(entries)


def test_an_app_that_does_not_answer_is_offline(tmp_path, served):
    url, _ = served({})
    cal = calendar(tmp_path / "top")
    cal.add_source({"name": "down", "type": "http", "url": f"{url}/nothing-here"})
    assert [(e["name"], e["status"]) for e in cal.joined()] == [("[down]", "offline")]


def test_sources_are_named_kept_and_removed(tmp_path):
    cal = calendar(tmp_path / "top")
    for bad in ({"type": "dir", "path": "x"}, {"name": "a/b", "type": "dir", "path": "x"},
                {"name": "nopath", "type": "dir"}, {"name": "odd", "type": "ftp", "url": "ftp://x"}):
        with pytest.raises(ValueError):
            cal.add_source(bad)
    assert cal.add_source({"name": "x", "path": "../x"}) == {"success": True,
                                                             "source": {"name": "x", "path": "../x", "type": "dir"}}
    assert "error" in cal.add_source({"name": "x", "type": "dir", "path": "../y"})
    cal.sources_path().write_text(json.dumps({"sources": [{"name": "x", "type": "dir", "path": "../x"},
                                                          "not a source", {"type": "dir"}]}))
    assert [s["name"] for s in cal.list_sources()] == ["x"]
    assert cal.remove_source("x") == {"success": True}
    assert "error" in cal.remove_source("x")


# --- the clock's claim -------------------------------------------------------------------------------------------


def test_a_clock_holds_what_nobody_nearer_holds(tmp_path):
    store = tmp_path / "c"
    store.mkdir()
    assert claim(store, "parent", 1, now=1000.0)
    assert not claim(store, "other-parent", 1, now=1010.0)        # held, beating, as near
    assert not claim(store, "grandparent", 2, now=1010.0)         # held from nearer
    assert not claim(store, "own", 0, now=1020.0)                 # nearer, but never taken at once: it asks
    assert not claim(store, "parent", 1, now=1060.0)              # the holder's next beat hands it over
    assert claim(store, "own", 0, now=1080.0)                     # the own clock holds it from its next beat
    assert not claim(store, "parent", 1, now=1090.0)
    assert claim(store, "parent", 1, now=1080.0 + CLAIM_LAPSE_S + 1)   # the own clock stopped beating


def test_a_calendar_id_is_its_folder_and_its_clock_stays_out_of_git(tmp_path):
    store, other = tmp_path / "c", tmp_path / "d"
    store.mkdir()
    other.mkdir()
    assert calendar_id(store) == calendar_id(tmp_path / "c" / ".." / "c") != calendar_id(other)
    assert not (store / META_DIR).exists()                   # an id writes nothing
    claim(store, "own", 0)
    assert (store / META_DIR / ".gitignore").read_text().split() == [CLOCK_FILE, RUNS_FILE]


# --- fire once ---------------------------------------------------------------------------------------------------


def test_a_folder_calendar_with_no_clock_is_fired_by_the_calendar_above_it(tmp_path):
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    job(child, "work")
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})

    report = parent.tick_sources()
    assert report == {"held": ["child"], "mounted": ["child/work"]}
    assert [a.name for a in parent.registry.get_due()] == ["child/work"]
    assert parent.registry.schema_path("child/work") == child / "work.json"


def test_two_calendars_above_one_folder_fire_it_once(tmp_path):
    first, second = calendar(tmp_path / "first"), calendar(tmp_path / "second")
    child = tmp_path / "child"
    job(child, "work")
    for cal in (first, second):
        cal.add_source({"name": "child", "type": "dir", "path": str(child)})

    first.tick_sources()
    assert second.tick_sources() == {"held": [], "mounted": []}
    assert [a.name for a in first.registry.get_due()] == ["child/work"]
    assert second.registry.get_due() == []


def test_the_nearest_clock_fires_and_a_calendar_with_its_own_clock_is_only_listed(tmp_path):
    grand, mid = calendar(tmp_path / "grand"), calendar(tmp_path / "mid")
    low = tmp_path / "low"
    job(mid.store, "mid-job")
    mid.registry.load_all()
    job(low, "low-job")
    grand.add_source({"name": "mid", "type": "dir", "path": str(mid.store)})
    mid.add_source({"name": "low", "type": "dir", "path": str(low)})

    assert grand.tick_sources()["mounted"] == ["mid/low/low-job", "mid/mid-job"]   # mid has no clock yet
    mid.tick_sources()                                                              # mid's own clock starts: it asks
    assert not mid.own_held
    assert grand.tick_sources() == {"held": [], "mounted": []}                      # grand hands both over
    mid.tick_sources()                                                              # and mid holds them
    assert sorted(a.name for a in mid.registry.get_due()) == ["low/low-job", "mid-job"]
    assert "mid/low/low-job" in {e.get("key") for e in grand.joined()}               # still listed above


def test_a_folder_reached_twice_is_held_once(tmp_path):
    top = calendar(tmp_path / "top")
    left, right, shared = tmp_path / "left", tmp_path / "right", tmp_path / "shared"
    for store in (left, right):
        store.mkdir()
        calendar(store).add_source({"name": "shared", "type": "dir", "path": str(shared)})
    job(shared, "once")
    top.add_source({"name": "left", "type": "dir", "path": str(left)})
    top.add_source({"name": "right", "type": "dir", "path": str(right)})

    assert top.tick_sources()["mounted"] == ["left/shared/once"]


def test_a_job_held_for_a_calendar_below_keeps_its_clock_until_its_file_changes(tmp_path):
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    path = job(child, "work")
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    parent.tick_sources()
    held = parent.registry.get("child/work")
    held.fire()
    parent.tick_sources()
    assert parent.registry.get("child/work") is held and held.run_count == 1

    path.write_text(json.dumps({"name": "work", "schedule": "every:600", "code_pointer": "os.getcwd"}))
    parent.tick_sources()
    assert parent.registry.get("child/work").schedule == "every:600"

    path.unlink()
    assert parent.tick_sources()["mounted"] == []
    assert parent.registry.get("child/work") is None


def test_a_model_call_from_another_folder_is_dormant_unless_its_source_arms_it(tmp_path):
    parent = calendar(tmp_path / "parent")
    quiet, armed = tmp_path / "quiet", tmp_path / "armed"
    job(quiet, "think", code_pointer=None, prompt_template="think about it")
    job(armed, "think", code_pointer=None, prompt_template="think about it")
    parent.add_source({"name": "quiet", "type": "dir", "path": str(quiet)})
    parent.add_source({"name": "armed", "type": "dir", "path": str(armed), "armed": True})

    parent.tick_sources()
    assert [a.name for a in parent.registry.get_due()] == ["armed/think"]
    assert by_name([e for e in parent.joined() if e.get("calendar") == "quiet"])["think"]["dormant"] is True


def test_a_registry_that_fires_only_its_own_jobs_claims_nothing(tmp_path):
    class OwnOnly(AutomationRegistry):
        fires_sources = False

    store = tmp_path / "own-only"
    store.mkdir()
    parent = Calendar(OwnOnly(store), sources_path=tmp_path / "own-only-sources.json")
    child = tmp_path / "child"
    job(child, "work")
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    assert parent.tick_sources() == {"held": [], "mounted": []}
    assert [e["key"] for e in parent.joined()] == ["child/work"]       # listed, never fired
    assert list(store.iterdir()) == [] and not (child / META_DIR).exists()   # and nothing written
    other = calendar(tmp_path / "other")
    other.add_source({"name": "child", "type": "dir", "path": str(child)})
    assert other.tick_sources()["mounted"] == ["child/work"]


def test_hot_reload_keeps_a_held_job_and_only_its_own_folder_changes_it(tmp_path):
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    path = job(child, "work")
    before = path.read_text()
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    parent.tick_sources()

    assert parent.registry.hot_reload()["removed"] == []
    assert parent.registry.get("child/work") is not None

    held = parent.registry.get("child/work")
    with pytest.raises(ValueError):
        parent.registry.save_schema(held.schema)
    assert parent.cancel("child/work") is False
    assert path.read_text() == before and parent.registry.get("child/work") is held
    assert not (parent.store / "child").exists()
    assert parent.schedule_sync({"name": "child/other", "schedule": "0 3 * * *", "code_pointer": "os.getcwd"})["status"] == "error"


def test_a_clock_taking_over_waits_out_an_interval_job_run_by_the_clock_before_it(tmp_path):
    first, second = calendar(tmp_path / "first"), calendar(tmp_path / "second")
    child = tmp_path / "child"
    job(child, "hourly", schedule="every:3600")
    for cal in (first, second):
        cal.add_source({"name": "child", "type": "dir", "path": str(child)})
    first.tick_sources()
    first.registry.get("child/hourly").fire()
    first.tick_sources()                                           # the run recorded beside the folder
    first.remove_source("child")
    first.tick_sources()                                           # let go
    second.tick_sources()
    assert [a.name for a in second.registry.automations.values()] == ["child/hourly"]
    assert second.registry.get_due() == []                         # it ran under the first clock this hour


def test_a_calendar_no_longer_listed_is_let_go(tmp_path):
    first, second = calendar(tmp_path / "first"), calendar(tmp_path / "second")
    child = tmp_path / "child"
    job(child, "work")
    for cal in (first, second):
        cal.add_source({"name": "child", "type": "dir", "path": str(child)})
    first.tick_sources()
    first.remove_source("child")
    assert first.tick_sources() == {"held": [], "mounted": []}
    assert second.tick_sources()["mounted"] == ["child/work"]


def test_a_calendar_that_lists_only_apps_refuses_a_folder_source(tmp_path):
    secret = tmp_path / "private"
    job(secret, "private-job")
    store = tmp_path / "box"
    store.mkdir()
    registry = AutomationRegistry(store)
    cal = Calendar(registry, source_types=("http",))
    with pytest.raises(ValueError):
        cal.add_source({"name": "peek", "type": "dir", "path": str(secret)})
    cal.sources_path().parent.mkdir(parents=True, exist_ok=True)
    cal.sources_path().write_text(json.dumps({"sources": [{"name": "local", "type": "dir", "path": str(store)},
                                                          {"name": "peek", "type": "dir", "path": str(secret)}]}))
    entries = cal.joined()
    assert [(e["name"], e["status"]) for e in entries] == [("[peek]", "refused")]
    assert "private-job" not in json.dumps(entries)
    assert cal.tick_sources() == {"held": [], "mounted": []}


# --- the heart's pass -------------------------------------------------------------------------------------------


def _heart(registry, calendar):
    """A stand-in agent for CAVEAgent.fire_due_automations: its registry, and get_calendar() answering `calendar`."""
    from types import SimpleNamespace
    return SimpleNamespace(automation_registry=registry, get_calendar=lambda: calendar)


def test_the_heart_ticks_the_calendar_over_the_registry_it_fires(tmp_path):
    from cave.core.cave_agent import CAVEAgent

    registry = AutomationRegistry(tmp_path / "store")
    cal = Calendar(registry)
    child = tmp_path / "child"
    job(child, "work", schedule="every:900")
    cal.add_source({"name": "child", "type": "dir", "path": str(child)})
    CAVEAgent.fire_due_automations(_heart(registry, cal))
    assert "child/work" in registry.mounted


def test_the_heart_leaves_alone_an_app_whose_calendar_is_over_another_registry(tmp_path):
    from cave.core.cave_agent import CAVEAgent

    fired = AutomationRegistry(tmp_path / "store")
    other = Calendar(AutomationRegistry(tmp_path / "store"))      # a second registry over the same folder
    child = tmp_path / "child"
    job(child, "work", schedule="every:900")
    other.add_source({"name": "child", "type": "dir", "path": str(child)})
    CAVEAgent.fire_due_automations(_heart(fired, other))
    assert fired.mounted == {} and other.registry.mounted == {}
    assert not (child / META_DIR).exists()                          # nothing claimed beneath it
    assert not (tmp_path / "store" / META_DIR / CLOCK_FILE).exists()  # and no clock written into its store


# --- the handover: a nearer clock takes a folder over without a beat where two fire it ---------------------------


@pytest.fixture
def fires(monkeypatch):
    """Every fire of any job, by name, counted where it happens (a job let go takes its run count with it)."""
    from cave.core.automation import InputAutomation
    seen = []
    original = InputAutomation.fire

    def counted(self, *a, **k):
        seen.append(self.name)
        return original(self, *a, **k)

    monkeypatch.setattr(InputAutomation, "fire", counted)
    return seen


def test_a_nearer_clock_takes_over_a_folder_held_from_farther_and_its_job_fires_once(tmp_path, fires):
    from cave.core.cave_agent import CAVEAgent

    far, near = calendar(tmp_path / "far"), calendar(tmp_path / "near")
    middle, folder = tmp_path / "middle", tmp_path / "folder"
    middle.mkdir()
    job(folder, "work", schedule="every:3600")
    far.add_source({"name": "middle", "type": "dir", "path": str(middle)})
    calendar(middle).add_source({"name": "folder", "type": "dir", "path": str(folder)})   # far reaches it at 2
    near.add_source({"name": "folder", "type": "dir", "path": str(folder)})                # near at 1
    for _ in range(4):                                     # the far clock's beat first, as the review found it
        for cal in (far, near):
            CAVEAgent.fire_due_automations(_heart(cal.registry, cal))
            due = [a.name for r in (far.registry, near.registry) for a in r.get_due()]
            assert len(due) <= 1, due                      # never due in two registries in one beat
    assert fires == ["middle/folder/work"]                 # once, by the clock that held it first
    assert "folder/work" in near.registry.mounted and not far._mount_state


def test_a_calendar_whose_own_clock_starts_under_a_holder_fires_its_jobs_once(tmp_path, fires):
    from cave.core.cave_agent import CAVEAgent

    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    job(child, "own", schedule="every:3600")
    own = calendar(child)
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    CAVEAgent.fire_due_automations(_heart(parent.registry, parent))           # the parent holds and fires it
    for _ in range(3):
        CAVEAgent.fire_due_automations(_heart(own.registry, own))             # its own clock starts
        CAVEAgent.fire_due_automations(_heart(parent.registry, parent))
    assert fires == ["child/own"]                          # once, by the parent that held it first
    assert own.own_held and not parent._mount_state


def test_a_restarted_clock_takes_its_own_folder_back_at_once(tmp_path):
    store = tmp_path / "c"
    store.mkdir()
    dead = subprocess_pid_gone()
    assert claim(store, f"{socket.gethostname()}:{dead}:old-life", 0, now=1000.0)
    assert claim(store, f"{socket.gethostname()}:{os.getpid()}:new-life", 0, now=1001.0)


def subprocess_pid_gone() -> int:
    import subprocess
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def test_a_clock_that_stops_is_taken_over_and_its_jobs_wait_from_their_record(tmp_path, fires):
    from cave.core.cave_agent import CAVEAgent

    folder = tmp_path / "folder"
    job(folder, "own", schedule="every:3600")
    own = calendar(folder)
    CAVEAgent.fire_due_automations(_heart(own.registry, own))     # its own clock fires it
    own.tick_sources()                                             # and records the run beside it
    clock = folder / META_DIR / CLOCK_FILE
    state = json.loads(clock.read_text())
    clock.write_text(json.dumps({**state, "beat": state["beat"] - CLAIM_LAPSE_S - 1}))   # then it stops
    parent = calendar(tmp_path / "parent")
    parent.add_source({"name": "folder", "type": "dir", "path": str(folder)})
    CAVEAgent.fire_due_automations(_heart(parent.registry, parent))
    assert "folder/own" in parent.registry.mounted
    assert fires == ["own"]                                        # it waits its interval from the run on record
