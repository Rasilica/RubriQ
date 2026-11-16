from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from submission.document_contracts import SourceLocator
from submission.models import FrozenModel
from submission.requirement_contracts import RequirementDraft, ShortText

type Classification = Literal["required", "optional", "conditional"]
type Application = Literal["applies", "does_not_apply", "undetermined"]


class ReviewErrorCode(StrEnum):
    EXCLUSION_REASON_REQUIRED = "exclusion_reason_required"
    INVALID_CONDITION = "invalid_condition"
    APPLICATION_REASON_REQUIRED = "application_reason_required"
    IMMUTABLE_IDENTITY = "immutable_identity"
    STALE_REVISION = "stale_revision"
    EMPTY_CRITERIA = "empty_criteria"
    APPLICATION_UNDETERMINED = "application_undetermined"
    VERSION_LIMIT = "version_limit"
    REVIEW_REQUEST_REQUIRED = "review_request_required"
    JSON_REQUIRED = "json_required"
    BODY_TOO_LARGE = "body_too_large"
    INVALID_REVIEW_REQUEST = "invalid_review_request"
    SESSION_LIMIT = "session_limit"
    SESSION_UNAVAILABLE = "session_unavailable"
    DEMO_UNAVAILABLE = "demo_unavailable"


class ReviewError(ValueError):
    code: ReviewErrorCode
    status_code: int

    def __init__(self, code: ReviewErrorCode, status_code: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class EditableSubcondition(FrozenModel):
    subcondition_id: Annotated[str, Field(min_length=1, max_length=100)]
    description: ShortText


class EditableItem(FrozenModel):
    requirement_id: Annotated[str, Field(min_length=1, max_length=100)]
    title: ShortText
    classification: Classification
    condition_description: ShortText | None
    subconditions: Annotated[tuple[EditableSubcondition, ...], Field(max_length=20)]
    included: bool
    exclusion_reason: ShortText | None
    application_status: Application
    application_reason: ShortText | None


class ReviewedItem(EditableItem):
    edited_fields: tuple[str, ...] = ()


class RevisionRequest(FrozenModel):
    expected_revision: Annotated[int, Field(ge=0)]


class WorkingCopyRequest(RevisionRequest):
    items: Annotated[tuple[EditableItem, ...], Field(max_length=100)]


class CreateRequest(FrozenModel):
    pass


class SourceBlock(FrozenModel):
    block_id: str
    raw_text: str
    source_locator: SourceLocator


class CriteriaVersion(FrozenModel):
    version: int
    revision: int
    document_version_id: str
    source_sha256: str
    items: tuple[ReviewedItem, ...]


class ReviewSession(FrozenModel):
    session_id: str
    revision: int = 0
    original_draft: RequirementDraft
    source_blocks: tuple[SourceBlock, ...]
    items: tuple[ReviewedItem, ...]
    versions: tuple[CriteriaVersion, ...] = ()
    confirmed_revision: int | None = None
    demo: Literal[True] = True
    ai_called: Literal[False] = False
    stored: Literal[False] = False


class CreatedSession(ReviewSession):
    session_token: str


class ReviewResponse[Data](FrozenModel):
    success: Literal[True] = True
    data: Data
