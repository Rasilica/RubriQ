import json
from pathlib import Path

import pytest
from conversion_helpers import fake_renderer, pdf_bytes, source_docx

from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.docx_conversion import convert_docx
from submission.evidence_contracts import EvidenceLimits
from submission.extraction import extract_pdf
from submission.formats import inspect_document
from submission.input_contracts import (
    DocumentInput,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)
from submission.models import MAX_DOCUMENT_PAGES, DocumentRole, PdfInput, PdfLimits, UploadError
from submission.pair_contracts import PairRuntime

RUNTIME = Path(__file__).parents[1] / ".runtime" / "batch" / "pair-runtime.json"


def test_shared_limit_is_one_hundred_pages() -> None:
    assert MAX_DOCUMENT_PAGES == 100
    assert InputLimits().max_pdf_pages == 100
    assert PdfLimits().max_pages == 100
    assert EvidenceLimits().max_pages == 100
    assert ConversionConfig(soffice=Path("x"), work_root=Path("y")).max_output_pages == 100


@pytest.mark.parametrize("pages", [51, 100])
def test_upload_accepts_up_to_limit(pages: int) -> None:
    content = pdf_bytes(pages)

    details = inspect_document(DocumentInput("r.pdf", content, DocumentRole.REPORT))

    assert details.source.detected_format == "pdf"


def test_upload_rejects_over_limit() -> None:
    with pytest.raises(InputValidationError) as caught:
        inspect_document(DocumentInput("r.pdf", pdf_bytes(101), DocumentRole.REPORT))
    assert caught.value.code is InputErrorCode.TOO_MANY_PAGES


def test_extraction_limit_boundary() -> None:
    extract_pdf(PdfInput("r.pdf", pdf_bytes(100), DocumentRole.REPORT))
    with pytest.raises(UploadError, match="too_many_pages"):
        extract_pdf(PdfInput("r.pdf", pdf_bytes(101), DocumentRole.REPORT))


@pytest.mark.parametrize(("pages", "accepted"), [(100, True), (101, False)])
def test_converted_output_limit_boundary(tmp_path: Path, pages: int, *, accepted: bool) -> None:
    config = ConversionConfig(
        soffice=fake_renderer(tmp_path, pdf_bytes(pages)), work_root=tmp_path / "jobs"
    )

    if accepted:
        assert convert_docx(source_docx(), config).preview_page_count == 100
        return
    with pytest.raises(ConversionError) as caught:
        convert_docx(source_docx(), config)
    assert caught.value.code == ConversionErrorCode.OUTPUT_LIMIT


@pytest.mark.skipif(not RUNTIME.exists(), reason="local runtime config not present")
def test_runtime_json_uses_shared_limit() -> None:
    runtime = PairRuntime.model_validate_json(RUNTIME.read_text())
    values = [v for k, v in _walk(json.loads(RUNTIME.read_text())) if "pages" in k]

    assert runtime is not None
    assert values
    assert set(values) == {MAX_DOCUMENT_PAGES}


def _walk(node: object, key: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, k)
    elif isinstance(node, int):
        yield key, node
