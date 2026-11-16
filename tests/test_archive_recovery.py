from io import BytesIO
from time import monotonic
from typing import Literal, assert_never
from unittest.mock import patch

import pytest
from docx_reader_helpers import make_docx
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from test_semantic_archive import original_setup  # noqa: F401
from test_semantic_archive import setup as archive_setup  # noqa: F401
from test_semantic_routes import check, confirm, extract, provider_response

from submission.input_contracts import DocumentInput
from submission.main import create_app
from submission.models import DocumentRole
from submission.pair_contracts import PairRuntime
from submission.pair_prepare import prepare_role
from submission.semantic_service import draft_view


@pytest.fixture
def setup(request):
    return request.getfixturevalue("archive_setup")


@pytest.mark.parametrize("kind", ["characters", "blocks", "blank", "partial", "unreadable"])
def test_criteria_archive_survives_report_check_ineligibility(setup, tmp_path, blank_pdf, kind):
    # Given: real documents outside AI report eligibility but inside library limits.
    client, store, session, headers, now = setup
    if kind in {"characters", "blocks"}:
        text = "x" * 61000 if kind == "characters" else "section"
        body = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        content = make_docx(body * (501 if kind == "blocks" else 1))
        source = DocumentInput("report.docx", content, DocumentRole.REPORT)
    elif kind == "unreadable":
        source = DocumentInput("report.pdf", b"broken", DocumentRole.REPORT)
    else:
        writer = PdfWriter()
        if kind == "partial":
            writer.append(PdfReader(BytesIO(session.report.original)))
        writer.append(PdfReader(BytesIO(blank_pdf)))
        buffer = BytesIO()
        writer.write(buffer)
        source = DocumentInput("report.pdf", buffer.getvalue(), DocumentRole.REPORT)
    role = prepare_role(source, PairRuntime(), monotonic() + 30)
    if kind == "characters":
        assert sum(len(block.raw_text) for block in role.view.document.blocks) > 60000
    elif kind == "blocks":
        assert len(role.view.document.blocks) > 500
    elif kind == "blank":
        assert not role.view.document.blocks
    elif kind == "partial":
        assert role.view.document.extraction_status == "partial"
    elif kind == "unreadable":
        assert role.view.document is None
    current = store.create("recovery", session.guide, role)
    local = (client, store, current, {**headers, "X-Session-Token": current.token}, now)
    path = tmp_path / "archive.sqlite3"
    with (
        patch("submission.semantic_service.complete", side_effect=provider_response) as provider,
        TestClient(create_app(library_path=path)) as isolated,
    ):
        local = (isolated, *local[1:])
        draft = confirm(local, extract(local).json()["data"])
        assert draft.status_code == 200
        if kind not in {"partial", "unreadable"}:
            rejected = check(local, draft.json()["data"])
            assert rejected.status_code == 422
            assert provider.call_count == 1
        # When: confirmed criteria are saved, then reopened by a fresh application.
        saved = isolated.post(
            f"/api/document-pairs/{current.identifier}/save", headers=local[3], json={}
        )
    assert saved.status_code == 200, saved.text
    receipt = saved.json()["data"]
    assert receipt["has_semantic_archive"]
    assert not receipt["has_check"]
    with TestClient(create_app(library_path=path)) as restarted:
        reopened = restarted.post(
            f"/api/document-library/{receipt['saved_id']}/open", headers=headers
        )
    # Then: the exact confirmed criteria return without a report check.
    assert reopened.status_code == 200, reopened.text
    archive = reopened.json()["data"]["semantic_archive"]
    assert archive["draft"] == draft.json()["data"]
    assert archive["check"] is None


def test_retry_after_lost_confirmation_response_keeps_check_and_version(setup):
    # Given: server committed a confirmation and check, but the client retained its old draft.
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        original = extract(setup).json()["data"]
        confirmed = confirm(setup, original).json()["data"]
        assert check(setup, confirmed).status_code == 200
    _, store, session, _, _ = setup
    with store.lease(session.identifier, session.token) as before:
        state = before.semantic_state
    # When: both a stale retry and repeated unchanged current confirmations arrive.
    for draft in (original, *([confirmed] * 22)):
        response = confirm(setup, draft)
        assert response.status_code == 200
        assert response.json()["data"] == confirmed
    # Then: no revision, version, fingerprint or valid check was consumed.
    with store.lease(session.identifier, session.token) as after:
        assert after.semantic_state == state
        assert after.semantic_revision == before.semantic_revision


@pytest.mark.parametrize("conflict", ["changed", "future", "draft"])
def test_confirmation_retry_rejects_conflicting_request(
    setup, conflict: Literal["changed", "future", "draft"]
):
    # Given: the client has an old draft after confirmation committed.
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        original = extract(setup).json()["data"]
    confirmed = confirm(setup, original).json()["data"]
    match conflict:
        case "changed":
            draft = {
                **original,
                "items": [{**item, "title": "changed"} for item in original["items"]],
            }
        case "future":
            draft = {**confirmed, "revision": confirmed["revision"] + 1}
        case "draft":
            draft = {**confirmed, "draft_id": "different-draft"}
        case unreachable:
            assert_never(unreachable)
    # When: a conflicting retry is submitted.
    response = confirm(setup, draft)
    # Then: the conflict remains visible.
    assert response.status_code == 409


@pytest.mark.parametrize("race", ["delete", "expire", "commit"])
def test_confirmation_noop_rechecks_session_before_returning(
    setup, race: Literal["delete", "expire", "commit"]
):
    # Given: an unchanged confirmed draft with a race immediately before returning.
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        original = extract(setup).json()["data"]
    confirmed = confirm(setup, original).json()["data"]
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

    # When: a retry races with session destruction or a newer semantic commit.
    with patch("submission.semantic_service.draft_view", side_effect=raced_view):
        response = confirm(setup, confirmed)
    # Then: the stale success cannot escape the store's lock-protected check.
    assert response.status_code == (409 if race == "commit" else 404)
