"""Split over-budget documents into several AI calls and merge the answers back.

Only the character budget limits a request. Blocks are never split; the merged response is
validated once against the full context by the existing adapters.
"""

from collections.abc import Sequence
from typing import Final

from submission import semantic_diagnostics as diagnostics
from submission.document_contracts import CommonDocument
from submission.report_check_binding import criteria_budget_size, validate_context_budget
from submission.report_check_contracts import (
    Judgment,
    ProposedFinding,
    ReportCheckContext,
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckLimits,
    ReportCheckResponse,
    ReportEvidence,
    ReportItem,
    ReportSubcondition,
)
from submission.report_check_results import ExpectedReportItem
from submission.report_check_validation import (
    criteria_fingerprint,
    parse_response,
    submitted_report_block_ids,
    with_cited_blocks_reviewed,
    without_sent_figures,
)
from submission.requirement_adapter import parse_response as parse_requirement_response
from submission.requirement_contracts import (
    RequirementError,
    RequirementErrorCode,
    RequirementInput,
    RequirementLimits,
    RequirementResponse,
)
from submission.requirement_validation import (
    admit_guide,
    is_sent,
    response_failure,
    sent_block_count,
)

MAX_CHECK_CHUNKS: Final = 5
MAX_REQUIREMENT_CHUNKS: Final = 3
MAX_EVIDENCE: Final = 10  # ProposedFinding.evidence contract cap

# Strongest positive evidence first. Any chunk with supporting evidence wins; "evidence_missing"
# survives only when every chunk said so, so a chunk that could not judge ("deferred") is never
# turned into a claim of absence. The policy layer still re-derives the effective judgment.
JUDGMENT_PRECEDENCE: Final[tuple[Judgment, ...]] = (
    "evidence_found",
    "partially_satisfied",
    "explicit_noncompliance",
    "deferred",
    "evidence_missing",
)


class ChunkOverflowError(ValueError):
    """The document cannot be split into the allowed number of budget-sized chunks."""


def plan_chunks(
    sizes: Sequence[int], *, capacity: int, max_count: int, max_chunks: int
) -> tuple[tuple[int, int], ...]:
    """Greedy consecutive [start, end) slices; never splits an item."""
    slices: list[tuple[int, int]] = []
    start, used = 0, 0
    for index, size in enumerate(sizes):
        if size > capacity or max_count < 1:
            raise ChunkOverflowError
        if used + size > capacity or index - start >= max_count:
            slices.append((start, index))
            start, used = index, 0
        used += size
    slices.append((start, len(sizes)))
    if len(slices) > max_chunks:
        raise ChunkOverflowError
    return tuple(slices)


def merge_judgment(judgments: Sequence[Judgment]) -> Judgment:
    return min(judgments, key=JUDGMENT_PRECEDENCE.index)


def _with_blocks(document: CommonDocument, blocks: tuple) -> CommonDocument:
    return document.model_copy(update={"blocks": blocks})


def check_chunk_contexts(
    ctx: ReportCheckContext, limits: ReportCheckLimits
) -> tuple[ReportCheckContext, ...]:
    """The original context when it fits, otherwise one context per report slice."""
    sent = tuple(block for block in ctx.report.blocks if is_sent(block))
    guide_sent = sent_block_count(ctx.guide)
    if guide_sent + len(sent) <= limits.max_blocks:
        try:
            validate_context_budget(ctx, limits)
        except ReportCheckError as error:
            if error.code != ReportCheckErrorCode.INPUT_LIMIT:
                raise
        else:
            return (ctx,)
    if len(sent) > limits.max_blocks:  # merged reviewed_block_ids is capped by the contract
        raise ReportCheckError(ReportCheckErrorCode.INPUT_LIMIT)
    try:
        slices = plan_chunks(
            [len(block.raw_text) for block in sent],
            capacity=limits.max_input_characters - criteria_budget_size(ctx),
            max_count=limits.max_blocks - guide_sent,
            max_chunks=MAX_CHECK_CHUNKS,
        )
    except ChunkOverflowError:
        raise ReportCheckError(ReportCheckErrorCode.INPUT_LIMIT) from None
    return tuple(
        ctx.model_copy(update={"report": _with_blocks(ctx.report, sent[start:end])})
        for start, end in slices
    )


