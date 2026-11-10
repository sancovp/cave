"""Review of the calendar tree: each test states what the intent requires and FAILS on the code under review.

Intent: a job fires once, by its own calendar's clock, else by the nearest calendar above it that has one; a job held
for a calendar beneath behaves as it does in its own calendar; a model call from another folder is never spent unasked.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cave.core import blockage_store
from cave.core.automation import AutomationRegistry, EventAutomation, Automation, AutomationSchema
from cave.core.calendar import Calendar
from cave.core.cave_agent import CAVEAgent
from cave.core.mixins.automation_mixin import AutomationMixin


def job(store: Path, name: str, **spec) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "schedule": "every:1", "code_pointer": "os.getcwd", **spec}
    path = store / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


def calendar(store: Path, **kw) -> Calendar:
    store.mkdir(parents=True, exist_ok=True)
    registry = AutomationRegistry(store)
    registry.load_all()
    return Calendar(registry, **kw)


def heart_host(registry, cal):
    """What `CAVEAgent.fire_due_automations` needs of `self`: a registry the heart fires and a `get_calendar()`."""
    return SimpleNamespace(
        automation_registry=registry, get_calendar=lambda: cal, _automation_results={}, _running_processes={},
        _get_pid_start_time=lambda pid: 0, _write_automation_failure=lambda name, result: None,
    )


@pytest.fixture(autouse=True)
def _no_blockage_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(blockage_store, "STORE_PATH", tmp_path / "blockages.jsonl")


def test_scheduling_a_name_that_is_a_held_jobs_name_must_not_overwrite_the_childs_file(tmp_path):
    """`schedule` takes any name, "/" included; `save_schema` of a name in `mounted` writes the origin file in the
    child's folder: one POST to /api/automations/schedule rewrites a job file of another calendar."""
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    path = job(child, "work", description="the child's own")
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    parent.tick_sources()
    before = path.read_text()

    parent.schedule_sync({"name": "child/work", "schedule": "0 3 * * *", "code_pointer": "os.getcwd",
                          "description": "scheduled by someone else"})

    assert path.read_text() == before


def test_a_held_job_that_depends_on_a_job_of_its_own_calendar_fires_after_it(tmp_path):
    """`depends_on` and `parallel` name jobs of the job's own calendar; the registry holds them as `<chain>/<name>`, so
    the dependency is never met and the job never fires — it fires in its own calendar."""
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    job(child, "a")
    job(child, "b", depends_on=["a"])
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    host = heart_host(parent.registry, parent)

    CAVEAgent.fire_due_automations(host)

    assert parent.registry.get("child/a").run_count == 1
    assert parent.registry.get("child/b").run_count == 1


def test_a_calendar_over_another_registry_holds_nothing_so_an_honest_clock_can(tmp_path):
    """JobWorld's avi and kiki agents override `get_calendar()` with `Calendar()` over a NEW registry, and JobWorld is
    left as it was (the owner's ruling): the heart ticks no calendar but one over the registry it fires, so the shadow
    calendar holds nothing and claims nothing — and a clock that does list the folder takes it and fires it."""
    heart_registry = AutomationRegistry(tmp_path / "heart")
    shadow = calendar(tmp_path / "shadow")           # the override's calendar: its own registry, nobody fires it
    child = tmp_path / "child"
    job(child, "work")
    shadow.add_source({"name": "child", "type": "dir", "path": str(child)})

    CAVEAgent.fire_due_automations(heart_host(heart_registry, shadow))
    assert shadow.registry.mounted == {} and heart_registry.mounted == {}

    honest = calendar(tmp_path / "honest")
    honest.add_source({"name": "child", "type": "dir", "path": str(child)})
    CAVEAgent.fire_due_automations(heart_host(honest.registry, honest))
    fired = [a for r in (heart_registry, shadow.registry, honest.registry) for a in r.automations.values() if a.run_count]
    assert [a.name for a in fired] == ["child/work"]


