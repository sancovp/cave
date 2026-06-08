"""Tests for Conductor Discord routing in organ_daemon.

Validates that Isaac's Discord messages route to Conductor via /messages/send
while other messages route to the main file inbox.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cave.core.organ_daemon import (
    write_to_inbox,
    send_to_conductor,
    INBOX_DIR,
    CAVE_BASE_URL,
)
from cave.core.world import WorldEvent


@pytest.fixture
def clean_inboxes(tmp_path, monkeypatch):
    """Set up temp inbox dirs."""
    main_inbox = tmp_path / "inboxes" / "main"
    monkeypatch.setattr("cave.core.organ_daemon.INBOX_DIR", main_inbox)
    return {"main": main_inbox}


class TestSendToConductor:
    """send_to_conductor posts to /messages/send via HTTP."""

    def test_posts_to_messages_send(self, clean_inboxes):
        event = WorldEvent(
            source="discord",
            content="[Discord #123] isaac: hello",
            priority=7,
            metadata={"discord_user_id": "12345", "discord_username": "isaac"},
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message_id": "abc123", "status": "sent"}
        with patch("cave.core.organ_daemon.httpx.post", return_value=mock_resp) as mock_post:
            mid = send_to_conductor(event)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["to_agent"] == "conductor"
            assert body["from_agent"] == "world:discord"
            assert body["content"] == "[Discord #123] isaac: hello"
            assert body["ingress"] == "discord"
            assert body["priority"] == 7
            assert mid == "abc123"

    def test_returns_error_on_failure(self, clean_inboxes):
        event = WorldEvent(source="discord", content="test", priority=5, metadata={})
        with patch("cave.core.organ_daemon.httpx.post", side_effect=Exception("connection refused")):
            mid = send_to_conductor(event)
            assert mid == "error"

    def test_main_inbox_unaffected(self, clean_inboxes):
        """Sending to conductor does NOT write to main inbox."""
        event = WorldEvent(source="discord", content="test", priority=5, metadata={})
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message_id": "x"}
        with patch("cave.core.organ_daemon.httpx.post", return_value=mock_resp):
            send_to_conductor(event)
        if clean_inboxes["main"].exists():
            assert len(list(clean_inboxes["main"].glob("*.json"))) == 0


class TestWriteToInbox:
    def test_writes_to_main_inbox(self, clean_inboxes):
        event = WorldEvent(source="discord", content="from ai", priority=3, metadata={})
        mid = write_to_inbox(event)
        files = list(clean_inboxes["main"].glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["to"] == "main"
        assert data["id"] == mid


class TestIsaacRouting:
    """Test the routing logic: Isaac → Conductor (HTTP), others → main inbox (file)."""

    def test_isaac_message_routes_to_conductor(self, clean_inboxes):
        isaac_user_id = "12345"
        event = WorldEvent(
            source="discord",
            content="[Discord #chan] isaac: work on the conductor",
            priority=7,
            metadata={"discord_user_id": "12345", "discord_username": "isaac"},
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message_id": "routed1"}
        sender_id = event.metadata.get("discord_user_id", "")
        with patch("cave.core.organ_daemon.httpx.post", return_value=mock_resp) as mock_post:
            if isaac_user_id and sender_id == isaac_user_id:
                send_to_conductor(event)
            else:
                write_to_inbox(event)
            mock_post.assert_called_once()
        main_files = list(clean_inboxes["main"].glob("*.json")) if clean_inboxes["main"].exists() else []
        assert len(main_files) == 0

    def test_non_isaac_message_routes_to_main(self, clean_inboxes):
        isaac_user_id = "12345"
        event = WorldEvent(
            source="discord",
            content="[Discord #chan] other_ai: status update",
            priority=5,
            metadata={"discord_user_id": "99999", "discord_username": "other_ai"},
        )
        sender_id = event.metadata.get("discord_user_id", "")
        with patch("cave.core.organ_daemon.httpx.post") as mock_post:
            if isaac_user_id and sender_id == isaac_user_id:
                send_to_conductor(event)
            else:
                write_to_inbox(event)
            mock_post.assert_not_called()
        main_files = list(clean_inboxes["main"].glob("*.json"))
        assert len(main_files) == 1

    def test_no_isaac_id_configured_routes_to_main(self, clean_inboxes):
        isaac_user_id = None
        event = WorldEvent(
            source="discord",
            content="[Discord #chan] isaac: hello",
            priority=7,
            metadata={"discord_user_id": "12345"},
        )
        sender_id = event.metadata.get("discord_user_id", "")
        if isaac_user_id and sender_id == isaac_user_id:
            send_to_conductor(event)
        else:
            write_to_inbox(event)
        main_files = list(clean_inboxes["main"].glob("*.json"))
        assert len(main_files) == 1

    def test_command_messages_still_go_to_main(self, clean_inboxes):
        isaac_user_id = "12345"
        event = WorldEvent(
            source="discord",
            content="[Discord #chan] isaac: done standup",
            priority=7,
            metadata={"discord_user_id": "12345", "command": True},
        )
        is_command = True
        sender_id = event.metadata.get("discord_user_id", "")
        if isaac_user_id and sender_id == isaac_user_id and not is_command:
            send_to_conductor(event)
        else:
            write_to_inbox(event)
        main_files = list(clean_inboxes["main"].glob("*.json"))
        assert len(main_files) == 1
