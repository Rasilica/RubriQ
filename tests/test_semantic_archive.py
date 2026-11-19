import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_semantic_routes import check, confirm, extract, provider_response
from test_semantic_routes import setup as original_setup  # noqa: F401

from submission.library_contracts import LibraryError, SnapshotManifest
from submission.library_store import LibraryStore, digest, encode
from submission.main import create_app
from submission.pair_contracts import PairError
from submission.pair_store import PairStore
from submission.review_contracts import ReviewError
from submission.review_logic import confirm_session
from submission.semantic_archive import capture
from submission.semantic_contracts import SemanticError
from submission.semantic_service import current_state


def test_reopened_criteria_get_and_check_reuse_saved_draft_without_extraction(setup):
    client, store, session, headers, now = setup
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
    with store.lease(session.identifier, session.token) as current:
        archive = capture(current)
    reopened = store.create(
        session.project, session.guide, session.report, semantic_archive=archive
    )
    reopened_headers = {**headers, "X-Session-Token": reopened.token}
    reopened_setup = client, store, reopened, reopened_headers, now
    with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
        read = client.get(
            f"/api/document-pairs/{reopened.identifier}/ai/criteria",
            headers=reopened_headers,
            params={"draft_id": draft["draft_id"]},
        )
        assert read.status_code == 200
        assert read.json()["data"] == draft
        call.assert_not_called()
        with store.lease(reopened.identifier, reopened.token) as current:
            assert current.semantic_state is None
        assert check(reopened_setup, draft).status_code == 200
        assert call.call_count == 1
        assert "expected_items" in json.loads(call.call_args.args[2])
    with store.lease(reopened.identifier, reopened.token) as current:
        assert current.semantic_state.check is not None
        assert current.semantic_archive is None


@pytest.mark.parametrize("version", [7, 20])
def test_reopened_confirmation_retains_saved_version_number_and_cap(setup, version):
    _, store, session, _, _ = setup
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        confirm(setup, extract(setup).json()["data"])
    with store.lease(session.identifier, session.token) as current:
        live = current.semantic_state
        latest = live.review.versions[-1].model_copy(update={"version": version})
        review = live.review.model_copy(update={"versions": (latest,)})
        edited = review.model_copy(update={"revision": review.revision + 1})
    if version == 20:
        with pytest.raises(ReviewError, match="version_limit"):
            confirm_session(edited, edited.revision, 20)
    else:
        assert confirm_session(edited, edited.revision, 20).versions[-1].version == 8


def test_archive_fallback_rejects_wrong_id_and_does_not_override_live_state(setup):
    _, store, session, _, _ = setup
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
    with store.lease(session.identifier, session.token) as current:
        archive = capture(current)
        reopened = replace(current, semantic_state=None, semantic_archive=archive)
        with pytest.raises(SemanticError, match="ai_stale_draft"):
            current_state(reopened, "wrong-id")
        another = current.semantic_state.model_copy(
            update={
                "review": current.semantic_state.review.model_copy(
                    update={"session_id": "new-live-id"}
                )
            }
        )
        with pytest.raises(SemanticError, match="ai_stale_draft"):
            current_state(replace(reopened, semantic_state=another), draft["draft_id"])
        corrupt = archive.model_copy(
            update={"draft": archive.draft.model_copy(update={"guide_sha256": "0" * 64})}
        )
        with pytest.raises(LibraryError, match="library_corrupt"):
            current_state(replace(reopened, semantic_archive=corrupt), draft["draft_id"])


@pytest.fixture
def setup(request):
    client, store, session, headers, now = request.getfixturevalue("original_setup")
    roles = tuple(
        replace(
            role,
            view=role.view.model_copy(
                update={
                    "rendering_status": role.view.document.rendering_status,
                    "preview_page_count": role.view.document.page_count.artifact_page_count,
                    "artifact_kind": "original_pdf",
                }
            ),
            pdf=role.original,
        )
        for role in (session.guide, session.report)
    )
    fixed = store.create(session.project, *roles)
    return client, store, fixed, {**headers, "X-Session-Token": fixed.token}, now


def test_authoritative_archive_survives_restart(setup, tmp_path):
    _, store, session, headers, _ = setup
    path = tmp_path / "archive.sqlite3"
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        result = check(setup, draft).json()["data"]
    with store.lease(session.identifier, session.token) as current:
        saved = LibraryStore(path).save(current, ())
    with (
        patch("submission.semantic_service.complete", side_effect=AssertionError("AI called")),
        TestClient(create_app(library_path=path)) as restarted,
    ):
        response = restarted.post(f"/api/document-library/{saved.saved_id}/open", headers=headers)
    assert response.status_code == 200
    archive = response.json()["data"]["semantic_archive"]
    assert archive["draft"] == draft
    assert archive["check"] == result
    assert "test-key" not in path.read_bytes().decode(errors="ignore")
    assert session.token not in path.read_bytes().decode(errors="ignore")
    assert saved.has_semantic_archive
    assert saved.has_check


def test_reconfirm_invalidates_check_and_snapshots_immutable(setup, tmp_path):
    _, store, session, _, _ = setup
    library = LibraryStore(tmp_path / "archive.sqlite3")
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        assert check(setup, draft).status_code == 200
        with store.lease(session.identifier, session.token) as current:
            first = library.save(current, ())
        edited = {**draft, "items": [{**item, "title": "edited"} for item in draft["items"]]}
        updated = confirm(setup, edited).json()["data"]
        with store.lease(session.identifier, session.token) as current:
            second = library.save(current, ())
    assert first.saved_id != second.saved_id
    assert library.load(first.saved_id).semantic_archive.check is not None
    restored = library.load(second.saved_id).semantic_archive
    assert restored.check is None
    assert restored.draft == type(restored.draft).model_validate(updated)


