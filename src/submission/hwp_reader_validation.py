from collections.abc import Mapping

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.document_contracts import BlockId, CommonDocument, ContractError, DocumentBlock
from submission.docx_contract_validation import validate_reference, validate_spans
from submission.hwp_reader_contracts import HwpNode, HwpTree
from submission.hwpx_contract_validation import validate_fragment_sequence


def validate_node(
    node: HwpNode, block: DocumentBlock, blocks: Mapping[BlockId, DocumentBlock]
) -> None:
    if (node.kind == "paragraph") != (node.fragment is not None):
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
    if node.kind != "paragraph" and (node.text or node.start):
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
    if node.parent is not None:
        parent = blocks.get(block.parent_block_id) if block.parent_block_id is not None else None
        if (
            parent is None
            or parent.kind == "paragraph"
            or parent.reading_order >= block.reading_order
            or not node.path.startswith(node.parent + "/")
        ):
            raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)


def validate_tree(tree: HwpTree, document: CommonDocument) -> CommonDocument:
    if tree.parts != tuple(f"BodyText/Section{index}" for index in range(len(tree.parts))):
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
    blocks = {block.block_id: block for block in document.blocks}
    if len(blocks) != len(document.blocks):
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
    for node, block in zip(tree.nodes, document.blocks, strict=True):
        if not any(node.path.startswith(f"{part}/") for part in tree.parts):
            raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
        validate_node(node, block, blocks)
    if any(
        not any(path == part or path.startswith(f"{part}/") for part in tree.parts)
        for path in tree.omitted
    ):
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
    try:
        validate_fragment_sequence(document.blocks)
        for block in document.blocks:
            validate_spans(block, document.source)
        for reference in document.references:
            validate_reference(reference, document.source, blocks)
    except ContractError as error:
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID) from error
    return document
