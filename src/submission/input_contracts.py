from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, override

from pydantic import Field

from submission.document_contracts import DocumentSource
from submission.models import DocumentRole, FrozenModel

type DocumentFormat = Literal["pdf", "docx", "hwpx", "hwp"]


@dataclass(frozen=True, slots=True)
class DocumentInput:
    filename: str
    content: bytes
    role: DocumentRole
    declared_mime: str | None = None


class InputLimits(FrozenModel):
    max_bytes: Annotated[int, Field(gt=0)] = 10 * 1024 * 1024
    max_pdf_pages: Annotated[int, Field(gt=0)] = 50
    max_members: Annotated[int, Field(gt=0)] = 2000
    max_expanded_bytes: Annotated[int, Field(gt=0)] = 100 * 1024 * 1024
    max_member_bytes: Annotated[int, Field(gt=0)] = 20 * 1024 * 1024
    max_xml_bytes: Annotated[int, Field(gt=0)] = 20 * 1024 * 1024
    max_xml_nodes: Annotated[int, Field(gt=0)] = 100_000
    max_xml_depth: Annotated[int, Field(gt=0)] = 128


class InputErrorCode(StrEnum):
    EMPTY_FILE = "empty_file"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"
    EXTENSION_MISMATCH = "extension_mismatch"
    MIME_MISMATCH = "mime_mismatch"
    CORRUPT_DOCUMENT = "corrupt_document"
    ENCRYPTED_DOCUMENT = "encrypted_document"
    PROTECTED_DOCUMENT = "protected_document"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    PACKAGE_LIMIT = "package_limit"
    UNSAFE_PACKAGE_PATH = "unsafe_package_path"
    DUPLICATE_MEMBER = "duplicate_member"
    XML_LIMIT = "xml_limit"
    UNSAFE_XML = "unsafe_xml"
    EMPTY_DOCUMENT = "empty_document"
    TOO_MANY_PAGES = "too_many_pages"


class InputValidationError(Exception):
    code: InputErrorCode
    role: DocumentRole | None
    detected_format: DocumentFormat | None

    def __init__(
        self,
        code: InputErrorCode,
        role: DocumentRole | None = None,
        detected_format: DocumentFormat | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.role = role
        self.detected_format = detected_format

    @override
    def __str__(self) -> str:
        return self.code.value


class FormatDetails(FrozenModel):
    detected_format: DocumentFormat
    version: str
    members: tuple[str, ...] = ()
    content_members: tuple[str, ...] = ()
    parser_warning: bool = False


class FormatInspection(FrozenModel):
    source: DocumentSource
    declared_mime: str | None
    container_members: tuple[str, ...]
    content_members: tuple[str, ...]
    parser_warning: bool
    validation_scope: Literal["container_boundary"] = "container_boundary"
    extraction_performed: Literal[False] = False
    rendering_performed: Literal[False] = False
    stored: Literal[False] = False
