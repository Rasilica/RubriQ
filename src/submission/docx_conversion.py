import os
import platform
import re
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pydantic import TypeAdapter
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import DictionaryObject

from submission.conversion_contracts import (
    ConversionConfig,
    ConversionError,
    ConversionErrorCode,
    ConversionResult,
    FontManifest,
)
from submission.conversion_fields import neutralize_picture_fields
from submission.conversion_fonts import collect_fonts
from submission.conversion_process import run_process
from submission.conversion_profile import prepare_profile, reject_active_content
from submission.document_contracts import (
    ArtifactId,
    DocumentArtifact,
    DocumentSource,
    ToolDescriptor,
)
from submission.formats import inspect_document
from submission.input_contracts import (
    DocumentInput,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)
from submission.models import DocumentRole

CONVERSION_SLOT: Final = threading.Lock()
RENDER_OPTIONS: Final = ("--headless", "--norestore", "--unaccept=all")
PDF_OPTIONS: Final = ("--convert-to", "pdf:writer_pdf_Export")


@contextmanager
def conversion_slot() -> Generator[None]:
    """Admit at most one conversion in this Python process; never enqueue jobs."""
    if not CONVERSION_SLOT.acquire(blocking=False):
        raise ConversionError(ConversionErrorCode.BUSY)
    try:
        yield
    finally:
        CONVERSION_SLOT.release()


def read_preview(path: Path, config: ConversionConfig) -> tuple[bytes, int, tuple[str, ...]]:
    if not path.is_file() or path.is_symlink():
        raise ConversionError(ConversionErrorCode.OUTPUT_MISSING)
    with path.open("rb") as stream:
        content = stream.read(config.max_output_bytes + 1)
    if len(content) > config.max_output_bytes:
        raise ConversionError(ConversionErrorCode.OUTPUT_LIMIT)
    try:
        inspection = inspect_document(
            DocumentInput("preview.pdf", content, role=DocumentRole.REPORT),
            InputLimits(max_bytes=config.max_output_bytes, max_pdf_pages=config.max_output_pages),
        )
        if inspection.parser_warning:
            raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
        reader = PdfReader(BytesIO(content), strict=True)
        names = tuple(sorted({name for page in reader.pages for name in pdf_font_names(page)}))
        return content, len(reader.pages), names
    except InputValidationError as error:
        if error.code in {InputErrorCode.FILE_TOO_LARGE, InputErrorCode.TOO_MANY_PAGES}:
            raise ConversionError(ConversionErrorCode.OUTPUT_LIMIT) from error
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID) from error
    except (PyPdfError, ValueError, KeyError) as error:
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID) from error


def pdf_font_names(page: DictionaryObject) -> tuple[str, ...]:
    if "/Resources" not in page:
        return ()
    resolved = page["/Resources"].get_object()
    if not isinstance(resolved, DictionaryObject):
        return ()
    if "/Font" not in resolved:
        return ()
    font_map = resolved["/Font"].get_object()
    if not isinstance(font_map, DictionaryObject):
        return ()
    names: list[str] = []
    for key in TypeAdapter(tuple[str, ...]).validate_python(tuple(font_map)):
        descriptor = font_map[key].get_object()
        if isinstance(descriptor, DictionaryObject) and "/BaseFont" in descriptor:
            names.append(str(descriptor["/BaseFont"]))
    return tuple(names)


def render_job(
    source: DocumentInput,
    identity: DocumentSource,
    config: ConversionConfig,
    directory: Path,
    deadline: float,
) -> ConversionResult:
    profile = prepare_profile(directory)
    executable = str(config.soffice.absolute())
    base = (executable, *RENDER_OPTIONS, f"-env:UserInstallation={profile.as_uri()}")
    version_output = run_process(
        (*base, "--version"), directory, deadline, config.terminate_grace_seconds
    )
    version = version_output.decode("utf-8", errors="replace").strip()
    if re.fullmatch(r"LibreOffice [0-9]+(?:\.[0-9]+){1,4}(?: [0-9a-f]+)?", version) is None:
        raise ConversionError(ConversionErrorCode.RENDERER_UNAVAILABLE)
    input_path = directory / "source.docx"
    _ = input_path.write_bytes(source.content)
    output = directory / "output"
    output.mkdir(mode=0o700)
    arguments = (*base, *PDF_OPTIONS, "--outdir", str(output), str(input_path))
    _ = run_process(arguments, directory, deadline, config.terminate_grace_seconds)
    content, pages, fonts = read_preview(output / "source.pdf", config)
    manifest = collect_fonts(fonts, deadline)
    if time.monotonic() >= deadline:
        raise ConversionError(ConversionErrorCode.TIMEOUT)
    renderer = ToolDescriptor(
        name="LibreOffice",
        version=version,
        options=(
            *RENDER_OPTIONS,
            *PDF_OPTIONS,
            "isolated_user_profile",
            "macros_disabled",
            "active_content_disabled",
            "link_updates_never",
            "field_updates_disabled",
        ),
    )
    return build_conversion_result(identity, (content, pages), manifest, renderer, (renderer,))


def build_conversion_result(
    identity: DocumentSource,
    preview: tuple[bytes, int],
    manifest: FontManifest,
    renderer: ToolDescriptor,
    chain: tuple[ToolDescriptor, ...],
) -> ConversionResult:
    content, pages = preview
    content_hash = sha256(content).hexdigest()
    artifact = DocumentArtifact(
        artifact_id=ArtifactId(f"{identity.source_id}:preview_pdf:{content_hash}"),
        artifact_sha256=content_hash,
        kind="preview_pdf",
        parent_source_id=identity.source_id,
        conversion_chain=chain,
        renderer=renderer,
        font_manifest_hash=sha256(manifest.model_dump_json().encode()).hexdigest(),
        operating_system=platform.platform(),
        created_at=datetime.now(UTC),
    )
    return ConversionResult(
        identity,
        artifact,
        content,
        pages,
        manifest,
        (
            "original_layout_unverified",
            "font_inventory_partial",
            "font_resolution_unverified",
        ),
    )


def convert_docx(source: DocumentInput, config: ConversionConfig) -> ConversionResult:
    """Produce a preview without assigning original-document page or layout authority."""
    deadline = time.monotonic() + config.timeout_seconds
    if os.name != "posix":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_PLATFORM)
    with conversion_slot():
        identity = inspect_document(source, config.input_limits).source
        if identity.detected_format != "docx":
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_FORMAT)
        # Working copy only: web INCLUDEPICTURE field codes are dropped (cached picture kept) so
        # LibreOffice never sees a URL; the checked bytes are exactly the bytes rendered.
        working = replace(source, content=neutralize_picture_fields(source.content))
        reject_active_content(working.content)
        try:
            config.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with TemporaryDirectory(prefix="docx-", dir=config.work_root) as job:
                return render_job(working, identity, config, Path(job).resolve(), deadline)
        except OSError as error:
            raise ConversionError(ConversionErrorCode.IO_ERROR) from error