def test_browser_claims_not_archived(setup, tmp_path):
    _, store, session, headers, _ = setup
    with (
        patch("submission.library_routes.library_path", return_value=tmp_path / "archive.sqlite3"),
        patch("submission.pair_routes.PairStore", return_value=store),
        TestClient(create_app()) as isolated,
    ):
        response = isolated.post(
            f"/api/document-pairs/{session.identifier}/save",
            headers=headers,
            json={"semantic_archive": {"check": "forged"}},
        )
    assert response.status_code == 200
    assert response.json()["data"]["has_semantic_archive"] is False


def test_legacy_manifest_and_reopened_deduplication(setup, tmp_path):

    _, _, session, _, _ = setup
    library = LibraryStore(tmp_path / "archive.sqlite3")
    saved = library.save(session, ())
    with closing(sqlite3.connect(library.path)) as connection, connection:
        encoded = connection.execute("SELECT manifest FROM snapshots").fetchone()[0]
    assert "semantic_archive" not in encoded
    assert library.load(saved.saved_id).semantic_archive is None
    assert library.save(session, ()).already_saved


@pytest.mark.parametrize("change", ["criteria", "report", "scope"])
def test_mismatched_archive_rejected_even_with_rehashed_manifest(setup, tmp_path, change):

    _, store, session, _, _ = setup
    library = LibraryStore(tmp_path / "archive.sqlite3")
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        assert check(setup, draft).status_code == 200
    with store.lease(session.identifier, session.token) as current:
        saved = library.save(current, ())
    with closing(sqlite3.connect(library.path)) as connection, connection:
        encoded = connection.execute("SELECT manifest FROM snapshots").fetchone()[0]
        manifest = SnapshotManifest.model_validate_json(encoded)
        archive = manifest.semantic_archive
        changes = {
            "criteria": {"criteria_sha256": "0" * 64},
            "report": {"report_source_sha256": "0" * 64},
            "scope": {"reviewed_block_ids": ("absent-block",)},
        }
        result = archive.check.result.model_copy(update=changes[change])
        altered = archive.model_copy(
            update={"check": archive.check.model_copy(update={"result": result})}
        )
        manifest = manifest.model_copy(update={"semantic_archive": altered})
        connection.execute(
            "UPDATE snapshots SET manifest=?,digest=?", (encode(manifest), digest(manifest))
        )
    with pytest.raises(LibraryError, match="library_corrupt"):
        library.load(saved.saved_id)


def test_new_draft_does_not_archive_previous_check(setup, tmp_path):
    _, store, session, _, _ = setup
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        assert check(setup, draft).status_code == 200
        assert extract(setup).status_code == 200
    library = LibraryStore(tmp_path / "archive.sqlite3")
    with store.lease(session.identifier, session.token) as current:
        saved = library.save(current, ())
    assert not saved.has_semantic_archive


def test_reopened_archive_deduplicates_and_counts_toward_session_limit(setup, tmp_path):

    _, store, session, _, _ = setup
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        assert check(setup, draft).status_code == 200
    library = LibraryStore(tmp_path / "archive.sqlite3")
    with store.lease(session.identifier, session.token) as current:
        saved = library.save(current, ())
    loaded = library.load(saved.saved_id)
    reopened_store = PairStore()
    restored = reopened_store.create(
        "semantic", loaded.guide, loaded.report, semantic_archive=loaded.semantic_archive
    )
    receipt = library.save(restored, ())
    assert receipt.already_saved
    assert receipt.saved_id == saved.saved_id
    reopened_store.semantic_commit(restored.identifier, restored.token, 0, current.semantic_state)
    with reopened_store.lease(restored.identifier, restored.token) as fresh:
        assert fresh.view().semantic_archive is None
    limited = PairStore(max_bytes=loaded.guide.size + loaded.report.size)
    with pytest.raises(PairError):
        limited.create(
            "semantic", loaded.guide, loaded.report, semantic_archive=loaded.semantic_archive
        )


def cited_response(request, instructions, raw, key):
    completion = provider_response(request, instructions, raw, key)
    data = json.loads(completion.suggestion)
    if "reviewed_block_ids" in data:
        block = json.loads(raw)["blocks"][0]
        data["items"][0]["evidence"] = [
            {
                "citation": {
                    "block_id": block["block_id"],
                    "char_range": {"start": 0, "end": len(block["raw_text"])},
                    "quote": block["raw_text"],
                },
                "evidence_role": "content",
                "relation": "본문 인용",
            }
        ]
        data["items"][0]["proposed_judgment"] = "evidence_found"
    return completion.model_copy(update={"suggestion": json.dumps(data)})


def test_verified_citation_roundtrip_and_forgery_rejection(setup, tmp_path):
    _, store, session, _, _ = setup
    library = LibraryStore(tmp_path / "archive.sqlite3")
    with patch("submission.semantic_service.complete", side_effect=cited_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        response = check(setup, draft)
        assert response.status_code == 200
    with store.lease(session.identifier, session.token) as current:
        saved = library.save(current, ())
    loaded = library.load(saved.saved_id)
    archive = loaded.semantic_archive
    row = archive.check.result.items[0]
    assert row.evidence[0].citation.quote
    wrong = row.evidence[0].citation.model_copy(update={"quote": "forged quote"})
    item = row.model_copy(
        update={"evidence": (row.evidence[0].model_copy(update={"citation": wrong}),)}
    )
    altered = archive.model_copy(
        update={
            "check": archive.check.model_copy(
                update={
                    "result": archive.check.result.model_copy(
                        update={"items": (item, *archive.check.result.items[1:])}
                    ),
                }
            )
        }
    )
    with pytest.raises(LibraryError, match="library_corrupt"):
        library.save(replace(session, semantic_archive=altered), ())
