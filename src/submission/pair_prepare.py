import logging
from collections.abc import Callable
from time import monotonic
from typing import assert_never

from submission.conversion_contracts import ConversionError, ConversionResult
from submission.document_contracts import CommonDocument, ProcessingStatus
from submission.docx_conversion import convert_docx
from submission.docx_reader import read_docx
from submission.extraction import extract_pdf
from submission.formats import inspect_document
from submission.hancom_conversion import convert_hancom
from submission.hwp_reader import read_hwp
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import DocumentInput, InputValidationError
from submission.models import PdfInput, UploadError
from submission.ocr_pipeline import PageReader, apply_ocr
from submission.pair_contracts import PairError, PairErrorCode, PairRuntime, PreparedRole, RoleView
from submission.pdf_adapter import adapt_pdf

LOGGER = logging.getLogger(__name__)


def remaining(deadline: float, maximum: float) -> float:
    value = min(maximum, deadline - monotonic())
    if value <= 0:
        raise PairError(PairErrorCode.TIMEOUT)
    return value


def read_source(source: DocumentInput, runtime: PairRuntime, deadline: float) -> CommonDocument:
    kind = inspect_document(source).source.detected_format
    _ = remaining(deadline, 180.0)
    match kind:
        case "pdf":
            pdf = PdfInput(source.filename, source.content, source.role)
            return adapt_pdf(pdf, extract_pdf(pdf))
        case "docx":
            return read_docx(source)
        case "hwpx":
            return read_hwpx(source)
        case "hwp":
            if runtime.hwp is None:
                raise PairError(PairErrorCode.UNAVAILABLE)
            config = runtime.hwp.model_copy(
                update={"timeout_seconds": remaining(deadline, runtime.hwp.timeout_seconds)}
            )
            return read_hwp(source, config)
        case _:
            assert_never(kind)


def convert_source(
    source: DocumentInput, runtime: PairRuntime, deadline: float
) -> ConversionResult:
    if source.filename.lower().endswith(".docx"):
        if runtime.docx is None:
            raise PairError(PairErrorCode.UNAVAILABLE)
        return convert_docx(
            source,
            runtime.docx.model_copy(
                update={"timeout_seconds": remaining(deadline, runtime.docx.timeout_seconds)}
            ),
        )
    if runtime.hancom is None:
        raise PairError(PairErrorCode.UNAVAILABLE)
    return convert_hancom(
        source,
        runtime.hancom.model_copy(
            update={"timeout_seconds": remaining(deadline, runtime.hancom.timeout_seconds)}
        ),
    )


def failure_code(error: Exception, source: DocumentInput) -> str:
    if isinstance(error, (InputValidationError, ConversionError, UploadError, PairError)):
        return str(error.code)
    LOGGER.error("Unexpected %s preparation failure", source.role, exc_info=error)
    return str(PairErrorCode.FAILED)


def prepare_role(
    source: DocumentInput,
    runtime: PairRuntime,
    deadline: float,
    *,
    on_read: Callable[[PreparedRole], None] | None = None,
    read_page: PageReader | None = None,
) -> PreparedRole:
    try:
        document = read_source(source, runtime, deadline)
        _ = remaining(deadline, 180.0)
    except Exception as error:  # noqa: BLE001 -- one bad document must not fail the other role.
        return PreparedRole(
            RoleView(
                role=source.role,
                document=None,
                extraction_status=ProcessingStatus.FAILED,
                rendering_status=ProcessingStatus.NOT_STARTED,
                error_code=failure_code(error, source),
            ),
            source.content if len(source.content) <= 10 * 1024 * 1024 else b"",
        )
    if document.source.detected_format == "pdf":
        document = document.model_copy(update={"rendering_status": ProcessingStatus.COMPLETE})
        count = document.page_count.artifact_page_count
        ocr = apply_ocr(document, source.content, count, runtime, deadline, read_page=read_page)
        document = ocr.document
        return PreparedRole(
            RoleView(
                role=source.role,
                document=document,
                extraction_status=document.extraction_status,
                rendering_status=ProcessingStatus.COMPLETE,
                artifact_kind="original_pdf",
                preview_page_count=count,
                warnings=ocr.warnings,
            ),
            source.content,
            source.content,
        )
    if on_read is not None:
        on_read(
            PreparedRole(
                RoleView(
                    role=source.role,
                    document=document,
                    extraction_status=document.extraction_status,
                    rendering_status=ProcessingStatus.NOT_STARTED,
                ),
                source.content,
            )
        )
    try:
        result = convert_source(source, runtime, deadline)
        _ = remaining(deadline, 180.0)
    except Exception as error:  # noqa: BLE001 -- keep the read structure when rendering crashes.
        document = document.model_copy(update={"rendering_status": ProcessingStatus.FAILED})
        return PreparedRole(
            RoleView(
                role=source.role,
                document=document,
                extraction_status=document.extraction_status,
                rendering_status=ProcessingStatus.FAILED,
                error_code=failure_code(error, source),
                warnings=("original_layout_unverified",),
            ),
            source.content,
        )
    artifact = result.artifact.model_copy(
        update={
            "renderer": result.artifact.renderer.model_copy(update={"options": ()})
            if result.artifact.renderer is not None
            else None,
            "conversion_chain": tuple(
                tool.model_copy(update={"options": ()}) for tool in result.artifact.conversion_chain
            ),
            "storage_location": None,
        }
    )
    document = document.model_copy(
        update={
            "artifacts": (artifact,),
            "rendering_status": ProcessingStatus.COMPLETE,
        }
    )
    pages = result.preview_page_count
    ocr = apply_ocr(document, result.pdf_bytes, pages, runtime, deadline, read_page=read_page)
    document = ocr.document
    return PreparedRole(
        RoleView(
            role=source.role,
            document=document,
            extraction_status=document.extraction_status,
            rendering_status=ProcessingStatus.COMPLETE,
            artifact_kind="preview_pdf",
            preview_page_count=result.preview_page_count,
            warnings=(*result.warnings, *ocr.warnings),
        ),
        source.content,
        result.pdf_bytes,
    )
