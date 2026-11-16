from pathlib import Path

import pytest

from submission.document_contracts import BlockId, CharacterRange, ContractError, ContractErrorCode
from submission.docx_contract_validation import validate_docx_document
from submission.docx_reader import read_docx
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole

FIXTURE = Path(__file__).parents[1] / "samples/formats/boundary.docx"


@pytest.mark.parametrize(
    "defect", ["source_hash", "parent", "order", "range", "block_id", "span", "reference"]
)
def test_invalid_reader_result_provenance_is_rejected(defect: str) -> None:
    document = read_docx(DocumentInput("report.docx", FIXTURE.read_bytes(), DocumentRole.REPORT))
    first = document.blocks[0]
    match defect:
        case "source_hash":
            block = first.model_copy(
                update={
                    "source_locator": first.source_locator.model_copy(
                        update={"source_sha256": "a" * 64}
                    )
                }
            )
        case "parent":
            block = first.model_copy(update={"parent_block_id": BlockId("missing")})
        case "order":
            block = first.model_copy(update={"reading_order": 20})
        case "range":
            block = first.model_copy(update={"raw_char_range": CharacterRange(start=0, end=1)})
        case "block_id":
            block = first.model_copy(update={"block_id": BlockId("invented")})
        case "span":
            span = first.source_spans[0].model_copy(
                update={"block_char_range": CharacterRange(start=1, end=2)}
            )
            block = first.model_copy(update={"source_spans": (span,)})
        case "reference":
            reference = document.references[0].model_copy(update={"target_locator": None})
            broken = document.model_copy(
                update={"references": (reference, *document.references[1:])}
            )
            with pytest.raises(ContractError) as caught:
                validate_docx_document(broken)
            assert caught.value.code is ContractErrorCode.INVALID_SOURCE_REFERENCE
            return
        case _:
            pytest.fail("unknown test case")
    broken = document.model_copy(update={"blocks": (block, *document.blocks[1:])})
    with pytest.raises(ContractError) as caught:
        validate_docx_document(broken)
    expected = {
        "source_hash": ContractErrorCode.SOURCE_IDENTITY_MISMATCH,
        "parent": ContractErrorCode.INVALID_BLOCK_IDENTITY,
        "order": ContractErrorCode.INVALID_BLOCK_IDENTITY,
        "range": ContractErrorCode.INVALID_CHARACTER_RANGE,
        "block_id": ContractErrorCode.INVALID_BLOCK_IDENTITY,
        "span": ContractErrorCode.INVALID_CHARACTER_RANGE,
    }
    assert caught.value.code is expected[defect]


def test_missing_normalization_mapping_is_rejected() -> None:
    document = read_docx(DocumentInput("report.docx", FIXTURE.read_bytes(), DocumentRole.REPORT))
    first = document.blocks[0].model_copy(update={"normalization_map": ()})
    broken = document.model_copy(update={"blocks": (first, *document.blocks[1:])})
    with pytest.raises(ContractError) as caught:
        validate_docx_document(broken)
    assert caught.value.code is ContractErrorCode.INVALID_CHARACTER_RANGE


def test_docx_document_cannot_claim_hwpx_coverage() -> None:
    document = read_docx(DocumentInput("report.docx", FIXTURE.read_bytes(), DocumentRole.REPORT))
    coverage = document.coverage.model_copy(update={"scope": "hwpx_xml_structure"})
    broken = document.model_copy(update={"coverage": coverage})
    with pytest.raises(ContractError) as caught:
        validate_docx_document(broken)
    assert caught.value.code is ContractErrorCode.SOURCE_IDENTITY_MISMATCH


@pytest.mark.parametrize("defect", ["anchor", "missing_owner", "ownerless_offset", "wrong_target"])
def test_invalid_reference_details_are_rejected(defect: str) -> None:
    document = read_docx(DocumentInput("report.docx", FIXTURE.read_bytes(), DocumentRole.REPORT))
    original = document.references[0]
    match defect:
        case "anchor":
            changed = original.model_copy(update={"source_char_offset": 999})
        case "missing_owner":
            changed = original.model_copy(update={"source_block_id": BlockId("absent")})
        case "ownerless_offset":
            changed = original.model_copy(update={"source_block_id": None, "source_char_offset": 1})
        case "wrong_target":
            changed = original.model_copy(
                update={"target_locator": document.blocks[0].source_locator}
            )
        case _:
            pytest.fail("unknown case")
    broken = document.model_copy(update={"references": (changed, *document.references[1:])})
    with pytest.raises(ContractError) as caught:
        validate_docx_document(broken)
    assert caught.value.code is ContractErrorCode.INVALID_SOURCE_REFERENCE
