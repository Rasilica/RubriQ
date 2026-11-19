from submission.document_contracts import (
    BlockId,
    CharacterRange,
    CommonDocument,
    DocumentBlock,
    DocumentDiagnostic,
    DocumentSource,
    NormalizationSpan,
    PageCountAssessment,
    ProcessingStatus,
    SourceLocator,
    SourceReference,
    SourceTextSpan,
    StructuralCoverage,
)
from submission.hwp_reader_contracts import HwpNode, HwpTree


def locator(source: DocumentSource, path: str) -> SourceLocator:
    return SourceLocator(source_sha256=source.content_sha256, path=path, original_page_number=None)


def block_id(source: DocumentSource, path: str, fragment: int | None = None) -> BlockId:
    suffix = "" if fragment is None else f":fragment:{fragment}"
    return BlockId(f"{source.source_id}:{path}{suffix}")


def project_block(node: HwpNode, order: int, source: DocumentSource) -> DocumentBlock:
    bounds = CharacterRange(start=0, end=len(node.text))
    return DocumentBlock(
        block_id=block_id(source, node.path, node.fragment),
        kind=node.kind,
        raw_text=node.text,
        normalized_text=node.text,
        normalization_version="identity-v1",
        normalization_map=(NormalizationSpan(raw_range=bounds, normalized_range=bounds),)
        if node.kind == "paragraph"
        else (),
        source_locator=locator(source, node.path),
        raw_char_range=CharacterRange(start=node.start, end=node.start + len(node.text)),
        raw_coordinate_basis="hwp_paragraph_unicode",
        source_fragment_index=node.fragment,
        source_spans=(
            SourceTextSpan(
                source_locator=locator(source, node.path + "/text"),
                source_char_range=CharacterRange(start=node.start, end=node.start + len(node.text)),
                block_char_range=bounds,
                source_coordinate_basis="hwp_paragraph_unicode",
            ),
        )
        if node.text
        else (),
        parent_block_id=block_id(source, node.parent) if node.parent is not None else None,
        reading_order=order,
    )


def project_tree(tree: HwpTree, source: DocumentSource) -> CommonDocument:
    blocks = tuple(project_block(node, order, source) for order, node in enumerate(tree.nodes))
    # A shape whose text box was read is fully read; pictures and containers stay unread.
    text_box_figures = {
        block.parent_block_id for block in blocks if "/textbox/" in block.source_locator.path
    }
    warnings = tuple(
        DocumentDiagnostic(
            code="unsupported_element", page_number=None, source_locator=locator(source, path)
        )
        for path in tree.omitted
    ) + tuple(
        DocumentDiagnostic(
            code="figure_content_unread", page_number=None, source_locator=block.source_locator
        )
        for block in blocks
        if block.kind == "figure" and block.block_id not in text_box_figures
    )
    readable = any(block.raw_text for block in blocks)
    return CommonDocument(
        source=source,
        blocks=blocks,
        artifacts=(),
        coverage=StructuralCoverage(
            scope="hwp5_structure",
            processed_parts=tree.parts,
            omitted_locators=tuple(locator(source, path) for path in tree.omitted),
        ),
        extraction_status=ProcessingStatus.PARTIAL
        if warnings
        else ProcessingStatus.COMPLETE
        if readable
        else ProcessingStatus.FAILED,
        rendering_status=ProcessingStatus.NOT_STARTED,
        warnings=warnings,
        typed_errors=()
        if readable
        else (
            DocumentDiagnostic(
                code="empty_content",
                page_number=None,
                source_locator=locator(source, tree.parts[0]),
            ),
        ),
        mappings=(),
        references=tuple(
            SourceReference(
                kind=link.kind,
                source_locator=locator(source, link.path),
                source_block_id=block_id(source, link.owner, link.fragment),
                source_char_offset=link.offset,
                target_locator=locator(source, link.path) if link.resolved else None,
                status="resolved" if link.resolved else "unresolved",
            )
            for link in tree.references
        ),
        page_count=PageCountAssessment(
            basis="unknown",
            artifact_sha256=None,
            artifact_page_count=None,
            status="deferred",
            reason_code="original_layout_unverified",
        ),
    )