def test_a_folder_the_devdir_loader_holds_is_not_also_mounted_by_a_source(tmp_path):
    """OM's devdir loader registers every `.cave/automations/*.json` of its onion as `woom:<place>:<name>`; the skill
    tells the owner to list such a folder as a dir source, which mounts the same file again: two due jobs per slot."""
    from onionmorph.woom_automations import DevdirAutomationLoader

    cal = calendar(tmp_path / "automations")
    folder = tmp_path / "project" / ".cave" / "automations"
    path = job(folder, "publish")
    cave = SimpleNamespace(automation_registry=cal.registry)
    loader = DevdirAutomationLoader(cave, str(tmp_path))
    loader.sync(SimpleNamespace(automations=[{"path": "/project", "name": "publish",
                                              "spec": json.loads(path.read_text()), "errors": [], "mtime": 0.0}]))
    cal.add_source({"name": "project", "type": "dir", "path": str(folder)})
    cal.tick_sources()

    due = [a.name for a in cal.registry.get_due()]
    assert len(due) == 1, due


def test_editing_a_held_interval_job_does_not_make_it_due_again(tmp_path):
    """A re-made job has no `last_run`, and an interval job with none is due at once: any edit of a held job's file
    (a description) fires it again at the next beat, however long its interval."""
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    path = job(child, "hourly", schedule="every:3600")
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    parent.tick_sources()
    parent.registry.get("child/hourly").fire()
    assert parent.registry.get_due() == []

    path.write_text(json.dumps({**json.loads(path.read_text()), "description": "reworded"}))
    parent.tick_sources()

    assert parent.registry.get_due() == []


def test_a_dormant_model_job_does_not_fire_on_its_event(tmp_path):
    """Dormancy is `_cron_job.enabled = False`, which only `is_due` reads; `fire_event` checks `schema.enabled`, so a
    mounted unarmed job with an `event_name` and a `prompt_template` is fired by its event and delivers its prompt."""
    parent = calendar(tmp_path / "parent")
    child = tmp_path / "child"
    out = tmp_path / "out.json"
    job(child, "ev", schedule=None, code_pointer=None, event_name="ping", prompt_template="think about it",
        delivery={"type": "file", "path": str(out)})
    parent.add_source({"name": "child", "type": "dir", "path": str(child)})
    parent.tick_sources()
    assert isinstance(parent.registry.get("child/ev"), EventAutomation)

    host = SimpleNamespace(automation_registry=parent.registry)
    results = AutomationMixin.fire_event(host, "ping")

    assert results == [] and not out.exists()


@pytest.mark.xfail(strict=True, reason="a registry that fires only its own jobs writes nothing, so it cannot claim its "
                   "own folder; such an app is listed over http, never as a folder (cave DESIGN.md §2, the board)")
def test_a_calendar_whose_registry_fires_its_own_jobs_is_not_also_fired_by_a_calendar_listing_its_folder(tmp_path):
    """HealthWorld's registry has a clock of its own and fires its folder's jobs, but `fires_sources` False makes it
    claim nothing, its own folder included; a calendar above that lists the folder as a dir source then holds it and
    mounts the same jobs: each fires twice. (An app's folder is meant to be listed over http; nothing refuses a dir.)"""
    class OwnOnly(AutomationRegistry):
        fires_sources = False

    app_store = tmp_path / "app"
    job(app_store, "turn")
    app = Calendar(OwnOnly(app_store), sources_path=tmp_path / "app-sources.json")
    app.registry.load_all()
    above = calendar(tmp_path / "above")
    above.add_source({"name": "app", "type": "dir", "path": str(app_store)})

    app.tick_sources()
    above.tick_sources()

    assert [a.name for a in app.registry.get_due()] == ["turn"]      # the app's own clock fires it
    assert above.registry.get_due() == []                            # so the calendar above must not


def test_a_machine_the_devdir_loader_holds_is_listed_as_the_calendars_own(tmp_path):
    """The loader mounts each machine with its file, so the calendar can hold that file once; the machine is the
    calendar's own world machine all the same — listed among its own jobs, never as a job of a calendar beneath."""
    from onionmorph.woom_automations import DevdirAutomationLoader

    cal = calendar(tmp_path / "automations")
    folder = tmp_path / "forge" / ".cave" / "automations"
    path = job(folder, "tend", schedule="every:900")
    loader = DevdirAutomationLoader(SimpleNamespace(automation_registry=cal.registry), str(tmp_path))
    loader.sync(SimpleNamespace(automations=[{"path": "/forge", "name": "tend",
                                              "spec": json.loads(path.read_text()), "errors": [], "mtime": 0.0}]))
    cal.tick_sources()

    own = [(e["name"], e["calendar"]) for e in cal.joined()]
    assert own == [("woom:/forge:tend", "")]
    assert "calendar" not in next(e for e in cal.list_scheduled() if e["name"] == "woom:/forge:tend")
