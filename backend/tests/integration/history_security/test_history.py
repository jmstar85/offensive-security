"""Legacy raw database rows must never leak through REST history."""
import json
from typing import Final

import pytest
from sqlalchemy import insert

from app.models.msgchain import MsgChain
from app.models.session import WorkflowMessage

from .conftest import HistoryCase

SECRET: Final = "sk-abc123def456ghi789jkl"


@pytest.mark.parametrize("suffix", ["/messages", "/msgchains", ""])
async def test_history_response_masks_preexisting_raw_rows(
    history_case: HistoryCase, suffix: str,
) -> None:
    # Given historical data inserted below ORM hooks, as it existed before this fix.
    case = history_case
    envelope = json.dumps({
        "ambiguity": 0.25, "blockers": [SECRET], "reasoning": SECRET,
        "draft_plan": {"steps": [], "note": SECRET},
    })
    await case.db.execute(insert(WorkflowMessage).values(
        pentest_session_id=case.session.id, role="assistant", turn_index=1,
        content=envelope, blockers_json={"items": [SECRET], "reasoning": SECRET},
    ))
    await case.db.execute(insert(MsgChain).values(
        pentest_session_id=case.session.id, role_name="generator", status="finished",
        messages_json=[{
            "role": "assistant", "content": envelope,
            "tool_calls": [{"arguments": {"nested": [SECRET]}}],
            "usage": {"input_tokens": 17},
        }],
    ))
    case.session.prompt = SECRET
    case.session.draft_plan_json = {"steps": [], "note": SECRET}
    case.session.ambiguity_override_reason = SECRET
    await case.db.flush()
    # When an authorized caller reads through the actual HTTP surface.
    response = await case.client.get(case.url + suffix, headers=case.headers("member"))
    # Then conversation content, JSON envelopes, and metadata are scrubbed.
    assert response.status_code == 200, response.text
    assert SECRET not in response.text
    assert "REDACTED" in response.text
    if suffix == "/messages":
        assert json.loads(response.json()[0]["content"])["ambiguity"] == 0.25
    if suffix == "/msgchains":
        assert response.json()[0]["messages"][0]["usage"] == {"input_tokens": 17}


async def test_history_masking_preserves_json_for_password_secret(
    history_case: HistoryCase,
) -> None:
    # Given a legacy envelope whose secret matches the password pattern (not an api key).
    case = history_case
    envelope = json.dumps({
        "ambiguity": 0.25,
        "reasoning": "password=supersecret123",
        "blockers": ["password: hunter2abcdef"],
        "draft_plan": {"steps": []},
    })
    await case.db.execute(insert(WorkflowMessage).values(
        pentest_session_id=case.session.id, role="assistant", turn_index=1, content=envelope,
    ))
    await case.db.flush()
    # When an authorized caller reads the history.
    response = await case.client.get(case.url + "/messages", headers=case.headers("member"))
    # Then the envelope is STILL valid JSON with numeric fields intact and no secret.
    assert response.status_code == 200, response.text
    parsed = json.loads(response.json()[0]["content"])
    assert parsed["ambiguity"] == 0.25
    assert "supersecret123" not in response.text
    assert "hunter2abcdef" not in response.text
    assert "REDACTED" in response.text
