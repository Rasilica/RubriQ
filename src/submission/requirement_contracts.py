from enum import StrEnum
from typing import Annotated, Final, Literal, NewType, Self

from pydantic import Field, model_validator

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
from submission.models import FrozenModel

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


class RequirementResponse(FrozenModel):
    schema_version: Literal["1"]
    source_id: Annotated[SourceId, Field(min_length=1, max_length=200)]
    document_version_id: Annotated[str, Field(min_length=1, max_length=200)]
    source_sha256: Sha256
    requirements: Annotated[tuple[RequirementInput, ...], Field(max_length=100)]


class VerifiedCitation(CitationInput):
    source_locator: SourceLocator
    coordinate_basis: Literal["block_raw_unicode"] = "block_raw_unicode"
    verification: Literal["exact_quote"] = "exact_quote"


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


class RequestBlock(FrozenModel):
    block_id: BlockId
    raw_text: str


class RequirementRequest(FrozenModel):
    prompt_version: Literal["1"] = "1"
    schema_version: Literal["1"] = "1"
    source_id: SourceId
    document_version_id: str
    source_sha256: Sha256
    instructions: str
    response_schema_json: str
    blocks: tuple[RequestBlock, ...]
    coordinate_basis: Literal["block_raw_unicode"] = "block_raw_unicode"
