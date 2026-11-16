from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, ClassVar, Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field, computed_field


class DocumentRole(StrEnum):
    GUIDE = "guide"
    REPORT = "report"


class FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class PdfLimits(FrozenModel):
    max_bytes: Annotated[int, Field(gt=0)] = 10 * 1024 * 1024
    max_pages: Annotated[int, Field(gt=0)] = 50


@dataclass(frozen=True, slots=True)
class PdfInput:
    filename: str
    content: bytes
    role: DocumentRole


UPLOAD_STATUS: Final = {"file_too_large": 413, "body_too_large": 413, "extraction_busy": 409}


class UploadError(Exception):
    code: str
    message: str
    role: DocumentRole | None
    status_code: int

    def __init__(self, code: str, message: str, role: DocumentRole | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.role = role
        self.status_code = UPLOAD_STATUS.get(code, 422)

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class Paragraph(FrozenModel):
    id: str
    text: str


class ExtractedPage(FrozenModel):
    number: Annotated[int, Field(gt=0)]
    text: str
    paragraphs: tuple[Paragraph, ...]
    error: Literal["text_unavailable", "extraction_error"] | None = None


class ExtractedDocument(FrozenModel):
    id: str
    role: DocumentRole
    filename: str
    pages: tuple[ExtractedPage, ...]
    page_numbering: Literal["file_1_based"] = "file_1_based"
    parser_warning: bool = False

    @computed_field
    @property
    def complete(self) -> bool:
        return not self.parser_warning and all(page.error is None for page in self.pages)

    @computed_field
    @property
    def readable_pages(self) -> tuple[int, ...]:
        return tuple(page.number for page in self.pages if page.error is None)


class PreparedPair(FrozenModel):
    project_name: str
    guide: ExtractedDocument
    report: ExtractedDocument
    ai_called: Literal[False] = False
    stored: Literal[False] = False

    @computed_field
    @property
    def ready(self) -> bool:
        return self.guide.complete and self.report.complete


class PairResponse(FrozenModel):
    success: Literal[True] = True
    data: PreparedPair


class ErrorDetail(FrozenModel):
    code: str
    message: str
    role: DocumentRole | None = None


class ErrorResponse(FrozenModel):
    success: Literal[False] = False
    error: ErrorDetail


class HealthResponse(FrozenModel):
    success: Literal[True] = True
    mode: Literal["local_extraction_only"] = "local_extraction_only"
