import signal
import sys
from pathlib import Path
from types import FrameType

from submission.conversion_process import request_cancellation
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.pair_contracts import PreparedRole
from submission.pair_prepare import prepare_role
from submission.pair_process import MAX_RESULT_BYTES, PairJob, PairJobResult, bounded_file


class WorkerCancelled(BaseException):
    pass


def terminate(_signum: int, _frame: FrameType | None) -> None:
    request_cancellation(WorkerCancelled())


def checkpoint(directory: Path, role: PreparedRole) -> None:
    if role.pdf is not None:
        pending = directory / f"{role.view.role}.pdf.pending"
        _ = pending.write_bytes(role.pdf)
        _ = pending.replace(directory / f"{role.view.role}.pdf")
    payload = role.view.model_dump_json(round_trip=True).encode()
    if len(payload) > MAX_RESULT_BYTES:
        raise WorkerCancelled
    pending = directory / f"{role.view.role}.json.pending"
    _ = pending.write_bytes(payload)
    _ = pending.replace(directory / f"{role.view.role}.json")


def execute(directory: Path) -> None:
    job = PairJob.model_validate_json(bounded_file(directory / "job.json", 1024 * 1024))
    guide = prepare_role(
        DocumentInput(
            job.guide_filename,
            bounded_file(directory / "guide.input", 10 * 1024 * 1024 + 1),
            DocumentRole.GUIDE,
        ),
        job.runtime,
        job.deadline,
        on_read=lambda role: checkpoint(directory, role),
    )
    checkpoint(directory, guide)
    report = prepare_role(
        DocumentInput(
            job.report_filename,
            bounded_file(directory / "report.input", 10 * 1024 * 1024 + 1),
            DocumentRole.REPORT,
        ),
        job.runtime,
        job.deadline,
        on_read=lambda role: checkpoint(directory, role),
    )
    checkpoint(directory, report)
    payload = (
        PairJobResult(guide=guide.view, report=report.view)
        .model_dump_json(round_trip=True)
        .encode()
    )
    if len(payload) > MAX_RESULT_BYTES:
        raise WorkerCancelled
    _ = (directory / "result.json").write_bytes(payload)


def main() -> None:
    _ = signal.signal(signal.SIGTERM, terminate)
    try:
        execute(Path(sys.argv[1]))
    except WorkerCancelled:
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