def merged_check_limits(limits: ReportCheckLimits) -> ReportCheckLimits:
    return limits.model_copy(
        update={
            "max_input_characters": limits.max_input_characters * MAX_CHECK_CHUNKS,
            "max_response_bytes": limits.max_response_bytes * MAX_CHECK_CHUNKS,
        }
    )


def _scope_error(branch: diagnostics.ContractBranch) -> ReportCheckError:
    diagnostics.contract_failure(ReportCheckErrorCode.INVALID_SCOPE, branch)
    return ReportCheckError(ReportCheckErrorCode.INVALID_SCOPE)


def _assert_scope(is_valid: bool, branch: diagnostics.ContractBranch) -> None:  # noqa: FBT001
    if not is_valid:
        raise _scope_error(branch)


def _check_chunk(
    ctx: ReportCheckContext, chunk: ReportCheckContext, response: ReportCheckResponse
) -> None:
    source = ctx.report.source
    if (
        response.report_source_id != source.source_id
        or response.report_document_version_id != source.document_version_id
        or response.report_source_sha256 != source.content_sha256
    ):
        diagnostics.contract_failure(ReportCheckErrorCode.SOURCE_MISMATCH, "source_binding")
        raise ReportCheckError(ReportCheckErrorCode.SOURCE_MISMATCH)
    if response.criteria_sha256 != criteria_fingerprint(ctx):
        diagnostics.contract_failure(ReportCheckErrorCode.CRITERIA_MISMATCH, "criteria_binding")
        raise ReportCheckError(ReportCheckErrorCode.CRITERIA_MISMATCH)
    reviewed = response.reviewed_block_ids
    _assert_scope(len(set(reviewed)) == len(reviewed), "scope_duplicate")
    _assert_scope(
        set(reviewed) <= {block.block_id for block in chunk.report.blocks}, "scope_unsubmitted"
    )
    for item in response.items:
        for found in (item.evidence, *(sub.evidence for sub in item.subconditions)):
            _assert_scope(
                all(entry.citation.block_id in reviewed for entry in found), "scope_cite_unreviewed"
            )


def _merge_evidence(findings: Sequence[ProposedFinding]) -> tuple[ReportEvidence, ...]:
    merged: list[ReportEvidence] = []
    for finding in findings:
        merged.extend(entry for entry in finding.evidence if entry not in merged)
    return tuple(merged[:MAX_EVIDENCE])


def _winner(findings: Sequence[ProposedFinding]) -> tuple[Judgment, str]:
    judgment = merge_judgment([finding.proposed_judgment for finding in findings])
    reason = next(f.reason for f in findings if f.proposed_judgment == judgment)
    return judgment, reason


def _merge_item(expected: ExpectedReportItem, found: Sequence[ReportItem]) -> ReportItem | None:
    """None when no chunk returned the item, so validation reports it exactly as today."""
    if not found:
        return None
    subconditions: list[ReportSubcondition] = []
    for sub_id in expected.subcondition_ids:
        subs = [s for item in found for s in item.subconditions if s.subcondition_id == sub_id]
        if subs:
            judgment, reason = _winner(subs)
            subconditions.append(
                ReportSubcondition(
                    subcondition_id=sub_id,
                    proposed_judgment=judgment,
                    reason=reason,
                    evidence=_merge_evidence(subs),
                )
            )
    judgment, reason = _winner(found)
    return ReportItem(
        requirement_id=expected.requirement_id,
        proposed_judgment=judgment,
        reason=reason,
        evidence=_merge_evidence(found),
        subconditions=tuple(subconditions),
    )


