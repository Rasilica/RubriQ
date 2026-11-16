from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field

from submission.document_contracts import BlockId, CommonDocument, Sha256, SourceId
from submission.models import FrozenModel
from submission.requirement_contracts import CitationInput, RequirementDraft, ShortText
from submission.review_contracts import CriteriaVersion

type Judgment = Literal[
    "evidence_found",
    "partially_satisfied",
    "explicit_noncompliance",
    "evidence_missing",
    "deferred",
]
type EvidenceRole = Literal["content", "heading", "toc", "unknown"]


class ReportCheckErrorCode(StrEnum):
    INVALID_CONTEXT = "invalid_context"
    INVALID_REPORT = "invalid_report"
    INPUT_LIMIT = "input_limit"
    RESPONSE_LIMIT = "response_limit"
    INVALID_RESPONSE = "invalid_response"
    SOURCE_MISMATCH = "source_mismatch"
    CRITERIA_MISMATCH = "criteria_mismatch"
    INVALID_IDENTITY = "invalid_identity"
    INVALID_CITATION = "invalid_citation"
    INVALID_SCOPE = "invalid_scope"


class ReportCheckError(ValueError):
    code: ReportCheckErrorCode

    def __init__(self, code: ReportCheckErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class ReportCheckLimits(FrozenModel):
    max_blocks: Annotated[int, Field(gt=0)] = 2000
    max_input_characters: Annotated[int, Field(gt=0)] = 200_000
    max_response_bytes: Annotated[int, Field(gt=0)] = 1_000_000


DEFAULT_REPORT_CHECK_LIMITS: Final = ReportCheckLimits()


class CriteriaContext(FrozenModel):
    guide: CommonDocument
    original_draft: RequirementDraft
    criteria: CriteriaVersion


class ReportCheckContext(CriteriaContext):
    report: CommonDocument


class ReportEvidence(FrozenModel):
    citation: CitationInput
    evidence_role: EvidenceRole
    relation: ShortText


class ProposedFinding(FrozenModel):
    proposed_judgment: Judgment
    reason: ShortText
    evidence: Annotated[tuple[ReportEvidence, ...], Field(max_length=10)]


class ReportSubcondition(ProposedFinding):
    subcondition_id: Annotated[str, Field(min_length=1, max_length=100)]


class ReportItem(ProposedFinding):
    requirement_id: Annotated[str, Field(min_length=1, max_length=100)]
    subconditions: Annotated[tuple[ReportSubcondition, ...], Field(max_length=20)]


class ReportCheckResponse(FrozenModel):
    schema_version: Literal["1"]
    criteria_sha256: Sha256
    report_source_id: Annotated[SourceId, Field(min_length=1, max_length=200)]
    report_document_version_id: Annotated[str, Field(min_length=1, max_length=200)]
    report_source_sha256: Sha256
    reviewed_block_ids: Annotated[tuple[BlockId, ...], Field(max_length=2000)]
    items: Annotated[tuple[ReportItem, ...], Field(max_length=100)]
