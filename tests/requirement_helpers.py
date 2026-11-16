import json
from pathlib import Path
from typing import TypedDict

from submission.document_contracts import CommonDocument
from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput
from submission.pdf_adapter import adapt_pdf

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class RangePayload(TypedDict):
    start: int
    end: int


class CitationPayload(TypedDict):
    block_id: str
    char_range: RangePayload
    quote: str


class ConditionPayload(TypedDict):
    description: str
    citations: list[CitationPayload]


class SubconditionPayload(ConditionPayload):
    subcondition_id: str


class RequirementPayload(TypedDict):
    requirement_id: str
    title: str
    classification: str
    condition: ConditionPayload | None
    citations: list[CitationPayload]
    subconditions: list[SubconditionPayload]


class ResponsePayload(TypedDict):
    schema_version: str
    source_id: str
    document_version_id: str
    source_sha256: str
    requirements: list[RequirementPayload]


def guide_document() -> CommonDocument:
    path = SAMPLES / "pdf/guide.pdf"
    source = PdfInput(path.name, path.read_bytes(), DocumentRole.GUIDE)
    return adapt_pdf(source, extract_pdf(source))


def response_payload() -> ResponsePayload:
    return json.loads((SAMPLES / "requirements/guide-offline-response.json").read_text())


def single_response(document: CommonDocument, text: str) -> str:
    block = next(block for block in document.blocks if text in block.raw_text)
    start = block.raw_text.index(text)
    return json.dumps(
        {
            "schema_version": "1",
            "source_id": document.source.source_id,
            "document_version_id": document.source.document_version_id,
            "source_sha256": document.source.content_sha256,
            "requirements": [
                {
                    "requirement_id": "R1",
                    "title": "구조 출처 시험",
                    "classification": "required",
                    "condition": None,
                    "subconditions": [],
                    "citations": [
                        {
                            "block_id": block.block_id,
                            "quote": text,
                            "char_range": {"start": start, "end": start + len(text)},
                        }
                    ],
                }
            ],
        }
    )
