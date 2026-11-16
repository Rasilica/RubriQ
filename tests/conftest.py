from io import BytesIO

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas


@pytest.fixture
def text_pdf() -> bytes:
    # Given: a two-page document with meaningful text on each page.
    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(72, 720, "Purpose: help students check requirements.")
    canvas.showPage()
    canvas.drawString(72, 720, "Input: guide and report. Output: cited findings.")
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


@pytest.fixture
def blank_pdf() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    return buffer.getvalue()
