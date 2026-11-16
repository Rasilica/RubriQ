from submission.document_contracts import CharacterRange
from submission.report_check_contracts import (
    ReportCheckContext,
    ReportCheckResponse,
    ReportEvidence,
    ReportItem,
    ReportSubcondition,
)
from submission.report_check_validation import criteria_fingerprint
from submission.requirement_contracts import CitationInput


def structure_response(context: ReportCheckContext) -> str:
    blocks = tuple(block for block in context.report.blocks if block.raw_text.strip())
    evidence = tuple(
        ReportEvidence(
            citation=CitationInput(
                block_id=block.block_id,
                char_range=CharacterRange(start=0, end=len(block.raw_text)),
                quote=block.raw_text,
            ),
            evidence_role="unknown",
            relation="합성 구조 위치 이동 예시이며 요구사항 충족 근거로 판정하지 않습니다.",
        )
        for block in blocks[:10]
    )
    reason = "합성 구조 인용의 정확한 위치만 확인했습니다. 의미 충족과 원본 분량은 보류합니다."
    return ReportCheckResponse(
        schema_version="1",
        criteria_sha256=criteria_fingerprint(context),
        report_source_id=context.report.source.source_id,
        report_document_version_id=context.report.source.document_version_id,
        report_source_sha256=context.report.source.content_sha256,
        reviewed_block_ids=tuple(block.block_id for block in blocks),
        items=tuple(
            ReportItem(
                requirement_id=item.requirement_id,
                proposed_judgment="deferred",
                reason=reason,
                evidence=evidence if item.requirement_id == "R1" else (),
                subconditions=tuple(
                    ReportSubcondition(
                        subcondition_id=sub.subcondition_id,
                        proposed_judgment="deferred",
                        reason=reason,
                        evidence=(),
                    )
                    for sub in item.subconditions
                ),
            )
            for item in context.criteria.items
            if item.included and item.application_status == "applies"
        ),
    ).model_dump_json()
