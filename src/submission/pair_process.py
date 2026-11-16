import os
import stat
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Final

from pydantic import ValidationError

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_process import run_process
from submission.document_contracts import ProcessingStatus
from submission.input_contracts import DocumentInput
from submission.models import FrozenModel
from submission.pair_contracts import PairError, PairErrorCode, PairRuntime, PreparedRole, RoleView

MAX_RESULT_BYTES: Final = 32 * 1024 * 1024
MAX_PDF_BYTES: Final = 10 * 1024 * 1024


class PairJob(FrozenModel):
    guide_filename: str
    report_filename: str
    runtime: PairRuntime
    deadline: float


class PairJobResult(FrozenModel):
    guide: RoleView
    report: RoleView


def bounded_file(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise PairError(PairErrorCode.FAILED)
        result = stream.read(maximum + 1)
    if len(result) > maximum:
        raise PairError(PairErrorCode.FAILED)
    return result


def restored_role(directory: Path, source: DocumentInput, view: RoleView) -> PreparedRole:
    if view.role != source.role:
        raise PairError(PairErrorCode.FAILED)
    document = view.document
    if document is None:
        return PreparedRole(view, source.content if len(source.content) <= MAX_PDF_BYTES else b"")
    if (
        document.source.content_sha256 != sha256(source.content).hexdigest()
        or document.source.role != source.role
    ):
        raise PairError(PairErrorCode.FAILED)
    pdf = None
    if view.artifact_kind is not None:
        pdf = bounded_file(directory / f"{source.role}.pdf", MAX_PDF_BYTES)
        if (
            not document.artifacts
            or document.artifacts[0].artifact_sha256 != sha256(pdf).hexdigest()
        ):
            raise PairError(PairErrorCode.FAILED)
    return PreparedRole(view, source.content, pdf)


def timeout_role(directory: Path, source: DocumentInput) -> PreparedRole:
    checkpoint = directory / f"{source.role}.json"
    if checkpoint.exists():
        view = RoleView.model_validate_json(bounded_file(checkpoint, MAX_RESULT_BYTES))
        if view.document is not None and view.rendering_status == ProcessingStatus.NOT_STARTED:
            view = view.model_copy(
                update={
                    "document": view.document.model_copy(
                        update={
                            "rendering_status": ProcessingStatus.FAILED,
                        }
                    ),
                    "rendering_status": ProcessingStatus.FAILED,
                    "error_code": "preparation_timeout",
                }
            )
        return restored_role(directory, source, view)
    return PreparedRole(
        RoleView(
            role=source.role,
            document=None,
            extraction_status=ProcessingStatus.FAILED,
            rendering_status=ProcessingStatus.FAILED,
            error_code="preparation_timeout",
        ),
        source.content if len(source.content) <= MAX_PDF_BYTES else b"",
    )


def recover_timeout(
    directory: Path,
    guide: DocumentInput,
    report: DocumentInput,
) -> tuple[PreparedRole, PreparedRole]:
    first, second = timeout_role(directory, guide), timeout_role(directory, report)
    if not (first.available or second.available):
        raise PairError(PairErrorCode.TIMEOUT)
    return first, second


def run_preparation(
    guide: DocumentInput,
    report: DocumentInput,
    runtime: PairRuntime,
    *,
    timeout_seconds: float = 180.0,
) -> tuple[PreparedRole, PreparedRole]:
    deadline = monotonic() + timeout_seconds
    renderer_grace = max(
        (
            2.0,
            *(
                config.terminate_grace_seconds
                for config in (runtime.docx, runtime.hancom)
                if config is not None
            ),
        )
    )
    # stop_group may wait for TERM, reap, and final group exit; HWP uses 2 seconds.
    cleanup_grace = max(10.0, 3 * renderer_grace + 2.0)
    try:
        with TemporaryDirectory(prefix="document-pair-") as temporary:
            directory = Path(temporary)
            _ = (directory / "guide.input").write_bytes(guide.content)
            _ = (directory / "report.input").write_bytes(report.content)
            job = PairJob(
                guide_filename=guide.filename,
                report_filename=report.filename,
                runtime=runtime,
                deadline=deadline,
            )
            _ = (directory / "job.json").write_text(job.model_dump_json())
            try:
                _ = run_process(
                    (sys.executable, "-m", "submission.pair_worker", str(directory)),
                    Path(__file__).parents[1],
                    deadline,
                    cleanup_grace,
                )
            except ConversionError as error:
                if error.code == ConversionErrorCode.TIMEOUT:
                    return recover_timeout(directory, guide, report)
                raise
            if monotonic() >= deadline:
                return recover_timeout(directory, guide, report)
            result = PairJobResult.model_validate_json(
                bounded_file(directory / "result.json", MAX_RESULT_BYTES)
            )
            return restored_role(directory, guide, result.guide), restored_role(
                directory, report, result.report
            )
    except ConversionError as error:
        code = (
            PairErrorCode.TIMEOUT
            if error.code == ConversionErrorCode.TIMEOUT
            else PairErrorCode.FAILED
        )
        raise PairError(code) from None
    except (OSError, ValidationError):
        raise PairError(PairErrorCode.FAILED) from None
