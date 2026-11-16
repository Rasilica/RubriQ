from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Literal, override

from pydantic import ConfigDict, Field

from submission.document_contracts import DocumentArtifact, DocumentSource, Sha256
from submission.input_contracts import InputLimits
from submission.models import FrozenModel


class ConversionErrorCode(StrEnum):
    INVALID_CONFIG = "invalid_config"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    UNSUPPORTED_FORMAT = "unsupported_format"
    UNSUPPORTED_ACTIVE_CONTENT = "unsupported_active_content"
    BUSY = "conversion_busy"
    RENDERER_UNAVAILABLE = "renderer_unavailable"
    RENDERER_FAILED = "renderer_failed"
    TIMEOUT = "conversion_timeout"
    PROCESS_OUTPUT_LIMIT = "process_output_limit"
    OUTPUT_MISSING = "output_missing"
    OUTPUT_INVALID = "output_invalid"
    OUTPUT_LIMIT = "output_limit"
    IO_ERROR = "conversion_io_error"
    CLEANUP_FAILED = "cleanup_failed"


class ConversionError(Exception):
    code: ConversionErrorCode

    def __init__(self, code: ConversionErrorCode) -> None:
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code.value


class ConversionConfig(FrozenModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)

    soffice: Path
    work_root: Path
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 60.0
    terminate_grace_seconds: Annotated[float, Field(gt=0, le=10, allow_inf_nan=False)] = 2.0
    input_limits: InputLimits = InputLimits()
    max_output_bytes: Annotated[int, Field(gt=0)] = 10 * 1024 * 1024
    max_output_pages: Annotated[int, Field(gt=0)] = 50


class FontRecord(FrozenModel):
    location: str
    byte_size: int
    sha256: Sha256


class FontManifest(FrozenModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    declared_roots: tuple[str, ...] = ()
    unavailable_or_skipped: tuple[str, ...] = ()
    inventory_scope: Literal["bounded_known_system_directories"] = (
        "bounded_known_system_directories"
    )
    inventory_complete: Literal[False] = False
    inventory: tuple[FontRecord, ...]
    rendered_pdf_font_names: tuple[str, ...]
    resolution_verified: Literal[False] = False


@dataclass(frozen=True, slots=True)
class ConversionResult:
    source: DocumentSource
    artifact: DocumentArtifact
    pdf_bytes: bytes
    preview_page_count: int
    font_manifest: FontManifest
    warnings: tuple[str, ...]
