from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from submission.cloud_contracts import Provider, Usage
from submission.document_contracts import (
    DocumentDiagnostic,
    ExtractionCoverage,
    ProcessingStatus,
    Sha256,
    StructuralCoverage,
)
from submission.models import FrozenModel
from submission.ollama_contracts import ModelName
from submission.report_check_results import ItemResult
from submission.requirement_contracts import RequirementDraft, RequirementItem
from submission.review_contracts import (
    CriteriaVersion,
    ReviewedItem,
    ReviewSession,
    WorkingCopyRequest,
)


class SemanticCode(StrEnum):
    INVALID_MODEL = "ai_invalid_model"
    FORBIDDEN = "ai_forbidden"
    CONFIRMATION_REQUIRED = "ai_confirmation_required"
    STALE_DRAFT = "ai_stale_draft"
    CONSENT_REQUIRED = "ai_consent_required"
    SOURCE_MISMATCH = "ai_source_mismatch"
    INPUT_LIMIT = "ai_input_limit"
    SESSION_EXPIRING = "ai_session_expiring"


class SemanticError(ValueError):
    def __init__(self, code: SemanticCode, status: int = 422) -> None:
        super().__init__(code)
        self.code: str = code
        self.status: int = status


class AIRequest(FrozenModel):
    provider: Provider | Literal["ollama"]
    model: ModelName
    consent: Annotated[bool, Field(strict=True)] = False
    use_saved_key: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def cloud_model_name(self) -> Self:
        if self.provider != "ollama" and any(c in self.model for c in ":/"):
            raise SemanticError(SemanticCode.INVALID_MODEL)
        return self


class RequirementsRequest(AIRequest):
    guide_sha256: Sha256


class CriteriaRequest(WorkingCopyRequest):
    draft_id: Annotated[str, Field(min_length=1, max_length=128)]


class CheckRequest(RequirementsRequest):
    draft_id: Annotated[str, Field(min_length=1, max_length=128)]
    criteria_sha256: Sha256
    report_sha256: Sha256


class DraftView(FrozenModel):
    draft_id: str
    revision: int
    guide_sha256: str
    requirements: tuple[RequirementItem, ...]
    items: tuple[ReviewedItem, ...]
    criteria_sha256: str | None
    confirmed: bool
    provider: Provider | Literal["ollama"]
    model: str
    ai_called: Literal[True] = True
    semantic_accuracy_verified: Literal[False] = False
    guarantees_all_requirements: Literal[False] = False
    source_extraction_status: Literal["complete", "partial"]
    coverage: Annotated[ExtractionCoverage | StructuralCoverage, Field(discriminator="scope")]
    warnings: tuple[DocumentDiagnostic, ...]
    typed_errors: tuple[DocumentDiagnostic, ...]
    usage: Usage


class LiveReportResult(FrozenModel):
    schema_version: Literal["1"] = "1"
    prompt_version: Literal["1"] = "1"
    criteria_sha256: str
    criteria_version: int
    criteria_revision: int
    report_source_id: str
    report_document_version_id: str
    report_source_sha256: str
    submitted_block_ids: tuple[str, ...]
    reviewed_block_ids: tuple[str, ...]
    items: tuple[ItemResult, ...]
    guide_extraction_status: ProcessingStatus
    report_extraction_status: ProcessingStatus
    guide_coverage: Annotated[ExtractionCoverage | StructuralCoverage, Field(discriminator="scope")]
    report_coverage: Annotated[
        ExtractionCoverage | StructuralCoverage, Field(discriminator="scope")
    ]
    guide_warnings: tuple[DocumentDiagnostic, ...]
    report_warnings: tuple[DocumentDiagnostic, ...]
    guide_typed_errors: tuple[DocumentDiagnostic, ...]
    report_typed_errors: tuple[DocumentDiagnostic, ...]
    ai_called: Literal[True] = True
    semantic_accuracy_verified: Literal[False] = False
    guarantees_all_requirements: Literal[False] = False
    reviewed_scope_verified: Literal[False] = False


class CheckView(FrozenModel):
    provider: Provider | Literal["ollama"]
    model: str
    ai_called: Literal[True] = True
    result: LiveReportResult
    usage: Usage
    request_count: Annotated[int, Field(ge=1)] = 1


class SemanticState(FrozenModel):
    provider: Provider | Literal["ollama"]
    model: str
    review: ReviewSession
    usage: Usage
    check: CheckView | None = None


class SemanticArchive(FrozenModel):
    draft: DraftView
    check: CheckView | None = None
    original_draft: RequirementDraft
    criteria: CriteriaVersion
