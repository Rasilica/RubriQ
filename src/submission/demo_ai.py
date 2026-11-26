"""Demo mode: saved example answers for the bundled sample documents. No AI is called."""

from hashlib import sha256
from pathlib import Path
from typing import Final

from submission.cloud_contracts import TextCompletion
from submission.document_contracts import CommonDocument
from submission.report_check_contracts import (
    ReportCheckContext,
    ReportCheckResponse,
    ReportItem,
    ReportSubcondition,
)
from submission.report_check_validation import criteria_fingerprint
from submission.semantic_contracts import SemanticCode, SemanticError

SAMPLES: Final = Path(__file__).resolve().parents[2] / "samples"
REPORTS: Final = ("normal", "missing", "paraphrased")
UNCOVERED: Final = "체험 모드의 저장된 예시 응답에 없는 항목입니다."


def is_sample(document: CommonDocument, name: str) -> bool:
    content = (SAMPLES / "pdf" / f"{name}.pdf").read_bytes()
    return document.source.content_sha256 == sha256(content).hexdigest()


def requirements_answer(guide: CommonDocument) -> TextCompletion:
    if not is_sample(guide, "guide"):
        raise SemanticError(SemanticCode.DEMO_SAMPLE_ONLY)
    path = SAMPLES / "requirements/guide-offline-response.json"
    return TextCompletion(suggestion=path.read_text(encoding="utf-8"))


def uncovered(subcondition_id: str) -> ReportSubcondition:
    return ReportSubcondition(
        subcondition_id=subcondition_id,
        proposed_judgment="deferred",
        reason=UNCOVERED,
        evidence=(),
    )


def adapt_item(
    saved: ReportItem | None, requirement_id: str, subcondition_ids: tuple[str, ...]
) -> ReportItem:
    """Follow the user's confirmed criteria, which may differ from the saved answer."""
    if saved is None:
        return ReportItem(
            requirement_id=requirement_id,
            proposed_judgment="deferred",
            reason=UNCOVERED,
            evidence=(),
            subconditions=tuple(uncovered(identifier) for identifier in subcondition_ids),
        )
    known = {sub.subcondition_id: sub for sub in saved.subconditions}
    return saved.model_copy(
        update={
            "subconditions": tuple(
                known.get(identifier) or uncovered(identifier) for identifier in subcondition_ids
            )
        }
    )


def check_answer(context: ReportCheckContext) -> TextCompletion:
    name = next((item for item in REPORTS if is_sample(context.report, item)), None)
    if name is None or not is_sample(context.guide, "guide"):
        raise SemanticError(SemanticCode.DEMO_SAMPLE_ONLY)
    path = SAMPLES / "checks" / f"{name}-offline-response.json"
    saved = ReportCheckResponse.model_validate_json(path.read_text(encoding="utf-8"), strict=True)
    by_id = {item.requirement_id: item for item in saved.items}
    response = saved.model_copy(
        update={
            "criteria_sha256": criteria_fingerprint(context),
            "report_source_id": context.report.source.source_id,
            "report_document_version_id": context.report.source.document_version_id,
            "report_source_sha256": context.report.source.content_sha256,
            "reviewed_block_ids": tuple(block.block_id for block in context.report.blocks),
            "items": tuple(
                adapt_item(
                    by_id.get(item.requirement_id),
                    item.requirement_id,
                    tuple(sub.subcondition_id for sub in item.subconditions),
                )
                for item in context.criteria.items
                if item.included and item.application_status == "applies"
            ),
        }
    )
    return TextCompletion(suggestion=response.model_dump_json())
