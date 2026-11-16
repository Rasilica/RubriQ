from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Final, assert_never

from submission.compatibility_contracts import (
    AnchorReport,
    CaseReport,
    CompatibilityCase,
    CompatibilityError,
    CompatibilityErrorCode,
    CompatibilityManifest,
    CompatibilityReport,
)
from submission.compatibility_evidence import Comparison, compare_anchor, preview_snapshot
from submission.compatibility_io import read_material, write_private, write_report
from submission.document_contracts import ExtractionCoverage, StructuralCoverage
from submission.evidence_contracts import EvidenceError
from submission.extraction import extract_pdf
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole, PdfInput, UploadError
from submission.pair_contracts import PairError, PairRuntime, PreparedRole
from submission.pair_prepare import prepare_role, remaining

CHARACTER_LIMIT: Final = 200_000


def pdf_text(content: bytes) -> tuple[str, ...]:
    extracted = extract_pdf(PdfInput("document.pdf", content, DocumentRole.REPORT))
    if sum(len(page.text) for page in extracted.pages) > CHARACTER_LIMIT:
        raise CompatibilityError(CompatibilityErrorCode.LIMIT)
    return tuple(page.text for page in extracted.pages)


def compare_anchors(
    case: CompatibilityCase, comparison: Comparison, deadline: float
) -> tuple[AnchorReport, ...]:
    reports: list[AnchorReport] = []
    for anchor in case.anchors:
        _ = remaining(deadline, 180.0)
        reports.append(compare_anchor(anchor, comparison))
    _ = remaining(deadline, 180.0)
    return tuple(reports)


def write_pdfs(output: Path, role: PreparedRole, reference: bytes | None) -> None:
    existing_bytes = sum(path.stat().st_size for path in output.parent.glob("*/*.pdf"))
    if existing_bytes + len(reference or b"") + len(role.pdf or b"") > 256 * 1024 * 1024:
        raise CompatibilityError(CompatibilityErrorCode.LIMIT)
    output.mkdir(mode=0o700)
    if reference is not None:
        write_private(output / "reference.pdf", reference)
    if role.pdf is not None:
        write_private(output / "preview.pdf", role.pdf)


def inspect_case(case: CompatibilityCase, runtime: PairRuntime, output: Path) -> CaseReport:
    base = CaseReport(
        case_id=case.case_id,
        family_id=case.family_id,
        split=case.split,
        provenance=case.provenance,
        format=case.format,
        authoring_app=case.authoring_app,
        authoring_version=case.authoring_version,
        fonts=case.fonts,
        status="material_missing",
        expected_anchors=case.anchors,
    )
    try:
        return evaluate_case(case, runtime, output, base)
    except CompatibilityError as error:
        return base.model_copy(update={"status": "invalid", "error": error.code})
    except (UploadError, PairError, EvidenceError) as error:
        return base.model_copy(update={"status": "invalid", "error": str(error.code)})


def evaluate_case(
    case: CompatibilityCase, runtime: PairRuntime, output: Path, base: CaseReport
) -> CaseReport:
    if case.source is None or not case.source.path.exists():
        return base
    content = read_material(case.source)
    deadline = monotonic() + 180.0
    role = prepare_role(
        DocumentInput(f"source.{case.format}", content, DocumentRole.REPORT),
        runtime,
        deadline,
    )
    if role.view.document is None:
        raise CompatibilityError(role.view.error_code or "read_failed")
    reference = (
        read_material(case.reference)
        if case.reference is not None and case.reference.path.exists()
        else None
    )
    preview_hash = sha256(role.pdf).hexdigest() if role.pdf is not None else None
    if reference is not None and (
        case.reference_origin == "service_preview"
        or (case.format != "pdf" and sha256(reference).hexdigest() == preview_hash)
    ):
        raise CompatibilityError(CompatibilityErrorCode.REFERENCE)
    reference_text = pdf_text(reference) if reference is not None else ()
    review = case.layout_review
    if review is not None and (
        review.source_sha256 != case.source.sha256
        or review.reference_sha256 != (sha256(reference).hexdigest() if reference else None)
        or review.preview_sha256 != preview_hash
    ):
        raise CompatibilityError(CompatibilityErrorCode.REVIEW)
    document = role.view.document
    if sum(len(block.raw_text) for block in document.blocks) > CHARACTER_LIMIT:
        raise CompatibilityError(CompatibilityErrorCode.LIMIT)
    coverage = document.coverage
    match coverage:
        case StructuralCoverage():
            omitted = coverage.omitted_locators
        case ExtractionCoverage():
            omitted = ()
        case _:
            assert_never(coverage)
    comparison = Comparison(document, preview_snapshot(role), reference_text)
    anchors = compare_anchors(case, comparison, deadline)
    write_pdfs(output / case.case_id, role, reference)
    status = "material_missing" if reference is None else "review_pending"
    if review is not None:
        status = "review_recorded"
    return base.model_copy(
        update={
            "status": status,
            "source_sha256": case.source.sha256,
            "reference_sha256": sha256(reference).hexdigest() if reference else None,
            "preview_sha256": preview_hash,
            "reference_pages": len(reference_text) or None,
            "preview_pages": role.view.preview_page_count,
            "extraction_status": role.view.extraction_status.value,
            "rendering_status": role.view.rendering_status.value,
            "warnings": role.view.warnings,
            "error": role.view.error_code,
            "omitted_paths": tuple(locator.path for locator in omitted),
            "diagnostics": document.warnings + document.typed_errors,
            "artifacts": document.artifacts,
            "anchors": anchors,
            "layout_review": review,
        }
    )


def run_manifest(
    manifest: CompatibilityManifest, runtime: PairRuntime, output: Path
) -> CompatibilityReport:
    output.mkdir(mode=0o700)
    report = CompatibilityReport(
        cases=tuple(inspect_case(case, runtime, output) for case in manifest.cases)
    )
    write_report(output, report)
    return report
