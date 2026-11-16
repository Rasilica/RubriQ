from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class FixtureModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class ManifestDocument(FixtureModel):
    id: str
    path: str
    format: str
    version: str | None
    family_id: str
    sha256: str
    size_bytes: int
    provenance: str
    authoring_application: None
    human_review_completed: bool
    independent_evaluation: bool
    authored_app_original: bool
    rendering_verified: bool
    full_document_reader_verified: bool


class Manifest(FixtureModel):
    schema_version: int
    usage: str
    generator: str
    documents: tuple[ManifestDocument, ...]


class XmlLocator(FixtureModel):
    member: str
    path: str
    original_page: None
    section_reading_index: int | None = None


class RecordLocator(FixtureModel):
    stream: str
    record_index: int
    record_offset: int
    tag_id: int
    level: int
    payload_offset: int
    payload_length: int
    encoding: str
    original_page: None


class PdfLocator(FixtureModel):
    original_page: int


class Citation(FixtureModel):
    kind: str
    locator: XmlLocator | RecordLocator | PdfLocator
    expected_text: str
    trailing_control: str = ""


class TruthDocument(FixtureModel):
    id: str
    path: str
    sha256: str
    family_id: str
    page_count: int | None
    cases: tuple[Citation, ...]
    ordered_section_members: tuple[str, ...] = ()
    version: str | None = None
    flags: int | None = None


class Truth(FixtureModel):
    schema_version: int
    purpose: str
    human_review_completed: bool
    independent_evaluation: bool
    namespaces: dict[str, str]
    documents: tuple[TruthDocument, ...]
