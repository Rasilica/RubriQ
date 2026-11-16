import json
from pathlib import Path

from requirement_helpers import guide_document, response_payload

from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput
from submission.pdf_adapter import adapt_pdf
from submission.report_check_contracts import ReportCheckContext
from submission.report_check_validation import criteria_fingerprint
from submission.requirement_adapter import build_requirement_draft
from submission.review_contracts import EditableItem, ReviewSession, WorkingCopyRequest
from submission.review_logic import confirm_session, initial_item, save_working_copy


def context():
    guide = guide_document()
    draft = build_requirement_draft(guide, json.dumps(response_payload()))
    session = ReviewSession(
        session_id="test",
        original_draft=draft,
        source_blocks=(),
        items=tuple(initial_item(item) for item in draft.requirements),
    )
    items = tuple(
        item.model_copy(
            update={"application_status": "does_not_apply", "application_reason": "개인"}
        )
        if item.classification == "conditional"
        else item
        for item in session.items
    )
    saved = save_working_copy(
        session,
        WorkingCopyRequest(
            expected_revision=0,
            items=tuple(
                EditableItem.model_validate(item.model_dump(exclude={"edited_fields"}))
                for item in items
            ),
        ),
    )
    confirmed = confirm_session(saved, saved.revision, 10)
    path = Path(__file__).resolve().parents[1] / "samples/pdf/normal.pdf"
    source = PdfInput(path.name, path.read_bytes(), DocumentRole.REPORT)
    report = adapt_pdf(source, extract_pdf(source))
    return ReportCheckContext(
        guide=guide, original_draft=draft, criteria=confirmed.versions[-1], report=report
    )


def payload(ctx):
    return {
        "schema_version": "1",
        "criteria_sha256": criteria_fingerprint(ctx),
        "report_source_id": ctx.report.source.source_id,
        "report_document_version_id": ctx.report.source.document_version_id,
        "report_source_sha256": ctx.report.source.content_sha256,
        "reviewed_block_ids": [
            block.block_id for block in ctx.report.blocks if block.raw_text.strip()
        ],
        "items": [
            {
                "requirement_id": item.requirement_id,
                "proposed_judgment": "evidence_missing",
                "reason": "검토 범위에서 근거 미확인",
                "evidence": [],
                "subconditions": [
                    {
                        "subcondition_id": sub.subcondition_id,
                        "proposed_judgment": "evidence_missing",
                        "reason": "근거 미확인",
                        "evidence": [],
                    }
                    for sub in item.subconditions
                ],
            }
            for item in ctx.criteria.items
            if item.included and item.application_status == "applies"
        ],
    }


def evidence(ctx, role="content"):
    block = next(block for block in ctx.report.blocks if block.raw_text.strip())
    return {
        "citation": {
            "block_id": block.block_id,
            "char_range": {"start": 0, "end": len(block.raw_text)},
            "quote": block.raw_text,
        },
        "evidence_role": role,
        "relation": "응답자가 주장하는 관련 근거",
    }
