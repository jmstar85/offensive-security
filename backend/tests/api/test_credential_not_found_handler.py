"""Regression (Bug B): a CredentialNotFound reaching the HTTP layer must map to
a clean, actionable 400 — not a raw 500 — and must never leak the user_id from
the exception message.

Live repro before the fix: an Assistant turn (or a flag-ON interview) on a
session whose provider has no stored per-user credential fails closed with
CredentialNotFound (correct — it never fabricates a result), but the exception
propagated uncaught to Starlette's error middleware → HTTP 500. The app-level
handler in app.main maps it to 400 {"code": "credential_required"}.
"""
from __future__ import annotations

import json

from app.main import _credential_not_found_handler
from app.orchestrator.llm.credential_resolver import CredentialNotFound


async def test_credential_not_found_maps_to_clean_400_without_leaking_user_id():
    exc = CredentialNotFound(
        "No active credential found for provider='anthropic' "
        "user_id=UUID('8ce408ec-938d-43c4-90ac-fced3a3cf377')"
    )

    resp = await _credential_not_found_handler(None, exc)

    assert resp.status_code == 400
    body = json.loads(bytes(resp.body))
    assert body["code"] == "credential_required"
    # The client-facing detail must not echo the raw exception (which carries the
    # user_id) — no tenant identifier leakage.
    assert "user_id" not in body["detail"]
    assert "8ce408ec" not in body["detail"]
