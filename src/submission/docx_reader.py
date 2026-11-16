from typing import Final

from submission.document_contracts import (
    CommonDocument,
    DocumentDiagnostic,
    PageCountAssessment,
    ProcessingStatus,
    SourceLocator,
    SourceReference,
    StructuralCoverage,
)
from submission.docx_contract_validation import validate_docx_document
from submission.docx_parts import (
    OFFICE_NS,
    DocxPackage,
    PartRelationship,
    ReaderPart,
    diagnostic,
    header_part,
    inventory_warnings,
    locator,
    note_key,
    note_parts,
    root_path,
)
from submission.docx_structure import read_region
from submission.docx_structure_types import (
    PendingReference,
    RegionPosition,
    StructureResult,
    child_paths,
)
from submission.docx_validation import WORD_NS
from submission.format_containers import read_package
from submission.formats import inspect_document
from submission.input_contracts import (
    DocumentInput,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)

DEFAULT_LIMITS: Final = InputLimits()


def read_parts(
    package: DocxPackage, parts: tuple[ReaderPart, ...], previous: StructureResult
) -> StructureResult:
    result = previous
    for part in parts:
        current = read_region(
            part.node,
            part.member,
            package.source,
            part.kind,
            position=RegionPosition(root_path=part.path, start_order=len(result.blocks)),
        )
        result = StructureResult(
            blocks=result.blocks + current.blocks,
            warnings=result.warnings + current.warnings,
            references=result.references + current.references,
        )
    return result


def referenced_headers(
    package: DocxPackage,
    relations: tuple[PartRelationship, ...],
    references: tuple[PendingReference, ...],
) -> tuple[ReaderPart, ...]:
    parts: tuple[ReaderPart, ...] = ()
    for reference in references:
        if reference.kind == "footnote" or not reference.key:
            continue
        relation = next((item for item in relations if item.identifier == reference.key), None)
        if relation is None:
            continue
        part = header_part(package, relation, reference.kind)
        if part is not None and not any(
            (item.member, item.kind) == (part.member, part.kind) for item in parts
        ):
            parts += (part,)
    return parts


def reference_target(
    package: DocxPackage,
    reference: PendingReference,
    parts: tuple[ReaderPart, ...],
    relations: tuple[PartRelationship, ...],
) -> SourceLocator | None:
    if not reference.key:
        return None
    if reference.kind == "footnote":
        target = next(
            (
                item
                for item in parts
                if item.kind == "footnote" and item.key == note_key(reference.key)
            ),
            None,
        )
    else:
        relation = next((item for item in relations if item.identifier == reference.key), None)
        target = next(
            (
                item
                for item in parts
                if item.kind == reference.kind
                and relation is not None
                and item.member == relation.target
            ),
            None,
        )
        if relation is not None and relation.relation_type != f"{OFFICE_NS}/{reference.kind}":
            target = None
    return locator(package.source, target.member, target.path) if target is not None else None


def resolve_references(
    package: DocxPackage,
    pending: tuple[PendingReference, ...],
    parts: tuple[ReaderPart, ...],
    relations: tuple[PartRelationship, ...],
) -> tuple[SourceReference, ...]:
    return tuple(
        SourceReference(
            kind=item.kind,
            source_locator=item.source_locator,
            source_block_id=item.source_block_id,
            source_char_offset=item.source_char_offset,
            target_locator=target,
            status="resolved" if target is not None else "unresolved",
        )
        for item in pending
        for target in (reference_target(package, item, parts, relations),)
    )


def assemble_document(
    package: DocxPackage,
    result: StructureResult,
    processed: tuple[str, ...],
    references: tuple[SourceReference, ...],
) -> CommonDocument:
    unresolved = tuple(
        DocumentDiagnostic(
            code="invalid_reference", page_number=None, source_locator=item.source_locator
        )
        for item in references
        if item.status == "unresolved"
    )
    warnings = result.warnings + unresolved + inventory_warnings(package, processed)
    has_text = any(block.raw_text for block in result.blocks)
    status = (
        ProcessingStatus.PARTIAL
        if warnings
        else ProcessingStatus.COMPLETE
        if has_text
        else ProcessingStatus.FAILED
    )
    errors = (
        ()
        if has_text
        else (
            DocumentDiagnostic(
                code="empty_content",
                page_number=None,
                source_locator=locator(package.source, package.main_part, "/w:document[1]"),
            ),
        )
    )
    return validate_docx_document(
        CommonDocument(
            source=package.source,
            blocks=result.blocks,
            artifacts=(),
            coverage=StructuralCoverage(
                scope="docx_ooxml_structure",
                processed_parts=processed,
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
            mappings=(),
            references=references,
            page_count=PageCountAssessment(
                basis="unknown",
                artifact_sha256=None,
                artifact_page_count=None,
                status="deferred",
                reason_code="original_layout_unverified",
            ),
        )
    )


def read_body(package: DocxPackage) -> StructureResult:
    root = package.root(package.main_part)
    body = root.find(f"{{{WORD_NS}}}body")
    if body is None:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, package.source.role, "docx")
    result = read_region(
        body,
        package.main_part,
        package.source,
        "body",
        position=RegionPosition(root_path=f"{root_path(root)}/w:body[1]"),
    )
    outside = tuple(
        diagnostic("invalid_structure", locator(package.source, package.main_part, path))
        for child, path in child_paths(root, root_path(root))
        if child is not body or (child.tail or "").strip()
    )
    if (root.text or "").strip():
        outside += (
            diagnostic(
                "invalid_structure", locator(package.source, package.main_part, root_path(root))
            ),
        )
    return StructureResult(result.blocks, result.warnings + outside, result.references)


def ordered_notes(
    package: DocxPackage, notes: tuple[ReaderPart, ...], references: tuple[PendingReference, ...]
) -> tuple[tuple[ReaderPart, ...], tuple[DocumentDiagnostic, ...]]:
    keys = tuple(
        dict.fromkeys(note_key(item.key) for item in references if item.kind == "footnote")
    )
    selected = tuple(note for key in keys for note in notes if note.key == key)
    warnings = tuple(
        diagnostic("invalid_reference", locator(package.source, note.member, note.path))
        for note in notes
        if note not in selected
    )
    return selected, warnings


def read_docx(source: DocumentInput, limits: InputLimits = DEFAULT_LIMITS) -> CommonDocument:
    inspection = inspect_document(source, limits)
    if inspection.source.detected_format != "docx":
        raise InputValidationError(
            InputErrorCode.UNSUPPORTED_FORMAT, source.role, inspection.source.detected_format
        )
    package = DocxPackage(
        inspection.source,
        read_package(source.content, limits),
        inspection.content_members[0],
        limits,
    )
    result = read_body(package)
    relations = package.main_relationships()
    notes, note_warnings, note_members = note_parts(package, relations)
    notes, orphan_warnings = ordered_notes(package, notes, result.references)
    result = read_parts(
        package,
        notes,
        StructureResult(
            blocks=result.blocks,
            warnings=result.warnings + note_warnings + orphan_warnings,
            references=result.references,
        ),
    )
    headers = referenced_headers(package, relations, result.references)
    result = read_parts(package, headers, result)
    references = resolve_references(package, result.references, notes + headers, relations)
    processed = tuple(
        dict.fromkeys((package.main_part, *note_members, *(part.member for part in headers)))
    )
    return assemble_document(package, result, processed, references)
