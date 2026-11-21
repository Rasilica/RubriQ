from enum import StrEnum
from typing import Annotated, ClassVar, Final, Literal, NewType, Self, cast

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    DocumentDiagnostic,
    ExtractionCoverage,
    Sha256,
    SourceId,
    SourceLocator,
    StructuralCoverage,
)
from submission.models import FrozenModel, OptionalFieldsModel

RequirementId = NewType("RequirementId", str)
SubconditionId = NewType("SubconditionId", str)
type ShortText = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class RequirementErrorCode(StrEnum):
    INVALID_GUIDE = "invalid_guide"
    INPUT_LIMIT = "input_limit"
    RESPONSE_LIMIT = "response_limit"
    INVALID_RESPONSE = "invalid_response"
    SOURCE_MISMATCH = "source_mismatch"
    DUPLICATE_ID = "duplicate_id"
    INVALID_CITATION = "invalid_citation"


class RequirementError(ValueError):
    code: RequirementErrorCode

    def __init__(self, code: RequirementErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class RequirementLimits(FrozenModel):
    max_blocks: Annotated[int, Field(gt=0)] = 2000
    max_input_characters: Annotated[int, Field(gt=0)] = 200_000
    max_response_bytes: Annotated[int, Field(gt=0)] = 1_000_000
    max_requirements: Annotated[int, Field(gt=0, le=100)] = 100
    max_subconditions: Annotated[int, Field(gt=0, le=20)] = 20
    max_citations: Annotated[int, Field(gt=0, le=10)] = 10
    max_text_characters: Annotated[int, Field(gt=0, le=2000)] = 2000
    max_quote_characters: Annotated[int, Field(gt=0, le=10_000)] = 10_000


DEFAULT_REQUIREMENT_LIMITS: Final = RequirementLimits()


class CitationInput(FrozenModel):
    block_id: Annotated[BlockId, Field(min_length=1, max_length=2000)]
    char_range: CharacterRange
    quote: Annotated[str, Field(min_length=1, max_length=10_000, pattern=r"\S")]


class CitedText[Citation](FrozenModel):
    description: ShortText
    citations: Annotated[tuple[Citation, ...], Field(min_length=1, max_length=10)]


class Subcondition[Citation](CitedText[Citation]):
    subcondition_id: Annotated[
        SubconditionId, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ]


class RequirementFields[Citation](FrozenModel):
    requirement_id: Annotated[
        RequirementId, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ]
    title: ShortText
    citations: Annotated[tuple[Citation, ...], Field(min_length=1, max_length=10)]
    subconditions: Annotated[tuple[Subcondition[Citation], ...], Field(max_length=20)]


class UnconditionalInput(RequirementFields[CitationInput]):
    classification: Literal["required", "optional"]
    condition: None


class ConditionalInput(RequirementFields[CitationInput]):
    classification: Literal["conditional"]
    condition: CitedText[CitationInput]


type RequirementInput = Annotated[
    UnconditionalInput | ConditionalInput, Field(discriminator="classification")
]


class RequirementModelResponse(FrozenModel):
    """What the model returns; the server owns the guide identity."""

    schema_version: Literal["1"]
    requirements: Annotated[tuple[RequirementInput, ...], Field(max_length=100)]


class RequirementResponse(RequirementModelResponse):
    source_id: Annotated[SourceId, Field(min_length=1, max_length=200)]
    document_version_id: Annotated[str, Field(min_length=1, max_length=200)]
    source_sha256: Sha256


class VerifiedCitation(CitationInput, OptionalFieldsModel):
    omit_when_default: ClassVar[tuple[str, ...]] = ("from_ocr",)

    source_locator: SourceLocator
    coordinate_basis: Literal["block_raw_unicode"] = "block_raw_unicode"
    verification: Literal["exact_quote"] = "exact_quote"
    from_ocr: bool = False  # quote is machine-recognised image text, not an exact source quote


class RequirementItem(RequirementFields[VerifiedCitation]):
    classification: Literal["required", "optional", "conditional"]
    condition: CitedText[VerifiedCitation] | None
    application_status: Literal["undetermined"] = "undetermined"

    @model_validator(mode="after")
    def condition_matches_classification(self) -> Self:
        if (self.classification == "conditional") != (self.condition is not None):
            raise RequirementError(RequirementErrorCode.INVALID_RESPONSE)
        return self


class RequirementDraft(FrozenModel):
    schema_version: Literal["1"] = "1"
    prompt_version: Literal["1"] = "1"
    source_id: SourceId
    document_version_id: str
    source_sha256: Sha256
    requirements: tuple[RequirementItem, ...]
    source_extraction_status: Literal["complete", "partial"]
    coverage: Annotated[ExtractionCoverage | StructuralCoverage, Field(discriminator="scope")]
    warnings: tuple[DocumentDiagnostic, ...]
    typed_errors: tuple[DocumentDiagnostic, ...]
    diagnostics: tuple[Literal["no_requirements_returned"], ...] = ()
    status: Literal["needs_review"] = "needs_review"
    response_label: Literal["test_response"] = "test_response"
    adapter_id: Literal["offline-fixture-v1"] = "offline-fixture-v1"
    fake: Literal[True] = True
    confirmed: Literal[False] = False
    semantic_accuracy_verified: Literal[False] = False
    guarantees_all_requirements: Literal[False] = False
    ai_called: Literal[False] = False
    stored: Literal[False] = False


FIGURE_INSTRUCTION: Final = (
    "kind가 figure인 블록은 원문에서 그림이 있는 위치이며 글자가 없습니다. "
    "그림이 있다는 것만 알 수 있고 내용은 볼 수 없으니 그림 내용을 단정하지 말고, "
    "그림이 없다고 판단하지 마세요. 캡션처럼 글로 확인되는 근거만 인용하고 "
    "figure 블록은 인용하지 마세요. "
)


OCR_INSTRUCTION: Final = (
    "kind가 ocr인 블록은 이미지에서 기계가 읽은 글자라 오탈자가 있을 수 있습니다. "
    "인용은 가능하지만 인식 결과이므로 표기가 어색하면 확인 필요로 판단하세요. "
)


class RequestBlock(FrozenModel):
    block_id: BlockId
    raw_text: str
    kind: str | None = None  # set only for "figure"/"ocr" so every other block serializes as before

    @model_serializer(mode="wrap")
    def _omit_empty_kind(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data = cast("dict[str, object]", handler(self))
        if data.get("kind") is None:
            _ = data.pop("kind", None)
        return data


class RequirementRequest(FrozenModel):
    prompt_version: Literal["1"] = "1"
    schema_version: Literal["1"] = "1"
    instructions: str
    response_schema_json: str
    blocks: tuple[RequestBlock, ...]
    coordinate_basis: Literal["block_raw_unicode"] = "block_raw_unicode"
