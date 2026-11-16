from hashlib import sha256
from pathlib import Path
from typing import Final, assert_never

from pydantic import ValidationError

from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput, UploadError
from submission.result_contracts import (
    LoadedRaster,
    RasterDocument,
    RasterManifest,
    ResultCase,
    ResultError,
    ResultErrorCode,
)

SAMPLES: Final = Path(__file__).resolve().parents[2] / "samples"
MAX_ASSET_BYTES: Final = 10 * 1024 * 1024
DOCUMENT_IDS: Final = ("guide", "normal", "missing", "over_limit")


def bounded_read(path: Path, maximum: int = MAX_ASSET_BYTES) -> bytes:
    try:
        with path.open("rb") as stream:
            content = stream.read(maximum + 1)
    except OSError:
        raise ResultError(ResultErrorCode.UNAVAILABLE) from None
    if len(content) > maximum:
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    return content


def report_document_id(case: ResultCase) -> str:
    match case:
        case ResultCase.DOCX_STRUCTURE | ResultCase.HWPX_STRUCTURE:
            raise ResultError(ResultErrorCode.NOT_FOUND)
        case ResultCase.NORMAL | ResultCase.UNCONFIRMED_SCOPE:
            return "normal"
        case ResultCase.MISSING:
            return "missing"
        case ResultCase.OVER_LIMIT:
            return "over_limit"
        case _:
            assert_never(case)


def read_manifest(samples: Path) -> RasterManifest:
    try:
        manifest = RasterManifest.model_validate_json(
            bounded_read(samples / "result-demos/manifest.json", 128 * 1024), strict=True
        )
    except ValidationError:
        raise ResultError(ResultErrorCode.UNAVAILABLE) from None
    if tuple(item.document_id for item in manifest.documents) != DOCUMENT_IDS:
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    return manifest


def validate_paths(descriptor: RasterDocument) -> None:
    expected_pdf = (
        "result-demos/over-limit.pdf"
        if descriptor.document_id == "over_limit"
        else f"pdf/{descriptor.document_id}.pdf"
    )
    if descriptor.pdf_path != expected_pdf:
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    for number, page in enumerate(descriptor.pages, start=1):
        if page.page_number != number or page.image_path != (
            f"result-demos/pages/{descriptor.document_id}-{number}.png"
        ):
            raise ResultError(ResultErrorCode.UNAVAILABLE)


def load_raster(document_id: str, *, samples: Path = SAMPLES) -> LoadedRaster:
    if document_id not in DOCUMENT_IDS:
        raise ResultError(ResultErrorCode.NOT_FOUND)
    manifest = read_manifest(samples)
    descriptor = next(item for item in manifest.documents if item.document_id == document_id)
    validate_paths(descriptor)
    pdf = bounded_read(samples / descriptor.pdf_path)
    if sha256(pdf).hexdigest() != descriptor.pdf_sha256:
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    try:
        extracted = extract_pdf(PdfInput(Path(descriptor.pdf_path).name, pdf, DocumentRole.REPORT))
    except UploadError:
        raise ResultError(ResultErrorCode.UNAVAILABLE) from None
    if len(extracted.pages) != len(descriptor.pages) or extracted.parser_warning:
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    images: tuple[bytes, ...] = ()
    for page in descriptor.pages:
        image = bounded_read(samples / page.image_path)
        if (
            sha256(image).hexdigest() != page.image_sha256
            or image[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or int.from_bytes(image[16:20], "big") != page.width
            or int.from_bytes(image[20:24], "big") != page.height
        ):
            raise ResultError(ResultErrorCode.UNAVAILABLE)
        images += (image,)
    return LoadedRaster(descriptor=descriptor, pdf_bytes=pdf, images=images)
