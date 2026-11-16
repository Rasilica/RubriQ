from typing import Literal, assert_never
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_semantic_archive import original_setup  # noqa: F401
from test_semantic_archive import setup as archive_setup  # noqa: F401
from test_semantic_routes import check, confirm, extract, provider_response

from submission.library_store import LibraryStore
from submission.main import create_app
from submission.semantic_service import draft_view


@pytest.fixture
def setup(request):
    return request.getfixturevalue("archive_setup")


def retrieve(setup, draft_id, **overrides):
    client, _, session, headers, _ = setup
    return client.get(
        f"/api/document-pairs/{session.identifier}/ai/criteria",
        params={"draft_id": draft_id},
        **{"headers": headers, **overrides},
    )


@pytest.mark.parametrize("phase", ["draft", "confirmed", "checked"])
def test_current_criteria_returns_exact_snapshot_without_mutation_or_provider(setup, phase):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        expected = extract(setup).json()["data"]
        if phase != "draft":
            expected = confirm(setup, expected).json()["data"]
        if phase == "checked":
            assert check(setup, expected).status_code == 200
    _, store, session, headers, _ = setup
    headers_without_key = {key: value for key, value in headers.items() if key != "X-AI-API-Key"}
    with store.lease(session.identifier, session.token) as before:
        state, revision = before.semantic_state, before.semantic_revision
    with patch("submission.semantic_service.complete") as provider:
        response = retrieve(setup, expected["draft_id"], headers=headers_without_key)
    assert response.status_code == 200
    assert response.json()["data"] == expected
    assert response.headers["cache-control"] == "no-store"
    provider.assert_not_called()
    with store.lease(session.identifier, session.token) as after:
        assert after.semantic_state == state
        assert after.semantic_revision == revision


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 403),
        ({"X-Local-Client": "prepare"}, 404),
        ({"X-Local-Client": "prepare", "X-Session-Token": "wrong"}, 404),
    ],
)
def test_current_criteria_requires_client_and_session_auth(setup, headers, status):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
    with patch("submission.semantic_service.complete") as provider:
        response = retrieve(setup, draft["draft_id"], headers=headers)
    assert response.status_code == status
    assert "data" not in response.json()
    provider.assert_not_called()


@pytest.mark.parametrize("draft_id", ["", "x" * 129])
def test_current_criteria_bounds_draft_id(setup, draft_id):
    response = retrieve(setup, draft_id)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("kind", ["absent", "wrong", "superseded"])
def test_current_criteria_requires_existing_same_draft(setup, kind):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft_id = "missing"
        if kind != "absent":
            draft_id = extract(setup).json()["data"]["draft_id"]
        if kind == "superseded":
            assert extract(setup).status_code == 200
        elif kind == "wrong":
            draft_id = "different"
    response = retrieve(setup, draft_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ai_stale_draft"


@pytest.mark.parametrize("race", ["delete", "expire", "commit"])
def test_current_criteria_rechecks_lifetime_and_revision_before_return(
    setup, race: Literal["delete", "expire", "commit"]
):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
    _, store, session, _, now = setup

    def raced_view(current, state):
        result = draft_view(current, state)
        match race:
            case "delete":
                store.delete(session.identifier, session.token)
            case "expire":
                now[0] = 601
            case "commit":
                store.semantic_commit(
                    session.identifier, session.token, current.semantic_revision, state
                )
            case unreachable:
                assert_never(unreachable)
        return result

    with patch("submission.semantic_service.draft_view", side_effect=raced_view):
        response = retrieve(setup, draft["draft_id"])
    assert response.status_code == (409 if race == "commit" else 404)
    assert "data" not in response.json()


def test_current_criteria_rejects_expired_session_before_reading(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
    setup[4][0] = 601
    response = retrieve(setup, draft["draft_id"])
    assert response.status_code == 404


def test_current_criteria_enforces_origin_host_and_request_quota(setup):
    _, _, _, headers, _ = setup
    response = retrieve(setup, "draft", headers={**headers, "Origin": "https://example.com"})
    assert response.status_code == 403
    response = retrieve(setup, "draft", headers={**headers, "Host": "example.com"})
    assert response.status_code == 400
    with patch("submission.result_rate_limit.ResultRateLimit.retry_after", return_value=3):
        response = retrieve(setup, "draft")
    assert response.status_code == 429
    assert response.headers["cache-control"] == "no-store"


def test_lost_confirmation_then_edited_retry_recovers_and_archive_survives_restart(setup, tmp_path):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        original = extract(setup).json()["data"]
    committed = confirm(setup, original).json()["data"]
    local = {**original, "items": [{**item, "title": "local edit"} for item in original["items"]]}
    assert confirm(setup, local).status_code == 409
    with patch("submission.semantic_service.complete") as provider:
        recovered = retrieve(setup, original["draft_id"]).json()["data"]
        assert recovered == committed
        confirmed = confirm(setup, {**local, "revision": recovered["revision"]})
    provider.assert_not_called()
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["items"][0]["title"] == "local edit"
    _, store, session, headers, _ = setup
    path = tmp_path / "archive.sqlite3"
    with store.lease(session.identifier, session.token) as current:
        saved = LibraryStore(path).save(current, ())
    with (
        patch("submission.semantic_service.complete") as provider,
        TestClient(create_app(library_path=path)) as restarted,
    ):
        reopened = restarted.post(f"/api/document-library/{saved.saved_id}/open", headers=headers)
    assert reopened.status_code == 200
    assert reopened.json()["data"]["semantic_archive"]["draft"] == confirmed.json()["data"]
    provider.assert_not_called()
