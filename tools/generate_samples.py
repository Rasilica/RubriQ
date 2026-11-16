# Copyright 2026 제출 전 contributors
# /// script
# requires-python = ">=3.12"
# dependencies = ["reportlab>=4.4,<5", "pydantic>=2.11,<3"]
# ///
# ─── How to run ───
# From API: uv run tools/generate_samples.py
# With the project environment: uv run python tools/generate_samples.py
"""Render authored source pages; never generate or infer truth labels."""

import logging
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

SAMPLES: Final = Path(__file__).resolve().parents[1] / "samples"
FONT: Final = "HYSMyeongJo-Medium"
MARGIN: Final = 46.0
FONT_SIZE: Final = 11
LINE_HEIGHT: Final = 19
CONTENT_BOTTOM: Final = 80
LOGGER: Final = logging.getLogger(__name__)


class Page(BaseModel):
    """One explicitly authored PDF page."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    number: int = Field(ge=1)
    heading: str = Field(min_length=1)
    paragraphs: tuple[str, ...]


class Document(BaseModel):
    """A document has a stable ID and an explicit page sequence."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[a-z]+$")
    title: str
    pdf: str = Field(pattern=r"^pdf/[a-z]+\.pdf$")
    pages: tuple[Page, ...] = Field(min_length=2, max_length=2)


class Sources(BaseModel):
    """Parse the checked-in source boundary before rendering."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int
    family_id: str
    usage: str
    documents: tuple[Document, ...]


class LayoutError(RuntimeError):
    """Fail visibly if authored content would escape its fixed page."""

    def __init__(self, document_id: str, page_number: int) -> None:
        """Identify the authored page needing correction."""
        super().__init__(f"Content exceeds fixed layout: {document_id}:{page_number}")


def render_document(document: Document) -> None:
    """Write two fixed pages, rejecting overflow instead of silently clipping."""
    width, height = A4
    output = SAMPLES / document.pdf
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        canvas = Canvas(stream, pagesize=A4, invariant=1)
        canvas.setTitle(document.title)
        canvas.setAuthor("제출 전 개발용 합성 자료")
        for expected_number, page in enumerate(document.pages, start=1):
            if page.number != expected_number:
                raise LayoutError(document.id, page.number)
            canvas.setFont(FONT, 16)
            canvas.drawString(MARGIN, height - 65, page.heading)
            canvas.setFont(FONT, FONT_SIZE)
            y = height - 110
            for paragraph in page.paragraphs:
                if pdfmetrics.stringWidth(paragraph, FONT, FONT_SIZE) > width - 2 * MARGIN:
                    raise LayoutError(document.id, page.number)
                if y < CONTENT_BOTTOM:
                    raise LayoutError(document.id, page.number)
                canvas.drawString(MARGIN, y, paragraph)
                y -= LINE_HEIGHT * 1.6
            canvas.setFont(FONT, 9)
            canvas.drawString(MARGIN, 40, "개발용 합성 자료 | 독립 평가용 아님")
            canvas.drawRightString(width - MARGIN, 40, f"PDF {page.number} / 2")
            canvas.showPage()
        canvas.save()


def main() -> None:
    """Render sources without changing their independent authored truth file."""
    sources = Sources.model_validate_json((SAMPLES / "sources.json").read_text(encoding="utf-8"))
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
    for document in sources.documents:
        render_document(document)
        LOGGER.info("Generated %s: %s pages", document.pdf, len(document.pages))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
