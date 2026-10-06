"""HTTP tests exercise JWT authentication and actual project-owner membership."""
import uuid

import pytest

from .conftest import HistoryCase


@pytest.mark.parametrize("actor", ["outsider", "other_team_admin"])
@pytest.mark.parametrize("suffix", ["", "/messages", "/msgchains", "/rescope-pending", "/approval-preview"])
async def test_read_rejected_when_project_belongs_to_other_team(
    history_case: HistoryCase, actor: str, suffix: str,
) -> None:
    # Given a misleading cached team field, the project owner remains authoritative.
    case = history_case
    case.session.team_id = case.users[actor].team_id
    await case.db.flush()
    # When a real cross-team token accesses history.
    response = await case.client.get(case.url + suffix, headers=case.headers(actor))
    # Then no session information is disclosed.
    assert response.status_code in (403, 404), response.text


@pytest.mark.parametrize("actor", ["owner", "member", "team_admin", "admin"])
@pytest.mark.parametrize("suffix", ["", "/messages", "/msgchains", "/rescope-pending"])
async def test_read_allowed_when_member_or_global_admin(
    history_case: HistoryCase, actor: str, suffix: str,
) -> None:
    # Given a legacy session with no cached team ID.
    case = history_case
    # When the owner, teammate or global administrator reads it.
    response = await case.client.get(case.url + suffix, headers=case.headers(actor))
    # Then the established team/admin policy is preserved.
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("suffix", ["", "/messages", "/msgchains", "/rescope-pending"])
async def test_read_missing_session_returns_not_found(
    history_case: HistoryCase, suffix: str,
) -> None:
    # Given a valid global admin token and an unknown session.
    case = history_case
    # When it is requested.
    response = await case.client.get(
        f"/pentest-sessions/{uuid.uuid4()}{suffix}", headers=case.headers("admin"),
    )
    # Then even an empty child collection does not imply a session exists.
    assert response.status_code == 404
