from typing import assert_never

from submission.document_contracts import PageCountAssessment
from submission.evidence_artifacts import inspect_artifact, strict_model
from submission.evidence_contracts import (
    DEFAULT_EVIDENCE_LIMITS,
    ArtifactInput,
    ArtifactSnapshot,
    BoundPageCountAssessment,
    EvidenceError,
    EvidenceErrorCode,
    EvidenceLimits,
    PageSelection,
)


def validate_selection(selection: PageSelection, snapshot: ArtifactSnapshot) -> bool:
    if selection.binding_sha256 != snapshot.binding_sha256:
        raise EvidenceError(EvidenceErrorCode.ARTIFACT_MISMATCH)
    if (
        selection.declared_submission_sha256 is not None
        and selection.declared_submission_sha256 != snapshot.target_sha256
    ):
        raise EvidenceError(EvidenceErrorCode.ARTIFACT_MISMATCH)
    included, excluded = selection.included_pages, selection.excluded_pages
    for pages in (included, excluded):
        if pages is not None and (
            len(pages) != len(set(pages))
            or any(not 1 <= page <= snapshot.physical_page_count for page in pages)
        ):
            raise EvidenceError(EvidenceErrorCode.INVALID_SELECTION)
    if included is None or excluded is None:
        return False
    if set(included) & set(excluded):
        raise EvidenceError(EvidenceErrorCode.INVALID_SELECTION)
    return selection.scope_confirmed and set(included) | set(excluded) == set(
        range(1, snapshot.physical_page_count + 1)
    )


def basis_reason(
    target: ArtifactInput, selection: PageSelection, snapshot: ArtifactSnapshot
) -> str:
    match snapshot.origin:
        case "synthetic":
            return "synthetic_artifact"
        case "real_pdf":
            pass
        case _:
            assert_never(snapshot.origin)
    if not snapshot.physical_verified or any(
        page.status == "extraction_error" for page in snapshot.pages
    ):
        return "artifact_inspection_incomplete"
    return declared_basis_reason(target, selection, snapshot)


def declared_basis_reason(
    target: ArtifactInput, selection: PageSelection, snapshot: ArtifactSnapshot
) -> str:
    match selection.basis:
        case "unknown":
            return "count_basis_unknown"
        case "verified_original_layout":
            return "original_layout_unverified"
        case "original_pdf":
            match target.binding.artifact.kind:
                case "original_pdf":
                    return "verified_scope_count"
                case "preview_pdf":
                    return "original_artifact_required"
                case _:
                    assert_never(target.binding.artifact.kind)
        case "declared_submission_pdf":
            if selection.declared_submission_sha256 == snapshot.target_sha256:
                return "verified_scope_count"
            return "submission_artifact_unconfirmed"
        case _:
            assert_never(selection.basis)


def assess_page_count(
    target: ArtifactInput,
    selection: PageSelection,
    *,
    limits: EvidenceLimits = DEFAULT_EVIDENCE_LIMITS,
) -> BoundPageCountAssessment:
    selection = strict_model(selection)
    snapshot = inspect_artifact(target, limits=limits)
    scope_complete = validate_selection(selection, snapshot)
    reason = (
        basis_reason(target, selection, snapshot)
        if scope_complete
        else "inclusion_scope_unconfirmed"
    )
    verified = reason == "verified_scope_count"
    return BoundPageCountAssessment(
        binding_sha256=snapshot.binding_sha256,
        assessment=PageCountAssessment(
            basis=selection.basis,
            artifact_sha256=snapshot.target_sha256,
            artifact_page_count=snapshot.physical_page_count
            if snapshot.physical_verified
            else None,
            included_pages=selection.included_pages,
            excluded_pages=selection.excluded_pages,
            count=len(selection.included_pages or ()) if verified else None,
            status="verified" if verified else "deferred",
            reason_code=reason,
        ),
    )
