from collections.abc import Mapping

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    CommonDocument,
    ContractError,
    ContractErrorCode,
    DocumentBlock,
    DocumentSource,
    SourceLocator,
    SourceReference,
)


def validate_locator(source: DocumentSource, position: SourceLocator) -> None:
    if position.source_sha256 != source.content_sha256 or position.original_page_number is not None:
        raise ContractError(ContractErrorCode.SOURCE_IDENTITY_MISMATCH)


def validate_spans(block: DocumentBlock, source: DocumentSource) -> None:
    cursor = 0
    for span in block.source_spans:
        validate_locator(source, span.source_locator)
        bounds = span.block_char_range
        if (
            bounds.start != cursor
            or bounds.end > len(block.raw_text)
            or span.source_char_range.end - span.source_char_range.start
            != bounds.end - bounds.start
        ):
            raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)
        if not span.source_locator.path.startswith(f"{block.source_locator.path}/"):
            raise ContractError(ContractErrorCode.SOURCE_IDENTITY_MISMATCH)
        if (
            span.source_coordinate_basis == "synthetic_control_unicode"
            and span.source_char_range != CharacterRange(start=0, end=1)
        ):
            raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)
        cursor = bounds.end
    if cursor != len(block.raw_text):
        raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)


def validate_block(
    block: DocumentBlock,
    source: DocumentSource,
    blocks: Mapping[BlockId, DocumentBlock],
    order: int,
) -> None:
    validate_locator(source, block.source_locator)
    if (
        block.block_id != f"{source.source_id}:{block.source_locator.path}"
        or block.reading_order != order
    ):
        raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    if block.parent_block_id is not None:
        parent = blocks.get(block.parent_block_id)
        if parent is None or parent.kind == "paragraph" or parent.reading_order >= order:
            raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    bounds = CharacterRange(start=0, end=len(block.raw_text))
    if block.raw_char_range != bounds or block.raw_coordinate_basis != "docx_paragraph_unicode":
        raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)
    if block.normalized_text != block.raw_text or block.normalization_version != "identity-v1":
        raise ContractError(ContractErrorCode.BLOCK_TEXT_MISMATCH)
    if block.kind == "paragraph":
        if len(block.normalization_map) != 1 or any(
            span.raw_range != bounds or span.normalized_range != bounds
            for span in block.normalization_map
        ):
            raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)
    elif block.raw_text or block.source_spans or block.normalization_map:
        raise ContractError(ContractErrorCode.BLOCK_TEXT_MISMATCH)
    validate_spans(block, source)


def validate_reference(
    reference: SourceReference, source: DocumentSource, blocks: Mapping[BlockId, DocumentBlock]
) -> None:
    validate_locator(source, reference.source_locator)
    if reference.source_block_id is not None:
        owner = blocks.get(reference.source_block_id)
        offset = reference.source_char_offset
        if (
            owner is None
            or owner.kind != "paragraph"
            or offset is None
            or not 0 <= offset <= len(owner.raw_text)
        ):
            raise ContractError(ContractErrorCode.INVALID_SOURCE_REFERENCE)
        if not reference.source_locator.path.startswith(f"{owner.source_locator.path}/"):
            raise ContractError(ContractErrorCode.INVALID_SOURCE_REFERENCE)
    elif reference.source_char_offset is not None:
        raise ContractError(ContractErrorCode.INVALID_SOURCE_REFERENCE)
    target = reference.target_locator
    if (reference.status == "resolved") != (target is not None):
        raise ContractError(ContractErrorCode.INVALID_SOURCE_REFERENCE)
    if target is not None:
        validate_locator(source, target)
        if not any(
            block.kind == reference.kind and block.source_locator == target
            for block in blocks.values()
        ):
            raise ContractError(ContractErrorCode.INVALID_SOURCE_REFERENCE)


def validate_docx_document(document: CommonDocument) -> CommonDocument:
    if (
        document.source.detected_format != "docx"
        or document.coverage.scope != "docx_ooxml_structure"
    ):
        raise ContractError(ContractErrorCode.SOURCE_IDENTITY_MISMATCH)
    blocks = {block.block_id: block for block in document.blocks}
    if len(blocks) != len(document.blocks):
        raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    for order, block in enumerate(document.blocks):
        validate_block(block, document.source, blocks, order)
    for reference in document.references:
        validate_reference(reference, document.source, blocks)
    for position in document.coverage.omitted_locators:
        validate_locator(document.source, position)
    for diagnostic in document.warnings + document.typed_errors:
        if diagnostic.source_locator is not None:
            validate_locator(document.source, diagnostic.source_locator)
    return document
