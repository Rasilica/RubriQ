from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field

from submission.document_contracts import Sha256
from submission.evidence_contracts import (
    ArtifactInput,
    BoundPageCountAssessment,
    EvidenceLimits,
    EvidenceModel,
    PageSelection,
)
from submission.report_check_contracts import Judgment, ReportCheckContext, ReportCheckLimits
from submission.report_check_results import ItemResult, ReportCheckResult
from submission.requirement_contracts import VerifiedCitation


class PageRuleErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNKNOWN_REQUIREMENT = "unknown_requirement"
    DUPLICATE_REQUIREMENT = "duplicate_requirement"
    SOURCE_MISMATCH = "source_mismatch"
    INPUT_LIMIT = "input_limit"
    INVALID_ARTIFACT = "invalid_artifact"


class PageRuleError(ValueError):
    code: PageRuleErrorCode

    def __init__(self, code: PageRuleErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class SubmissionCheckLimits(EvidenceModel):
    report_limits: ReportCheckLimits = ReportCheckLimits()
    evidence_limits: EvidenceLimits = EvidenceLimits()
    max_page_checks: Annotated[int, Field(gt=0, le=100)] = 100
    max_total_target_bytes: Annotated[int, Field(gt=0)] = 10 * 1024 * 1024
    max_total_target_characters: Annotated[int, Field(gt=0)] = 200_000


DEFAULT_SUBMISSION_CHECK_LIMITS: Final = SubmissionCheckLimits()


class PageRuleInput(EvidenceModel):
    requirement_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    target: ArtifactInput | None
    selection: PageSelection | None


class DerivedPageRule(EvidenceModel):
    grammar_version: Literal["pdf-all-upper-v1"] = "pdf-all-upper-v1"
    criteria_sha256: Sha256
    requirement_id: str
    criterion_sha256: Sha256
    guide_source_sha256: Sha256
    guide_document_version_id: str
    maximum_pages: Annotated[int, Field(ge=1, le=9999)]
    unit: Literal["page"] = "page"
    scope: Literal["all_pdf_pages"] = "all_pdf_pages"
    rule_citation: VerifiedCitation
    scope_citation: VerifiedCitation
    scope_subcondition_id: str


class RuleDerivation(EvidenceModel):
    rule: DerivedPageRule | None
    reason_code: Literal[
        "supported",
        "criterion_text_changed",
        "unsupported_rule_grammar",
        "unsupported_scope_grammar",
    ]


class PageScopeResult(EvidenceModel):
    subcondition_id: str
    status: Literal["verified", "deferred", "not_applicable"]
    effective_judgment: Literal["evidence_found", "deferred"] | None
    evaluation_basis: Literal["page_rule_scope"] = "page_rule_scope"
    reason_codes: tuple[str, ...]


class PageRuleResult(EvidenceModel):
    requirement_id: str
    status: Literal["compliant", "noncompliant", "deferred", "not_applicable"]
    rule: DerivedPageRule | None
    assessment: BoundPageCountAssessment | None
    scope_subconditions: tuple[PageScopeResult, ...]
    reason_codes: tuple[str, ...]


class SubmissionCheckContext(EvidenceModel):
    report_check: ReportCheckContext
    page_checks: tuple[PageRuleInput, ...]


class CombinedItemResult(EvidenceModel):
    semantic: ItemResult
    page_rule: PageRuleResult | None
    effective_judgment: Judgment | None
    evaluation_basis: Literal["semantic", "page_rule", "not_applicable"]
    needs_attention: bool


class SubmissionCheckResult(EvidenceModel):
    semantic: ReportCheckResult
    items: tuple[CombinedItemResult, ...]
    guarantees_all_page_rules: Literal[False] = False
    ai_called: Literal[False] = False
    stored: Literal[False] = False
