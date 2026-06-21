"""Tests for AgentInferenceLoop output delivery overrides."""
from types import SimpleNamespace

from cave.core.loops.base import create_loop


class FakeMainAgent:
    def __init__(self):
        self.sent = []

    def send_keys(self, *args):
        self.sent.append(args)


class FakeCave:
    def __init__(self):
        self.config = SimpleNamespace(
            main_agent_config=SimpleNamespace(active_hooks={}),
        )
        self.main_agent = FakeMainAgent()
        self.routed = []

    def route_message(self, **kwargs):
        self.routed.append(kwargs)
        return "msg-123"


def test_loop_defaults_to_tmux_prompt_delivery():
    cave = FakeCave()
    loop = create_loop(name="default", prompt="work now")

    result = loop.activate(cave)

    assert cave.main_agent.sent == [("work now", 0.5, "Enter")]
    assert cave.routed == []
    assert result["prompt_sent"] is True
    assert result["output"] == {"sent": True, "type": "tmux"}


def test_loop_output_override_routes_prompt_to_agent_inbox():
    cave = FakeCave()
    loop = create_loop(
        name="codex_loop",
        prompt="wake conductor",
        output_override={
            "type": "agent_inbox",
            "to_agent": "conductor",
            "from_agent": "loop:codex_loop",
            "priority": 7,
            "metadata": {"reason": "test"},
        },
    )

    result = loop.activate(cave)

    assert cave.main_agent.sent == []
    assert cave.routed == [{
        "from_agent": "loop:codex_loop",
        "to_agent": "conductor",
        "content": "wake conductor",
        "priority": 7,
        "metadata": {
            "loop": "codex_loop",
            "output_override": "agent_inbox",
            "reason": "test",
        },
    }]
    assert result["prompt_sent"] is True
    assert result["output"] == {
        "sent": True,
        "type": "agent_inbox",
        "to_agent": "conductor",
        "message_id": "msg-123",
    }


def test_loop_output_override_accepts_callable_delivery():
    cave = FakeCave()

    def deliver(target, loop):
        return {"target_seen": target is cave, "loop": loop.name}

    loop = create_loop(
        name="callable_loop",
        prompt="custom delivery",
        output_override=deliver,
    )

    result = loop.activate(cave)

    assert cave.main_agent.sent == []
    assert result["prompt_sent"] is True
    assert result["output"] == {
        "sent": True,
        "type": "callable",
        "target_seen": True,
        "loop": "callable_loop",
    }
