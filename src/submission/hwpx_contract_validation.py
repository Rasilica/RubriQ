from collections.abc import Mapping

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    CommonDocument,
    ContractError,
    ContractErrorCode,
    DocumentBlock,
    DocumentSource,
    SourceReference,
)
from submission.docx_contract_validation import validate_locator, validate_reference, validate_spans


def expected_identity(block: DocumentBlock, source: DocumentSource) -> str:
    expected = f"{source.source_id}:{block.source_locator.path}"
    if block.kind == "paragraph":
        if block.source_fragment_index is None:
            raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
        expected += f":fragment:{block.source_fragment_index}"
    elif block.source_fragment_index is not None:
        raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    return expected


def validate_block(
    block: DocumentBlock,
    source: DocumentSource,
    blocks: Mapping[BlockId, DocumentBlock],
    order: int,
) -> None:
    validate_locator(source, block.source_locator)
    if block.block_id != expected_identity(block, source) or block.reading_order != order:
        raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    if block.parent_block_id is not None:
        parent = blocks.get(block.parent_block_id)
        if parent is None or parent.kind == "paragraph" or parent.reading_order >= order:
            raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    bounds = CharacterRange(start=0, end=len(block.raw_text))
    if (
        block.raw_char_range.end - block.raw_char_range.start != len(block.raw_text)
        or block.raw_coordinate_basis != "hwpx_paragraph_unicode"
    ):
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


def validate_fragment_sequence(blocks: tuple[DocumentBlock, ...]) -> None:
    paragraphs: dict[str, tuple[int, int]] = {}
    for block in blocks:
        if block.kind != "paragraph":
            continue
        previous_index, previous_end = paragraphs.get(block.source_locator.path, (0, 0))
        if block.source_fragment_index != previous_index + 1:
            raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
        if block.raw_char_range.start != previous_end:
            raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)
        paragraphs = {
            **paragraphs,
            block.source_locator.path: (previous_index + 1, block.raw_char_range.end),
        }


def validate_inline_reference(
    reference: SourceReference, source: DocumentSource, blocks: Mapping[BlockId, DocumentBlock]
) -> None:
    validate_reference(reference, source, blocks)
    owner = blocks.get(reference.source_block_id) if reference.source_block_id is not None else None
    if (
        owner is None
        or reference.source_char_offset != len(owner.raw_text)
        or (
            reference.target_locator is not None
            and reference.target_locator != reference.source_locator
        )
    ):
        raise ContractError(ContractErrorCode.INVALID_SOURCE_REFERENCE)


def validate_hwpx_document(document: CommonDocument) -> CommonDocument:
    if document.source.detected_format != "hwpx" or document.coverage.scope != "hwpx_xml_structure":
        raise ContractError(ContractErrorCode.SOURCE_IDENTITY_MISMATCH)
    blocks = {block.block_id: block for block in document.blocks}
    if len(blocks) != len(document.blocks):
        raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
    for order, block in enumerate(document.blocks):
        validate_block(block, document.source, blocks, order)
    validate_fragment_sequence(document.blocks)
    for reference in document.references:
        validate_inline_reference(reference, document.source, blocks)
    for diagnostic in document.warnings + document.typed_errors:
        if diagnostic.source_locator is not None:
            validate_locator(document.source, diagnostic.source_locator)
    for position in document.coverage.omitted_locators:
        validate_locator(document.source, position)
    return document
