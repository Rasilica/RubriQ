from typing import Annotated, Literal

from pydantic import Field

from submission.document_contracts import (
    BlockId,
    DocumentDiagnostic,
    ExtractionCoverage,
    ProcessingStatus,
    Sha256,
    SourceId,
    StructuralCoverage,
)
from submission.models import FrozenModel
from submission.report_check_contracts import EvidenceRole, Judgment
from submission.requirement_contracts import RequestBlock, RequirementItem, VerifiedCitation
from submission.review_contracts import CriteriaVersion, ReviewedItem

type ReasonCode = Literal[
    "rule_verification_required",
    "content_evidence_required",
    "partial_extraction",
    "incomplete_review_scope",
    "subconditions_aggregated",
    "excluded",
    "condition_does_not_apply",
    "evidence_absent",
    "caller_deferred",
    "partial_requires_subconditions",
]


class VerifiedReportEvidence(FrozenModel):
    citation: VerifiedCitation
    evidence_role: EvidenceRole
    relation: str
    evidence_role_verified: Literal[False] = False
    semantic_relation_verified: Literal[False] = False


class EffectiveFinding(FrozenModel):
    proposed_judgment: Judgment
    judgment: Judgment
    reason: str
    reason_codes: tuple[ReasonCode, ...]
    needs_attention: bool
    evidence: tuple[VerifiedReportEvidence, ...]


class SubconditionResult(EffectiveFinding):
    subcondition_id: str


class ItemResult(FrozenModel):
    original_requirement: RequirementItem
    criterion: ReviewedItem
    requirement_id: str
    applicability: Literal["applicable", "not_applicable"]
    proposed_judgment: Judgment | None
    judgment: Judgment | None
    reason: str | None
    reason_codes: tuple[ReasonCode, ...]
    needs_attention: bool
    evidence: tuple[VerifiedReportEvidence, ...]
    subconditions: tuple[SubconditionResult, ...]


class ExpectedReportItem(FrozenModel):
    requirement_id: str
    subcondition_ids: tuple[str, ...]


class ReportCheckRequest(FrozenModel):
    schema_version: Literal["1"] = "1"
    prompt_version: Literal["1"] = "1"
    criteria: CriteriaVersion
    original_requirements: tuple[RequirementItem, ...]
    expected_items: tuple[ExpectedReportItem, ...]
    instructions: str
    response_schema_json: str
    blocks: tuple[RequestBlock, ...]
    coordinate_basis: Literal["block_raw_unicode"] = "block_raw_unicode"


class ReportCheckResult(FrozenModel):
    schema_version: Literal["1"] = "1"
    prompt_version: Literal["1"] = "1"
    criteria_sha256: Sha256
    criteria_version: int
    criteria_revision: int
    report_source_id: SourceId
    report_document_version_id: str
    report_source_sha256: Sha256
    submitted_block_ids: tuple[BlockId, ...]
    reviewed_block_ids: tuple[BlockId, ...]
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
    response_label: Literal["test_response"] = "test_response"
    adapter_id: Literal["offline-report-check-v1"] = "offline-report-check-v1"
    fake: Literal[True] = True
    ai_called: Literal[False] = False
    stored: Literal[False] = False
    semantic_accuracy_verified: Literal[False] = False
    guarantees_all_requirements: Literal[False] = False
    reviewed_scope_verified: Literal[False] = False
