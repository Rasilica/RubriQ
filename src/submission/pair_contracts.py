from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from submission.conversion_contracts import ConversionConfig
from submission.document_contracts import CommonDocument, ProcessingStatus
from submission.evidence_selection import EvidenceSelection as EvidenceSelection  # noqa: PLC0414
from submission.hancom_contracts import HancomConversionConfig
from submission.hwp_reading_contracts import HwpReadConfig
from submission.models import DocumentRole, FrozenModel
from submission.semantic_contracts import SemanticArchive


class PairRuntime(FrozenModel):
    docx: ConversionConfig | None = None
    hancom: HancomConversionConfig | None = None
    hwp: HwpReadConfig | None = None
    pdftoppm: Path | None = None


class PairErrorCode(StrEnum):
    NOT_FOUND = "session_not_found"
    BUSY = "preparation_busy"
    FAILED = "pair_failed"
    LIMIT = "session_limit"
    UNAVAILABLE = "asset_unavailable"
    INVALID = "invalid_selection"
    TIMEOUT = "preparation_timeout"


class PairError(Exception):
    code: PairErrorCode

    def __init__(self, code: PairErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class RoleView(FrozenModel):
    role: DocumentRole
    document: CommonDocument | None
    extraction_status: ProcessingStatus
    rendering_status: ProcessingStatus
    error_code: str | None = None
    warnings: tuple[str, ...] = ()
    preview_page_count: int | None = None
    artifact_kind: Literal["original_pdf", "preview_pdf"] | None = None


@dataclass(frozen=True, slots=True)
class PreparedRole:
    view: RoleView
    original: bytes
    pdf: bytes | None = None

    @property
    def size(self) -> int:
        return len(self.original) + len(self.pdf or b"") + len(self.view.model_dump_json().encode())

    @property
    def available(self) -> bool:
        document = self.view.document
        return self.pdf is not None or (
            document is not None
            and document.extraction_status in (ProcessingStatus.COMPLETE, ProcessingStatus.PARTIAL)
            and document.content_review_available
        )


class SavedOrigin(FrozenModel):
    saved_id: str
    saved_at: datetime
    saved_environment: tuple[str, ...]
    current_environment: tuple[str, ...]


class SessionView(FrozenModel):
    semantic_archive: SemanticArchive | None = None
    session_id: str
    project_name: str
    expires_at: datetime
    guide: RoleView
    report: RoleView
    access_token: str | None = None
    saved_id: str | None = None
    saved_at: datetime | None = None
    saved_environment: tuple[str, ...] = ()
    current_environment: tuple[str, ...] = ()


class PairEnvelope[Data](FrozenModel):
    success: Literal[True] = True
    data: Data


class Deleted(FrozenModel):
    deleted: Literal[True] = True
