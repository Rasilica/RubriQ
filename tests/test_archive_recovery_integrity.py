import sqlite3
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

import pytest
from test_semantic_archive import original_setup  # noqa: F401
from test_semantic_archive import setup as archive_setup  # noqa: F401
from test_semantic_routes import confirm, extract, provider_response

from submission.library_contracts import LibraryError, SnapshotManifest
from submission.library_store import LibraryStore, digest, encode
from submission.report_check_contracts import CriteriaContext
from submission.report_check_validation import criteria_fingerprint


@pytest.fixture
def setup(request):
    return request.getfixturevalue("archive_setup")


@pytest.mark.parametrize("change", ["guide", "citation", "identity", "fingerprint"])
def test_criteria_only_archive_rejects_forgery_on_save_and_load(setup, tmp_path, change):
    # Given: an authentic criteria-only archive, altered and rehashed by a local DB writer.
    _, store, session, _, _ = setup
    library = LibraryStore(tmp_path / "integrity.sqlite3")
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        assert confirm(setup, extract(setup).json()["data"]).status_code == 200
    with store.lease(session.identifier, session.token) as current:
        saved = library.save(current, ())
    archive = library.load(saved.saved_id).semantic_archive
    original = archive.original_draft
    criteria = archive.criteria
    if change == "guide":
        original = original.model_copy(update={"source_sha256": "0" * 64})
    elif change == "citation":
        requirement = original.requirements[0]
        citation = requirement.citations[0].model_copy(update={"quote": "forged"})
        requirement = requirement.model_copy(update={"citations": (citation,)})
        original = original.model_copy(
            update={"requirements": (requirement, *original.requirements[1:])}
        )
    elif change == "identity":
        item = criteria.items[0].model_copy(update={"requirement_id": "forged"})
        criteria = criteria.model_copy(update={"items": (item, *criteria.items[1:])})
    fingerprint = criteria_fingerprint(
        CriteriaContext(
            guide=session.guide.view.document, original_draft=original, criteria=criteria
        )
    )
    draft = archive.draft.model_copy(
        update={
            "requirements": original.requirements,
            "items": criteria.items,
            "criteria_sha256": "0" * 64 if change == "fingerprint" else fingerprint,
        }
    )
    forged = archive.model_copy(
        update={"draft": draft, "original_draft": original, "criteria": criteria}
    )
    # When: the forged archive crosses either save or load boundary.
    with pytest.raises(LibraryError, match="library_corrupt"):
        library.save(replace(session, semantic_archive=forged), ())
    with closing(sqlite3.connect(library.path)) as connection, connection:
        encoded = connection.execute("SELECT manifest FROM snapshots").fetchone()[0]
        manifest = SnapshotManifest.model_validate_json(encoded).model_copy(
            update={"semantic_archive": forged}
        )
        connection.execute(
            "UPDATE snapshots SET manifest=?,digest=?", (encode(manifest), digest(manifest))
        )
    # Then: a matching manifest digest cannot bypass semantic binding validation.
    with pytest.raises(LibraryError, match="library_corrupt"):
        library.load(saved.saved_id)
