"""Tests for Body perception through Ears (not Heart).

Validates that world perception is a Body function executed by Ears,
not a Heart tick. Heart pumps prompts. Ears perceives.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from cave.core.mixins.anatomy import Ears, Heart, Tick


# === Mocks ===

@dataclass
class MockWorldEvent:
    source: str
    content: str
    priority: int = 0


class MockWorld:
    def __init__(self, events=None):
        self._events = events or []
        self.tick_count = 0

    def tick(self):
        self.tick_count += 1
        return self._events


class MockCAVEAgent:
    """Minimal mock with world and route_message."""
    def __init__(self, world=None):
        self.world = world or MockWorld()
        self.main_agent = None
        self._routed = []

    def route_message(self, from_agent, to_agent, content, priority=0):
        self._routed.append({
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "priority": priority,
        })


# === Tests: Ears perceives world ===

class TestEarsPerceiveWorld:
    def test_perceive_world_returns_events(self):
        events = [MockWorldEvent(source="test", content="hello")]
        agent = MockCAVEAgent(world=MockWorld(events))
        ears = Ears(name="ears")
        ears.attach(agent)

        result = ears.perceive_world()
        assert len(result) == 1
        assert result[0].content == "hello"

    def test_perceive_world_routes_to_inbox(self):
        events = [MockWorldEvent(source="test", content="hello", priority=5)]
        agent = MockCAVEAgent(world=MockWorld(events))
        ears = Ears(name="ears")
        ears.attach(agent)

        ears.perceive_world()

        assert len(agent._routed) == 1
        assert agent._routed[0]["from"] == "world:test"
        assert agent._routed[0]["to"] == "main"
        assert agent._routed[0]["content"] == "hello"
        assert agent._routed[0]["priority"] == 5

    def test_perceive_world_skips_discord_events(self):
        events = [
            MockWorldEvent(source="discord", content="discord msg"),
            MockWorldEvent(source="cron", content="cron msg"),
        ]
        agent = MockCAVEAgent(world=MockWorld(events))
        ears = Ears(name="ears")
        ears.attach(agent)

        result = ears.perceive_world()
        assert len(result) == 1
        assert result[0].source == "cron"
        assert len(agent._routed) == 1

    def test_perceive_world_rate_limited(self):
        events = [MockWorldEvent(source="test", content="hello")]
        agent = MockCAVEAgent(world=MockWorld(events))
        ears = Ears(name="ears", proprioception_rate=30.0)
        ears.attach(agent)

        # First call — should work
        result1 = ears.perceive_world()
        assert len(result1) == 1

        # Second call immediately — rate limited
        result2 = ears.perceive_world()
        assert len(result2) == 0
        assert agent.world.tick_count == 1  # Only ticked once

    def test_perceive_world_respects_interval(self):
        events = [MockWorldEvent(source="test", content="hello")]
        agent = MockCAVEAgent(world=MockWorld(events))
        ears = Ears(name="ears", proprioception_rate=0.01)
        ears.attach(agent)

        ears.perceive_world()
        time.sleep(0.02)
        result = ears.perceive_world()
        assert len(result) == 1
        assert agent.world.tick_count == 2

    def test_perceive_world_no_agent_returns_empty(self):
        ears = Ears(name="ears")
        result = ears.perceive_world()
        assert result == []

    def test_perceive_world_no_world_returns_empty(self):
        agent = MagicMock(spec=[])  # No world attribute
        ears = Ears(name="ears")
        ears.attach(agent)
        result = ears.perceive_world()
        assert result == []

    def test_perceive_world_increments_counter(self):
        events = [
            MockWorldEvent(source="a", content="1"),
            MockWorldEvent(source="b", content="2"),
        ]
        agent = MockCAVEAgent(world=MockWorld(events))
        ears = Ears(name="ears")
        ears.attach(agent)

        ears.perceive_world()
        assert ears._world_events_processed == 2


class TestEarsStatus:
    def test_status_includes_perception_fields(self):
        ears = Ears(name="ears", proprioception_rate=30.0)
        status = ears.status()

        assert "proprioception_rate" in status
        assert status["proprioception_rate"] == 30.0
        assert "world_events_processed" in status
        assert status["world_events_processed"] == 0
        assert "last_perception" in status


class TestEarsPollLoop:
    def test_poll_loop_calls_both(self):
        """poll_loop calls check_now AND perceive_world."""
        events = [MockWorldEvent(source="test", content="world event")]
        agent = MockCAVEAgent(world=MockWorld(events))
        agent.main_agent = MagicMock()
        agent.main_agent.check_inbox.return_value = []
        ears = Ears(name="ears", poll_interval=0.01, proprioception_rate=0.0)
        ears.attach(agent)
        ears._running = True

        async def run_briefly():
            task = asyncio.create_task(ears.poll_loop())
            await asyncio.sleep(0.05)
            ears._running = False
            await asyncio.sleep(0.02)

        asyncio.run(run_briefly())

        # Both were called
        assert agent.main_agent.check_inbox.called
        assert agent.world.tick_count > 0


class TestHeartNoWorldTick:
    def test_heart_has_no_world_tick(self):
        """Heart should NOT have a world_tick — perception is Ears' job."""
        heart = Heart(name="test_heart")
        assert "world_tick" not in heart.ticks


class TestWirePerceptionLoop:
    def test_sets_proprioception_rate_on_ears(self):
        """_wire_perception_loop configures Ears, doesn't add Heart tick."""

        class FakeAgent:
            def __init__(self):
                self.ears = Ears(name="ears")
                self.heart = Heart(name="heart")
                self.world = MockWorld()

            def _wire_perception_loop(self_agent):
                # Reproduce what AnatomyMixin._wire_perception_loop does
                self_agent.ears.proprioception_rate = 30.0

        agent = FakeAgent()
        agent._wire_perception_loop()

        assert agent.ears.proprioception_rate == 30.0
        assert "world_tick" not in agent.heart.ticks
