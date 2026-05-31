"""SF4: raw_conversation topic access-control gate.

Tests call `verify_raw_conversation_access` directly — no real WebSocket.
The helper is the gating primitive; WebSocket handlers call it before
subscribing to topic='raw_conversation'.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest

from app.models.user import User, UserRole
from app.api.v1.coordinator import verify_raw_conversation_access


def _make_user(role: UserRole) -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = role.value
    u.is_active = True
    return u


def test_non_team_admin_rejected_with_close_4003():
    """Non-admin (MEMBER) user → denied with close code 4003."""
    member = _make_user(UserRole.MEMBER)
    allowed, code = verify_raw_conversation_access(member, accept_raw=True)
    assert not allowed
    assert code == 4003


def test_accept_raw_false_rejected_with_close_4003():
    """TEAM_ADMIN but accept_raw=False → denied with close code 4003."""
    team_admin = _make_user(UserRole.TEAM_ADMIN)
    allowed, code = verify_raw_conversation_access(team_admin, accept_raw=False)
    assert not allowed
    assert code == 4003


def test_team_admin_with_accept_raw_true_receives_raw():
    """TEAM_ADMIN with accept_raw=True → allowed, no close code."""
    team_admin = _make_user(UserRole.TEAM_ADMIN)
    allowed, code = verify_raw_conversation_access(team_admin, accept_raw=True)
    assert allowed
    assert code is None


def test_admin_with_accept_raw_true_receives_raw():
    """ADMIN with accept_raw=True → allowed, no close code."""
    admin = _make_user(UserRole.ADMIN)
    allowed, code = verify_raw_conversation_access(admin, accept_raw=True)
    assert allowed
    assert code is None


def test_no_cross_topic_bleed():
    """Subscriber on topic='conversation' must NOT receive 'role_turn_raw' messages."""
    from app.core.events import EventBus

    bus = EventBus()
    session_id = str(uuid.uuid4())

    # Subscribe only to 'conversation' topic
    conv_queue = bus.subscribe(session_id, topics={"conversation"})

    # Publish a raw_conversation event
    asyncio.run(bus.publish(session_id, {"type": "role_turn_raw", "content": "secret"}, topic="raw_conversation"))

    # The conversation subscriber queue must be empty — no bleed
    assert conv_queue.empty()

    # Publish a conversation event — it SHOULD arrive
    asyncio.run(bus.publish(session_id, {"type": "role_turn", "content": "clean"}, topic="conversation"))
    assert not conv_queue.empty()
    event = conv_queue.get_nowait()
    assert event["type"] == "role_turn"
