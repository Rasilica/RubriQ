from hashlib import sha256
from typing import Final

from submission.document_contracts import CommonDocument
from submission.pair_contracts import PairError, PairErrorCode, PreparedRole
from submission.pair_store import Session
from submission.report_check_contracts import CriteriaContext, ReportCheckLimits
from submission.report_check_validation import criteria_fingerprint
from submission.semantic_contracts import DraftView, SemanticState

CHECK_LIMITS: Final = ReportCheckLimits(
    max_blocks=2000,  # response-contract cap; the character budget is the real limit
    max_input_characters=60000,
    max_response_bytes=262144,
)


def document(role: PreparedRole) -> CommonDocument:
    result = role.view.document
    if result is None or sha256(role.original).hexdigest() != result.source.content_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    return result


def draft_view(session: Session, state: SemanticState) -> DraftView:
    review = state.review
    draft = review.original_draft
    confirmed = review.confirmed_revision == review.revision
    return DraftView(
        draft_id=review.session_id,
        revision=review.revision,
        guide_sha256=draft.source_sha256,
        requirements=draft.requirements,
        items=review.items,
        confirmed=confirmed,
        criteria_sha256=criteria_fingerprint(
            CriteriaContext(
                guide=document(session.guide), original_draft=draft, criteria=review.versions[-1]
            )
        )
        if confirmed
        else None,
        provider=state.provider,
        model=state.model,
        source_extraction_status=draft.source_extraction_status,
        coverage=draft.coverage,
        warnings=draft.warnings,
        typed_errors=draft.typed_errors,
        usage=state.usage,
    )
