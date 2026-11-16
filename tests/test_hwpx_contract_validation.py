import pytest
from hwpx_reader_helpers import FIXTURE, make_hwpx, source

from submission.document_contracts import BlockId, CharacterRange, ContractError, ContractErrorCode
from submission.hwpx_contract_validation import validate_hwpx_document
from submission.hwpx_reader import read_hwpx


@pytest.mark.parametrize(
    "defect", ["hash", "parent", "identity", "range", "fragment", "span", "normalization"]
)
def test_invalid_hwpx_provenance_is_rejected(defect: str) -> None:
    document = read_hwpx(source(FIXTURE.read_bytes()))
    first = document.blocks[0]
    match defect:
        case "hash":
            block = first.model_copy(
                update={
                    "source_locator": first.source_locator.model_copy(
                        update={"source_sha256": "a" * 64}
                    )
                }
            )
            expected = ContractErrorCode.SOURCE_IDENTITY_MISMATCH
        case "parent":
            block = first.model_copy(update={"parent_block_id": BlockId("missing")})
            expected = ContractErrorCode.INVALID_BLOCK_IDENTITY
        case "identity":
            block = first.model_copy(update={"block_id": BlockId("fake")})
            expected = ContractErrorCode.INVALID_BLOCK_IDENTITY
        case "range":
            block = first.model_copy(update={"raw_char_range": CharacterRange(start=0, end=1)})
            expected = ContractErrorCode.INVALID_CHARACTER_RANGE
        case "fragment":
            block = first.model_copy(update={"source_fragment_index": None})
            expected = ContractErrorCode.INVALID_BLOCK_IDENTITY
        case "span":
            block = first.model_copy(update={"source_spans": ()})
            expected = ContractErrorCode.INVALID_CHARACTER_RANGE
        case "normalization":
            block = first.model_copy(update={"normalization_map": ()})
            expected = ContractErrorCode.INVALID_CHARACTER_RANGE
        case _:
            pytest.fail("unknown case")
    broken = document.model_copy(update={"blocks": (block, *document.blocks[1:])})
    with pytest.raises(ContractError) as caught:
        validate_hwpx_document(broken)
    assert caught.value.code is expected


@pytest.mark.parametrize("defect", ["other_story", "ownerless", "interior_anchor"])
def test_hwpx_inline_reference_requires_its_owner_end_and_embedded_target(defect: str) -> None:
    story = "<hp:ctrl><hp:footNote><hp:subList><hp:p><hp:run><hp:t>각주</hp:t>"
    story += "</hp:run></hp:p></hp:subList></hp:footNote></hp:ctrl>"
    body = f"<hp:p><hp:run><hp:t>앞</hp:t>{story}<hp:t>뒤</hp:t>{story}</hp:run></hp:p>"
    document = read_hwpx(source(make_hwpx(body)))
    reference = document.references[0]
    match defect:
        case "other_story":
            broken = reference.model_copy(
                update={"target_locator": document.references[1].target_locator}
            )
        case "ownerless":
            broken = reference.model_copy(
                update={"source_block_id": None, "source_char_offset": None}
            )
        case "interior_anchor":
            broken = reference.model_copy(update={"source_char_offset": 0})
        case _:
            pytest.fail("unknown case")
    corrupted = document.model_copy(update={"references": (broken, *document.references[1:])})
    with pytest.raises(ContractError) as caught:
        validate_hwpx_document(corrupted)
    assert caught.value.code is ContractErrorCode.INVALID_SOURCE_REFERENCE