def merge_check_completions(
    ctx: ReportCheckContext,
    chunks: Sequence[ReportCheckContext],
    raws: Sequence[str],
    limits: ReportCheckLimits,
) -> str:
    """One ReportCheckResponse JSON; omitted items count as "no evidence in that chunk"."""
    responses = [
        with_cited_blocks_reviewed(
            without_sent_figures(parse_response(raw, limits, chunk), chunk),
            submitted_report_block_ids(chunk),
        )
        for chunk, raw in zip(chunks, raws, strict=True)
    ]
    for chunk, response in zip(chunks, responses, strict=True):
        _check_chunk(ctx, chunk, response)
    reviewed = {block_id for response in responses for block_id in response.reviewed_block_ids}
    expected = (
        ExpectedReportItem(
            requirement_id=item.requirement_id,
            subcondition_ids=tuple(sub.subcondition_id for sub in item.subconditions),
        )
        for item in ctx.criteria.items
        if item.included and item.application_status == "applies"
    )
    merged = (
        _merge_item(
            entry,
            [
                item
                for response in responses
                for item in response.items
                if item.requirement_id == entry.requirement_id
            ],
        )
        for entry in expected
    )
    head = responses[0]
    return ReportCheckResponse(
        schema_version="1",
        criteria_sha256=head.criteria_sha256,
        report_source_id=head.report_source_id,
        report_document_version_id=head.report_document_version_id,
        report_source_sha256=head.report_source_sha256,
        reviewed_block_ids=tuple(
            block.block_id
            for block in ctx.report.blocks
            if block.block_id in reviewed and block.raw_text.strip()
        ),
        items=tuple(item for item in merged if item is not None),
    ).model_dump_json()


def requirement_chunk_documents(
    guide: CommonDocument, limits: RequirementLimits
) -> tuple[CommonDocument, ...]:
    """The guide itself when it fits, otherwise one document per slice of sent blocks."""
    try:
        _ = admit_guide(guide, limits)
    except RequirementError as error:
        if error.code != RequirementErrorCode.INPUT_LIMIT:
            raise
    else:
        return (guide,)
    sent = tuple(block for block in guide.blocks if is_sent(block))
    try:
        slices = plan_chunks(
            [len(block.raw_text) for block in sent],
            capacity=limits.max_input_characters,
            max_count=limits.max_blocks,
            max_chunks=MAX_REQUIREMENT_CHUNKS,
        )
    except ChunkOverflowError:
        raise RequirementError(RequirementErrorCode.INPUT_LIMIT) from None
    return tuple(_with_blocks(guide, sent[start:end]) for start, end in slices)


def merged_requirement_limits(limits: RequirementLimits) -> RequirementLimits:
    return limits.model_copy(
        update={
            "max_input_characters": limits.max_input_characters * MAX_REQUIREMENT_CHUNKS,
            "max_response_bytes": limits.max_response_bytes * MAX_REQUIREMENT_CHUNKS,
        }
    )


def _renumbered(item: RequirementInput, number: int) -> RequirementInput:
    identifier = f"R{number}"
    return item.model_copy(
        update={
            "requirement_id": identifier,
            "subconditions": tuple(
                sub.model_copy(update={"subcondition_id": f"{identifier}-S{index}"})
                for index, sub in enumerate(item.subconditions, 1)
            ),
        }
    )


def merge_requirement_completions(
    guide: CommonDocument, raws: Sequence[str], limits: RequirementLimits
) -> str:
    """Concatenate chunk drafts in order with fresh R<n> / R<n>-S<m> IDs; no de-duplication."""
    responses = [parse_requirement_response(raw, limits, guide.source) for raw in raws]
    items = [item for response in responses for item in response.requirements]
    if len(items) > limits.max_requirements:
        raise response_failure(
            RequirementErrorCode.RESPONSE_LIMIT,
            "merge_count",
            len(items),
            limits.max_requirements,
        )
    head = responses[0]
    return RequirementResponse(
        schema_version="1",
        source_id=head.source_id,
        document_version_id=head.document_version_id,
        source_sha256=head.source_sha256,
        requirements=tuple(_renumbered(item, number) for number, item in enumerate(items, 1)),
    ).model_dump_json()
