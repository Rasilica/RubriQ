from submission.library_validation import check
from submission.pair_contracts import PreparedRole
from submission.pair_store import Session
from submission.report_check_contracts import CriteriaContext, ReportCheckContext
from submission.report_check_validation import (
    criteria_fingerprint,
    validate_context,
    validate_criteria_context,
)
from submission.requirement_contracts import CitationInput
from submission.requirement_validation import verify_citation
from submission.semantic_context import CHECK_LIMITS, draft_view
from submission.semantic_contracts import SemanticArchive


def capture(session: Session) -> SemanticArchive | None:
    state = session.semantic_state
    if state is None:
        return session.semantic_archive
    review = state.review
    if review.confirmed_revision != review.revision or not review.versions:
        return None
    return SemanticArchive(
        draft=draft_view(session, state),
        check=state.check,
        original_draft=review.original_draft,
        criteria=review.versions[-1],
    )


def validate_archive(
    archive: SemanticArchive | None, guide: PreparedRole, report: PreparedRole
) -> None:
    if archive is None:
        return
    guide_doc, report_doc = guide.view.document, report.view.document
    check(guide_doc is not None)
    if guide_doc is None:
        return
    ctx = CriteriaContext(
        guide=guide_doc,
        original_draft=archive.original_draft,
        criteria=archive.criteria,
    )
    validate_criteria_context(ctx, CHECK_LIMITS)
    draft = archive.draft
    check(
        draft.confirmed,
        draft.guide_sha256 == guide_doc.source.content_sha256,
        draft.criteria_sha256 == criteria_fingerprint(ctx),
        draft.items == archive.criteria.items,
        draft.requirements == archive.original_draft.requirements,
        draft.revision == archive.criteria.revision,
    )
    if archive.check is None:
        return
    check(report_doc is not None)
    if report_doc is None:
        return
    validate_context(
        ReportCheckContext(
            guide=guide_doc,
            report=report_doc,
            original_draft=archive.original_draft,
            criteria=archive.criteria,
        ),
        CHECK_LIMITS,
    )
    result = archive.check.result
    source = report_doc.source
    check(
        result.criteria_sha256 == draft.criteria_sha256,
        result.criteria_revision == draft.revision,
        result.criteria_version == archive.criteria.version,
        result.report_source_sha256 == source.content_sha256,
        result.report_source_id == source.source_id,
        result.report_document_version_id == source.document_version_id,
        result.submitted_block_ids
        == tuple(block.block_id for block in report_doc.blocks if block.raw_text.strip()),
        len(set(result.reviewed_block_ids)) == len(result.reviewed_block_ids),
        set(result.reviewed_block_ids) <= set(result.submitted_block_ids),
        tuple(item.criterion for item in result.items) == archive.criteria.items,
        tuple(item.original_requirement for item in result.items) == draft.requirements,
    )
    for item in result.items:
        evidence = item.evidence + tuple(
            cite for sub in item.subconditions for cite in sub.evidence
        )
        for entry in evidence:
            cite = entry.citation
            verified = verify_citation(
                CitationInput(
                    block_id=cite.block_id,
                    char_range=cite.char_range,
                    quote=cite.quote,
                ),
                report_doc.blocks,
            )
            check(verified == cite, cite.block_id in result.reviewed_block_ids)
