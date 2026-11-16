import pytest
from evidence_helpers import document, original_target, synthetic_context
from pydantic import ValidationError

from submission.evidence_artifacts import inspect_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    EvidenceError,
    PageSelection,
    PdfArtifactInput,
)
from submission.evidence_page_count import assess_page_count
from submission.models import DocumentRole, PdfInput


def test_count_when_actual_original_pdf_has_explicit_partition_verifies(text_pdf):
    # Given
    source = document(text_pdf)
    target = PdfArtifactInput(
        binding=ArtifactBinding(source=source.source, artifact=source.artifacts[0]),
        pdf=PdfInput("file.pdf", text_pdf, DocumentRole.REPORT),
    )
    selection = PageSelection(
        binding_sha256=inspect_artifact(target).binding_sha256,
        basis="original_pdf",
        included_pages=(2,),
        excluded_pages=(1,),
        scope_confirmed=True,
    )
    # When
    result = assess_page_count(target, selection)
    # Then
    assert result.assessment.status == "verified"
    assert result.assessment.count == 1
    assert result.assessment.artifact_page_count == 2


def test_count_when_synthetic_scope_complete_stays_deferred(text_pdf):
    # Given
    target = synthetic_context(text_pdf, ("a", "b")).target
    selection = PageSelection(
        binding_sha256=inspect_artifact(target).binding_sha256,
        basis="declared_submission_pdf",
        included_pages=(1, 2),
        excluded_pages=(),
        scope_confirmed=True,
        declared_submission_sha256=target.binding.artifact.artifact_sha256,
    )
    # When
    result = assess_page_count(target, selection)
    # Then
    assert result.assessment.status == "deferred"
    assert result.assessment.count is None


@pytest.mark.parametrize(
    "update",
    [
        {"included_pages": (1, 1)},
        {"excluded_pages": (1,)},
        {"included_pages": (3,)},
        {"binding_sha256": "0" * 64},
        {"declared_submission_sha256": "0" * 64},
        {"included_pages": (True,)},
        {"scope_confirmed": "false"},
    ],
)
def test_count_when_selection_forged_or_stale_rejects(text_pdf, update):
    # Given
    target = original_target(text_pdf)
    selection = PageSelection(
        binding_sha256=inspect_artifact(target).binding_sha256,
        basis="original_pdf",
        included_pages=(1, 2),
        excluded_pages=(),
        scope_confirmed=True,
    ).model_copy(update=update)
    # When / Then
    with pytest.raises(EvidenceError):
        assess_page_count(target, selection)


@pytest.mark.parametrize(
    "update",
    [
        {"included_pages": None},
        {"excluded_pages": None},
        {"scope_confirmed": False},
        {"included_pages": (1,)},
        {"basis": "unknown"},
        {"basis": "verified_original_layout"},
        {"basis": "declared_submission_pdf"},
    ],
)
def test_count_when_scope_or_basis_unconfirmed_defers(text_pdf, update):
    # Given
    target = original_target(text_pdf)
    selection = PageSelection(
        binding_sha256=inspect_artifact(target).binding_sha256,
        basis="original_pdf",
        included_pages=(1, 2),
        excluded_pages=(),
        scope_confirmed=True,
    ).model_copy(update=update)
    # When
    result = assess_page_count(target, selection)
    # Then
    assert result.assessment.status == "deferred"
    assert result.assessment.count is None


def test_count_when_all_pages_excluded_verifies_zero(text_pdf):
    # Given
    target = original_target(text_pdf)
    selection = PageSelection(
        binding_sha256=inspect_artifact(target).binding_sha256,
        basis="original_pdf",
        included_pages=(),
        excluded_pages=(1, 2),
        scope_confirmed=True,
    )
    # When
    result = assess_page_count(target, selection)
    # Then
    assert result.assessment.status == "verified"
    assert result.assessment.count == 0


def test_count_when_text_unavailable_preserves_physical_count(blank_pdf):
    # Given
    target = original_target(blank_pdf)
    selection = PageSelection(
        binding_sha256=inspect_artifact(target).binding_sha256,
        basis="original_pdf",
        included_pages=(1,),
        excluded_pages=(),
        scope_confirmed=True,
    )
    # When
    result = assess_page_count(target, selection)
    # Then
    assert result.assessment.count == 1
    assert result.assessment.status == "verified"


@pytest.mark.parametrize("pages", [(True,), ("1",), (1.0,)])
def test_selection_when_constructor_coercion_requested_rejects(pages):
    # Given
    digest = "0" * 64
    # When / Then
    with pytest.raises(ValidationError):
        PageSelection(
            binding_sha256=digest,
            basis="original_pdf",
            included_pages=pages,
            excluded_pages=(),
            scope_confirmed=True,
        )
