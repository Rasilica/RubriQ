import pytest
from pydantic import ValidationError

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    ContractError,
    DocumentBlock,
    SourceLocator,
    SourceTextSpan,
)


@pytest.mark.parametrize(("start", "end"), [(-1, 2), (4, 3)])
def test_character_range_rejects_invalid_boundaries(start: int, end: int) -> None:
    # Given / When / Then
    with pytest.raises((ValidationError, ContractError)):
        CharacterRange(start=start, end=end)


def test_character_range_accepts_empty_half_open_range() -> None:
    # Given / When
    span = CharacterRange(start=3, end=3)
    # Then
    assert span.end - span.start == 0


def test_source_locator_can_represent_structure_without_original_page() -> None:
    # Given / When
    locator = SourceLocator(
        source_sha256="a" * 64,
        path="word/document.xml/body/p[1]",
        original_page_number=None,
    )
    # Then
    assert locator.original_page_number is None


def test_contract_models_are_frozen() -> None:
    # Given
    span = CharacterRange(start=0, end=3)
    # When / Then
    with pytest.raises(ValidationError):
        span.start = 1


@pytest.mark.parametrize("value", ["short", "g" * 64])
def test_source_locator_rejects_invalid_source_hash(value: str) -> None:
    # Given / When / Then
    with pytest.raises(ValidationError):
        SourceLocator(source_sha256=value, path="page/1/block/p1-b1", original_page_number=1)


def hwpx_fragment() -> DocumentBlock:
    locator = SourceLocator(
        source_sha256="a" * 64,
        path="Contents/section0.xml::/hs:sec[1]/hp:p[1]",
        original_page_number=None,
    )
    return DocumentBlock(
        block_id=BlockId("fragment-1"),
        kind="paragraph",
        raw_text="뒤",
        normalized_text="뒤",
        normalization_version="identity-v1",
        normalization_map=(),
        source_locator=locator,
        raw_char_range=CharacterRange(start=0, end=1),
        raw_coordinate_basis="hwpx_paragraph_unicode",
        source_fragment_index=1,
        source_spans=(
            SourceTextSpan(
                source_locator=locator.model_copy(
                    update={"path": f"{locator.path}/hp:run[1]/hp:t[1]/hp:tab[1]"}
                ),
                source_char_range=CharacterRange(start=0, end=1),
                block_char_range=CharacterRange(start=0, end=1),
                source_coordinate_basis="source_node_tail_unicode",
            ),
        ),
        reading_order=0,
    )


def test_hwpx_fragment_and_tail_contracts() -> None:
    block = hwpx_fragment()
    restored = DocumentBlock.model_validate_json(block.model_dump_json())
    assert restored == block
    assert restored.source_fragment_index == 1
    assert restored.source_spans[0].source_coordinate_basis == "source_node_tail_unicode"


@pytest.mark.parametrize("index", [0, -1])
def test_invalid_fragment_index_is_rejected(index: int) -> None:
    with pytest.raises(ValidationError):
        DocumentBlock.model_validate(
            {**hwpx_fragment().model_dump(), "source_fragment_index": index}
        )
