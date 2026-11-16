from hashlib import sha256

import pytest
from run_compatibility import execute
from test_compatibility import make_case

from submission.compatibility_contracts import (
    CompatibilityError,
    CompatibilityManifest,
    LayoutReview,
)
from submission.compatibility_review import record_reviews
from submission.compatibility_runner import run_manifest
from submission.pair_contracts import PairRuntime


def review_fixture(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    case = case.model_copy(update={"reference": case.source})
    manifest = CompatibilityManifest(cases=(case,))
    previous = tmp_path / "previous"
    original = run_manifest(manifest, PairRuntime(), previous)
    digest = sha256(text_pdf).hexdigest()
    reviewed = case.model_copy(
        update={
            "layout_review": LayoutReview(
                reviewer="tester",
                source_sha256=digest,
                reference_sha256=digest,
                preview_sha256=digest,
                outcome="matches",
                notes="checked stored pages",
            )
        }
    )
    return CompatibilityManifest(cases=(reviewed,)), previous, original


def test_review_reuses_exact_pdf_without_preparation(tmp_path, text_pdf, monkeypatch):
    manifest, previous, original = review_fixture(tmp_path, text_pdf)

    def unexpected(*_):
        pytest.fail("review must not prepare or reconvert")

    monkeypatch.setattr("submission.compatibility_runner.prepare_role", unexpected)
    result = record_reviews(manifest, previous, tmp_path / "reviewed")
    assert result.cases[0].status == "review_recorded"
    assert result.cases[0].artifacts == original.cases[0].artifacts
    assert result.cases[0].anchors == original.cases[0].anchors
    assert result.support_certified is False
    assert result.cases[0].actual_acceptance is False
    assert (tmp_path / "reviewed/sample/preview.pdf").read_bytes() == text_pdf


def test_review_rejects_modified_preview(tmp_path, text_pdf):
    manifest, previous, _ = review_fixture(tmp_path, text_pdf)
    (previous / "sample/preview.pdf").write_bytes(b"changed nondeterministic conversion")
    with pytest.raises(CompatibilityError, match="hash_mismatch"):
        record_reviews(manifest, previous, tmp_path / "reviewed")


def test_review_rejects_changed_source(tmp_path, text_pdf):
    manifest, previous, _ = review_fixture(tmp_path, text_pdf)
    (tmp_path / "source.pdf").write_bytes(b"changed")
    with pytest.raises(CompatibilityError, match="hash_mismatch"):
        record_reviews(manifest, previous, tmp_path / "reviewed")


def test_review_rejects_corpus_relabeling(tmp_path, text_pdf):
    manifest, previous, _ = review_fixture(tmp_path, text_pdf)
    relabeled = manifest.cases[0].model_copy(update={"provenance": "authored"})
    with pytest.raises(CompatibilityError, match="review_manifest_mismatch"):
        record_reviews(CompatibilityManifest(cases=(relabeled,)), previous, tmp_path / "reviewed")


def test_review_preserves_unreviewed_missing_case(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    missing = case.model_copy(update={"case_id": "missing", "source": None, "reference": None})
    prepared = case.model_copy(update={"reference": case.source})
    original = run_manifest(
        CompatibilityManifest(cases=(prepared, missing)), PairRuntime(), tmp_path / "previous"
    )
    digest = sha256(text_pdf).hexdigest()
    reviewed = prepared.model_copy(
        update={
            "layout_review": LayoutReview(
                reviewer="tester",
                source_sha256=digest,
                reference_sha256=digest,
                preview_sha256=digest,
                outcome="matches",
                notes="PDF baseline",
            )
        }
    )
    manifest = CompatibilityManifest(cases=(reviewed, missing))
    result = record_reviews(manifest, tmp_path / "previous", tmp_path / "reviewed")
    assert result.cases[0].status == "review_recorded"
    assert result.cases[1] == original.cases[1]


@pytest.mark.parametrize("change", ["traversal", "duplicate", "extra"])
def test_review_rejects_modified_report_ids_before_asset_lookup(tmp_path, text_pdf, change):
    manifest, previous, original = review_fixture(tmp_path, text_pdf)
    case = original.cases[0]
    entries = (
        (case.model_copy(update={"case_id": "../escape"}),)
        if change == "traversal"
        else (case, case if change == "duplicate" else case.model_copy(update={"case_id": "extra"}))
    )
    (previous / "report.json").write_text(
        original.model_copy(update={"cases": entries}).model_dump_json()
    )
    with pytest.raises(CompatibilityError, match="review_manifest_mismatch"):
        record_reviews(manifest, previous, tmp_path / "reviewed")
    assert not (tmp_path / "reviewed").exists()


def test_review_cli_and_stale_binding(tmp_path, text_pdf, capsys):
    manifest, previous, _ = review_fixture(tmp_path, text_pdf)
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json())
    assert execute(("--record-review", str(path), str(previous), str(tmp_path / "reviewed"))) == 0
    assert '"review_recorded"' in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        record_reviews(manifest, previous, tmp_path / "reviewed")
    case = manifest.cases[0]
    assert case.layout_review is not None
    stale = case.layout_review.model_copy(update={"preview_sha256": "0" * 64})
    with pytest.raises(CompatibilityError, match="stale_layout_review"):
        record_reviews(
            CompatibilityManifest(cases=(case.model_copy(update={"layout_review": stale}),)),
            previous,
            tmp_path / "stale",
        )


@pytest.mark.parametrize("hash_field", ["source_sha256", "reference_sha256", "preview_sha256"])
def test_other_case_review_cannot_preserve_stale_prior_review(tmp_path, text_pdf, hash_field):
    case = make_case(tmp_path, text_pdf)
    prepared = case.model_copy(update={"reference": case.source})
    other = prepared.model_copy(update={"case_id": "other"})
    previous = tmp_path / "previous"
    report = run_manifest(CompatibilityManifest(cases=(prepared, other)), PairRuntime(), previous)
    digest = sha256(text_pdf).hexdigest()
    review = LayoutReview(
        reviewer="tester",
        source_sha256=digest,
        reference_sha256=digest,
        preview_sha256=digest,
        outcome="matches",
        notes="previous PDF review",
    )
    stale_prior = report.cases[1].model_copy(
        update={
            "status": "review_recorded",
            "layout_review": review.model_copy(update={hash_field: "0" * 64}),
        }
    )
    (previous / "report.json").write_text(
        report.model_copy(update={"cases": (report.cases[0], stale_prior)}).model_dump_json()
    )
    manifest = CompatibilityManifest(
        cases=(
            prepared.model_copy(update={"layout_review": review}),
            other,
        )
    )
    with pytest.raises(CompatibilityError, match="stale_layout_review"):
        record_reviews(manifest, previous, tmp_path / "reviewed")
    assert not (tmp_path / "reviewed/report.json").exists()
