from typing import Final

from submission.document_contracts import (
    CommonDocument,
    DocumentDiagnostic,
    PageCountAssessment,
    ProcessingStatus,
    StructuralCoverage,
)
from submission.format_containers import PackageMember, member_bytes, parse_xml, read_package
from submission.formats import inspect_document
from submission.hwpx_contract_validation import validate_hwpx_document
from submission.hwpx_parts import inventory_warnings, part_locator, validate_package_order
from submission.hwpx_structure import read_section
from submission.hwpx_structure_types import HwpxReadResult
from submission.input_contracts import (
    DocumentInput,
    FormatInspection,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)

DEFAULT_LIMITS: Final = InputLimits()


def assemble_document(
    result: HwpxReadResult,
    inspection: FormatInspection,
    members: tuple[PackageMember, ...],
    limits: InputLimits,
) -> CommonDocument:
    warnings = result.warnings + inventory_warnings(
        members, inspection.content_members, inspection.source, limits
    )
    readable = any(block.raw_text for block in result.blocks)
    status = (
        ProcessingStatus.PARTIAL
        if warnings
        else ProcessingStatus.COMPLETE
        if readable
        else ProcessingStatus.FAILED
    )
    errors = (
        ()
        if readable
        else (
            DocumentDiagnostic(
                code="empty_content",
                page_number=None,
                source_locator=part_locator(
                    inspection.source, inspection.content_members[0], "/hs:sec[1]"
                ),
            ),
        )
    )
    return validate_hwpx_document(
        CommonDocument(
            source=inspection.source,
            blocks=result.blocks,
            artifacts=(),
            coverage=StructuralCoverage(
                scope="hwpx_xml_structure",
                processed_parts=inspection.content_members,
                omitted_locators=tuple(
                    dict.fromkeys(
                        item.source_locator for item in warnings if item.source_locator is not None
                    )
                ),
            ),
            extraction_status=status,
            rendering_status=ProcessingStatus.NOT_STARTED,
            warnings=warnings,
            typed_errors=errors,
            references=result.references,
            mappings=(),
            page_count=PageCountAssessment(
                basis="unknown",
                artifact_sha256=None,
                artifact_page_count=None,
                status="deferred",
                reason_code="original_layout_unverified",
            ),
        )
    )


def read_hwpx(source: DocumentInput, limits: InputLimits = DEFAULT_LIMITS) -> CommonDocument:
    inspection = inspect_document(source, limits)
    if inspection.source.detected_format != "hwpx":
        raise InputValidationError(
            InputErrorCode.UNSUPPORTED_FORMAT, source.role, inspection.source.detected_format
        )
    members = read_package(source.content, limits)
    try:
        validate_package_order(members, limits)
    except InputValidationError as error:
        raise InputValidationError(error.code, source.role, "hwpx") from None
    result = HwpxReadResult()
    for member in inspection.content_members:
        root = parse_xml(member_bytes(members, member), limits)
        section = read_section(root, member, inspection.source, start_order=len(result.blocks))
        result = HwpxReadResult(
            result.blocks + section.blocks,
            result.warnings + section.warnings,
            result.references + section.references,
        )
    return assemble_document(result, inspection, members, limits)
