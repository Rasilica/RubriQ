from hashlib import sha256
from pathlib import Path
from typing import Final

from submission.compatibility_contracts import (
    CaseReport,
    CompatibilityCase,
    CompatibilityError,
    CompatibilityErrorCode,
    CompatibilityManifest,
    CompatibilityReport,
    MaterialFile,
)
from submission.compatibility_io import read_bounded, read_material, write_private, write_report

MANIFEST_MISMATCH: Final = "review_manifest_mismatch"
MISSING_MATERIAL: Final = "review_material_missing"
PDF_PAIR_COUNT: Final = 2


def verify_current_file(material: MaterialFile | None, digest: str | None) -> None:
    if digest is None:
        if material is not None and material.path.exists():
            raise CompatibilityError(MANIFEST_MISMATCH)
        return
    if material is None or material.sha256 != digest:
        raise CompatibilityError(CompatibilityErrorCode.REVIEW)
    _ = read_material(material)


def validate_case(case: CompatibilityCase, previous: CaseReport) -> None:
    identity = (
        "case_id",
        "family_id",
        "split",
        "provenance",
        "format",
        "authoring_app",
        "authoring_version",
        "fonts",
    )
    if any(getattr(case, name) != getattr(previous, name) for name in identity):
        raise CompatibilityError(MANIFEST_MISMATCH)
    previous_anchors = previous.expected_anchors or previous.anchors
    if tuple((anchor.quote, anchor.locator_path) for anchor in case.anchors) != tuple(
        (anchor.quote, anchor.locator_path) for anchor in previous_anchors
    ):
        raise CompatibilityError(MANIFEST_MISMATCH)
    verify_current_file(case.source, previous.source_sha256)
    verify_current_file(case.reference, previous.reference_sha256)
    if previous.reference_sha256 is not None and case.reference_origin != "authoring_app_export":
        raise CompatibilityError(CompatibilityErrorCode.REVIEW)
    if previous.preview_sha256 is not None and (
        not previous.artifacts or previous.artifacts[0].artifact_sha256 != previous.preview_sha256
    ):
        raise CompatibilityError(CompatibilityErrorCode.REVIEW)
    review = case.layout_review or previous.layout_review
    if review is None:
        return
    if case.source is None or case.reference is None or previous.preview_sha256 is None:
        raise CompatibilityError(MISSING_MATERIAL)
    if (
        previous.status == "invalid"
        or review.source_sha256 != previous.source_sha256
        or review.reference_sha256 != previous.reference_sha256
        or review.preview_sha256 != previous.preview_sha256
    ):
        raise CompatibilityError(CompatibilityErrorCode.REVIEW)


def copy_reviewed_case(
    case: CompatibilityCase, previous: CaseReport, source: Path, output: Path
) -> CaseReport:
    validate_case(case, previous)
    assets = (("reference", previous.reference_sha256), ("preview", previous.preview_sha256))
    copied: list[tuple[str, bytes]] = []
    for name, digest in assets:
        if digest is None:
            continue
        material = MaterialFile(path=source / case.case_id / f"{name}.pdf", sha256=digest)
        copied.append((name, read_material(material)))
    if (
        len(copied) == PDF_PAIR_COUNT
        and case.format != "pdf"
        and sha256(copied[0][1]).digest() == sha256(copied[1][1]).digest()
    ):
        raise CompatibilityError(CompatibilityErrorCode.REFERENCE)
    size = sum(path.stat().st_size for path in output.glob("*/*.pdf"))
    if size + sum(len(content) for _, content in copied) > 256 * 1024 * 1024:
        raise CompatibilityError(CompatibilityErrorCode.LIMIT)
    destination = output / case.case_id
    destination.mkdir(mode=0o700)
    for name, content in copied:
        write_private(destination / f"{name}.pdf", content)
    return (
        previous.model_copy(
            update={"status": "review_recorded", "layout_review": case.layout_review}
        )
        if case.layout_review is not None
        else previous
    )


def record_reviews(
    manifest: CompatibilityManifest, previous: Path, output: Path
) -> CompatibilityReport:
    report = CompatibilityReport.model_validate_json(
        read_bounded(previous / "report.json", 16 * 1024 * 1024)
    )
    ids = tuple(case.case_id for case in report.cases)
    if len(set(ids)) != len(ids) or set(ids) != {case.case_id for case in manifest.cases}:
        raise CompatibilityError(MANIFEST_MISMATCH)
    if not any(case.layout_review is not None for case in manifest.cases):
        raise CompatibilityError(CompatibilityErrorCode.REVIEW)
    output.mkdir(mode=0o700)
    recorded = CompatibilityReport(
        cases=tuple(
            copy_reviewed_case(
                case,
                next(prior for prior in report.cases if prior.case_id == case.case_id),
                previous,
                output,
            )
            for case in manifest.cases
        )
    )
    write_report(output, recorded)
    return recorded
