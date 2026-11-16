# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# Run from API: PYTHONPATH=src .venv/bin/python tools/run_report_check_demo.py
import json
import sys
from enum import StrEnum
from pathlib import Path

from submission.extraction import extract_pdf
from submission.models import DocumentRole, FrozenModel, PdfInput
from submission.pdf_adapter import adapt_pdf
from submission.report_check_adapter import OfflineReportCheckAdapter
from submission.report_check_contracts import ReportCheckContext
from submission.report_check_results import ReportCheckResult
from submission.review_contracts import WorkingCopyRequest
from submission.review_logic import confirm_session, save_working_copy
from submission.review_store import demo_session


class DemoReportName(StrEnum):
    NORMAL = "normal"
    MISSING = "missing"
    PARAPHRASED = "paraphrased"


class DemoCheckResult(FrozenModel):
    report_name: DemoReportName
    check: ReportCheckResult


def demo_context(report_name: DemoReportName) -> ReportCheckContext:
    samples = Path(__file__).resolve().parents[1] / "samples"
    session = demo_session("offline-report-check")
    items = tuple(
        item.model_dump(exclude={"edited_fields"})
        | (
            {"application_status": "does_not_apply", "application_reason": "합성 문장만 사용"}
            if item.requirement_id == "R4"
            else {}
        )
        for item in session.items
    )
    request = WorkingCopyRequest.model_validate({"expected_revision": 0, "items": items})
    confirmed = confirm_session(save_working_copy(session, request), 1, 20)
    guide_input = PdfInput(
        "guide.pdf", (samples / "pdf/guide.pdf").read_bytes(), DocumentRole.GUIDE
    )
    report_path = samples / "pdf" / f"{report_name.value}.pdf"
    report_input = PdfInput(report_path.name, report_path.read_bytes(), DocumentRole.REPORT)
    return ReportCheckContext(
        guide=adapt_pdf(guide_input, extract_pdf(guide_input)),
        original_draft=confirmed.original_draft,
        criteria=confirmed.versions[0],
        report=adapt_pdf(report_input, extract_pdf(report_input)),
    )


def run_demo() -> tuple[DemoCheckResult, ...]:
    samples = Path(__file__).resolve().parents[1] / "samples/checks"
    return tuple(
        DemoCheckResult(
            report_name=name,
            check=OfflineReportCheckAdapter(
                (samples / f"{name.value}-offline-response.json").read_text(encoding="utf-8")
            ).check(demo_context(name)),
        )
        for name in DemoReportName
    )


if __name__ == "__main__":
    _ = sys.stdout.write(
        json.dumps(
            [demo.model_dump(mode="json") for demo in run_demo()], ensure_ascii=False, indent=2
        )
        + "\n"
    )
