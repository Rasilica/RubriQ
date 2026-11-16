from dataclasses import dataclass
from typing import assert_never

from submission.report_check_contracts import Judgment, ProposedFinding
from submission.report_check_results import EffectiveFinding, ReasonCode, VerifiedReportEvidence


@dataclass(frozen=True, slots=True)
class ReviewScope:
    complete_extraction: bool
    complete_review: bool
    optional: bool


def evaluate_finding(
    proposed: ProposedFinding, evidence: tuple[VerifiedReportEvidence, ...], scope: ReviewScope
) -> EffectiveFinding:
    codes: tuple[ReasonCode, ...] = ()
    judgment: Judgment
    match proposed.proposed_judgment:
        case "explicit_noncompliance":
            judgment, codes = "deferred", ("rule_verification_required",)
        case "deferred":
            judgment, codes = "deferred", ("caller_deferred",)
        case "evidence_found":
            if any(item.evidence_role == "content" for item in evidence):
                judgment = "evidence_found"
            else:
                judgment, codes = "deferred", ("content_evidence_required",)
        case "partially_satisfied":
            judgment, codes = "deferred", ("partial_requires_subconditions",)
        case "evidence_missing":
            judgment, codes = "evidence_missing", ("evidence_absent",)
            if not scope.complete_extraction:
                judgment, codes = "deferred", ("partial_extraction",)
            if not scope.complete_review:
                judgment, codes = "deferred", (*codes, "incomplete_review_scope")
        case _:
            assert_never(proposed.proposed_judgment)
    return EffectiveFinding(
        proposed_judgment=proposed.proposed_judgment,
        judgment=judgment,
        reason=proposed.reason,
        reason_codes=codes,
        needs_attention=not scope.optional and judgment != "evidence_found",
        evidence=evidence,
    )


def aggregate_subconditions(
    parent: EffectiveFinding, children: tuple[EffectiveFinding, ...], scope: ReviewScope
) -> EffectiveFinding:
    if not children:
        return parent
    match parent.proposed_judgment:
        case "explicit_noncompliance" | "deferred":
            return parent
        case "evidence_found" | "partially_satisfied" | "evidence_missing":
            judgments = tuple(child.judgment for child in children)
            if all(value == "evidence_found" for value in judgments):
                judgment: Judgment = "evidence_found"
            elif any(value == "evidence_found" for value in judgments):
                judgment = "partially_satisfied"
            elif all(value == "evidence_missing" for value in judgments):
                judgment = "evidence_missing"
            else:
                judgment = "deferred"
            return EffectiveFinding(
                proposed_judgment=parent.proposed_judgment,
                judgment=judgment,
                reason=parent.reason,
                reason_codes=("subconditions_aggregated",),
                evidence=parent.evidence,
                needs_attention=not scope.optional and judgment != "evidence_found",
            )
        case _:
            assert_never(parent.proposed_judgment)
