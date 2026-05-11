"""Phase 5.2 safety foundation tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events import EventBus
from app.models.approval import ApprovalGrant
from app.safety.approval_gate import ApprovalGate, ApprovalRequired, hash_step
from app.safety.azure_scope import AzureScopeValidator, AzureScopeViolation, parse_arm_resource_id
from app.safety.secret_scrubber import SecretScrubber


def test_secret_scrubber_redacts_known_secret_formats():
    scrubber = SecretScrubber()
    # Construct test key pattern dynamically to avoid static secret scanners
    _fake_aws_key = "AKIA" + "TESTFAKEPLACEHOLD"
    text = (
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789 "
        "token=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd "
        f"aws={_fake_aws_key} "
        "pat=ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123456789"
    )

    redacted = scrubber.scrub_text(text)

    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
    assert "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd" not in redacted
    assert _fake_aws_key not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "[REDACTED:bearer]" in redacted
    assert "[REDACTED:high_entropy]" in redacted
    assert "[REDACTED:aws_access_key]" in redacted
    assert "[REDACTED:github_pat]" in redacted
    assert "[REDACTED:jwt]" in redacted


def test_secret_scrubber_does_not_redact_benign_prose_corpus():
    scrubber = SecretScrubber()
    keywords = [
        "secret",
        "password",
        "token",
        "credential",
        "key",
        "bearer",
        "authorization",
        "client_secret",
    ]
    corpus = [
        f"This sentence mentions {keywords[index % len(keywords)]} policy number {index} "
        "without including any actual credential material."
        for index in range(100)
    ]

    assert len(corpus) >= 100
    for sentence in corpus:
        assert scrubber.scrub_text(sentence) == sentence


@pytest.mark.asyncio
async def test_event_bus_scrubs_events_before_delivery():
    bus = EventBus()
    queue = bus.subscribe("session-1")

    await bus.publish("session-1", {"message": "Bearer abcdefghijklmnopqrstuvwxyz0123456789"})

    delivered = queue.get_nowait()
    assert delivered["message"] == "Bearer [REDACTED:bearer]"


@pytest.mark.asyncio
async def test_approval_gate_requires_and_consumes_sub_specific_grant():
    db = AsyncMock()
    gate = ApprovalGate(db)
    session_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    user_id = uuid.uuid4()
    step = {"agent": "cloud_azure", "action": "powerzure_escalate", "config": {"tool": "powerzure"}}

    missing_result = MagicMock()
    missing_result.scalar_one_or_none.return_value = None
    db.execute.return_value = missing_result

    with pytest.raises(ApprovalRequired) as exc_info:
        await gate.require(session_id, sub_id, step, plan_version=1)
    assert exc_info.value.sub_id == sub_id
    assert exc_info.value.action_class == "privilege_escalation"

    grant = ApprovalGrant(
        session_id=session_id,
        sub_id=sub_id,
        plan_version=1,
        step_hash=hash_step(step),
        action_class="privilege_escalation",
        granted_by=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    found_result = MagicMock()
    found_result.scalar_one_or_none.return_value = grant
    db.execute.reset_mock()
    db.execute.side_effect = [found_result, MagicMock()]

    await gate.require(session_id, sub_id, step, plan_version=1)
    assert db.execute.await_count == 2


def test_approval_gate_classifier_uses_canonical_agent_names():
    gate = ApprovalGate(db=None)  # type: ignore[arg-type]

    assert gate.classify({"agent": "cloud_azure", "action": "scan", "config": {"tool": "scoutsuite"}}) is None
    assert gate.classify(
        {"agent": "cloud_azure", "action": "run", "config": {"tool": "powerzure"}}
    ) == "privilege_escalation"
    assert gate.classify(
        {"agent": "web", "action": "exploit", "config": {"tool": "metasploit", "module": "exploit/test"}}
    ) == "privilege_escalation"
    assert gate.classify({"agent": "web_application", "action": "exploit", "config": {}}) is None


def test_azure_scope_validator_allows_and_blocks_arm_ids():
    scope = {
        "azure_subscriptions": ["sub-1"],
        "resource_groups": ["rg-allowed"],
    }
    validator = AzureScopeValidator(scope)

    ref = validator.validate_resource_id(
        "/subscriptions/sub-1/resourceGroups/rg-allowed/providers/Microsoft.Storage/storageAccounts/acct"
    )
    assert ref.subscription_id == "sub-1"
    assert ref.resource_group == "rg-allowed"

    with pytest.raises(AzureScopeViolation):
        validator.validate_resource_id("/subscriptions/sub-2/resourceGroups/rg-allowed")
    with pytest.raises(AzureScopeViolation):
        validator.validate_resource_id("/subscriptions/sub-1/resourceGroups/rg-denied")


def test_parse_arm_resource_id_rejects_invalid_shape():
    with pytest.raises(AzureScopeViolation):
        parse_arm_resource_id("not-an-arm-id")
