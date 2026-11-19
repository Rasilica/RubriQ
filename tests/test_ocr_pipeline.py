import json
import platform
import shutil
import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from test_pair_preparation import runtime_for

from submission import ocr_pipeline
from submission.document_contracts import (
    CharacterRange,
    CommonDocument,
    ProcessingStatus,
    StructuralCoverage,
)
from submission.evidence_contracts import (
    ArtifactBinding,
    EvidenceMapContext,
    EvidenceMapRequest,
    PdfArtifactInput,
)
from submission.evidence_mapping import map_evidence
from submission.extraction import extract_pdf
from submission.input_contracts import DocumentInput
from submission.library_validation import environment, validate_role
from submission.models import DocumentRole, PdfInput
from submission.ocr_contracts import (
    OcrConfig,
    OcrError,
    OcrErrorCode,
    OcrObservation,
    OcrResult,
)
from submission.ocr_rows import OcrLine
from submission.pair_contracts import PairRuntime
from submission.pair_prepare import prepare_role
from submission.pdf_adapter import adapt_pdf
from submission.report_check_adapter import INSTRUCTIONS as REPORT_INSTRUCTIONS
from submission.requirement_adapter import INSTRUCTIONS as REQUIREMENT_INSTRUCTIONS
from submission.requirement_contracts import CitationInput, VerifiedCitation
from submission.requirement_validation import request_blocks, verify_citation

OCR_CONFIG = OcrConfig(binary_path=Path("/nonexistent/vision-ocr"), sha256="0" * 64)
RUNTIME = PairRuntime(ocr=OCR_CONFIG)
ROW = OcrLine("항목 | 내용 | 비고", ("항목", "내용", "비고"), 0.4, (0.1, 0.1, 0.8, 0.05))
TITLE = OcrLine("동아리 가입 안내", ("동아리 가입 안내",), 0.95, (0.1, 0.02, 0.5, 0.05))


class Pages:
    """Fake OCR runner returning canned lines per page and recording calls."""

    def __init__(self, lines=(TITLE, ROW), error: Exception | None = None) -> None:
        self.lines, self.error, self.calls = lines, error, []

    def __call__(self, _pdf: bytes, page: int, _deadline: float) -> tuple[OcrLine, ...]:
        self.calls.append(page)
        if self.error is not None:
            raise self.error
        return self.lines


def blank_pages(count: int) -> bytes:
    writer, buffer = PdfWriter(), BytesIO()
    for _ in range(count):
        _ = writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    return buffer.getvalue()


def prepare(content: bytes, runtime: PairRuntime, read_page=None, name: str = "scan.pdf"):
    source = DocumentInput(name, content, DocumentRole.GUIDE)
    return prepare_role(source, runtime, monotonic() + 60, read_page=read_page)


def test_ocr_unset_leaves_output_identical_and_never_reads_pages() -> None:
    fake = Pages()
    scanned = blank_pages(2)
    baseline = prepare(scanned, PairRuntime())
    result = prepare(scanned, PairRuntime(), fake)
    assert fake.calls == []
    assert result.view.model_dump_json() == baseline.view.model_dump_json()
    assert result.view.warnings == ()
    assert '"ocr"' not in result.view.model_dump_json()


def test_scanned_pdf_page_becomes_ocr_lines_with_partial_status() -> None:
    fake = Pages()
    result = prepare(blank_pages(1), RUNTIME, fake)
    document = result.view.document
    assert document is not None
    assert fake.calls == [1]
    assert [b.kind for b in document.blocks] == ["ocr_line", "ocr_line"]
    assert [b.raw_text for b in document.blocks] == ["동아리 가입 안내", "항목 | 내용 | 비고"]
    assert document.blocks[1].source_locator.path == "page[1]/ocr[2]"
    assert document.blocks[1].source_locator.original_page_number == 1
    assert document.blocks[1].ocr is not None
    assert document.blocks[1].ocr.confidence == 0.4
    assert [b.reading_order for b in document.blocks] == [0, 1]
    assert document.extraction_status == ProcessingStatus.PARTIAL
    assert result.view.extraction_status == ProcessingStatus.PARTIAL
    assert [w.code for w in document.warnings] == ["ocr_text_used"]
    assert "ocr_text_used" in result.view.warnings
    assert result.available


def test_mixed_pdf_reads_only_the_image_page(text_pdf: bytes) -> None:
    writer, buffer = PdfWriter(), BytesIO()
    _ = writer.add_page(PdfReader(BytesIO(text_pdf)).pages[0])
    _ = writer.add_blank_page(width=595, height=842)
    _ = writer.add_page(PdfReader(BytesIO(text_pdf)).pages[1])
    writer.write(buffer)
    fake = Pages()
    document = prepare(buffer.getvalue(), RUNTIME, fake).view.document
    assert document is not None
    assert fake.calls == [2]
    assert [b.source_locator.original_page_number for b in document.blocks] == [1, 2, 2, 3]
    kinds = [b.kind for b in document.blocks]
    assert kinds == ["extraction_block", "ocr_line", "ocr_line", "extraction_block"]
    assert [b.reading_order for b in document.blocks] == [0, 1, 2, 3]


def test_text_pdf_is_never_read_with_ocr(text_pdf: bytes) -> None:
    fake = Pages()
    result = prepare(text_pdf, RUNTIME, fake)
    assert fake.calls == []
    assert result.view.warnings == ()


def image_only_docx(monkeypatch: pytest.MonkeyPatch, text_pdf: bytes) -> CommonDocument:
    base = adapt_pdf(
        PdfInput("a.pdf", text_pdf, DocumentRole.GUIDE),
        extract_pdf(PdfInput("a.pdf", text_pdf, DocumentRole.GUIDE)),
    )
    figure = base.blocks[0].model_copy(
        update={"kind": "figure", "raw_text": "", "normalized_text": "", "normalization_map": ()}
    )
    document = base.model_copy(
        update={
            "blocks": (
                figure.model_copy(update={"raw_char_range": CharacterRange(start=0, end=0)}),
            ),
            "artifacts": (),
            "mappings": (),
            "source": base.source.model_copy(
                update={"detected_format": "docx", "declared_extension": ".docx"}
            ),
            "coverage": StructuralCoverage(
                scope="docx_ooxml_structure", processed_parts=(), omitted_locators=()
            ),
        }
    )
    monkeypatch.setattr("submission.pair_prepare.read_docx", lambda _source: document)
    return document


def test_image_only_docx_uses_converted_preview_pages(
    tmp_path: Path, text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = image_only_docx(monkeypatch, text_pdf)
    runtime = runtime_for(tmp_path, text_pdf).model_copy(update={"ocr": OCR_CONFIG})
    fake = Pages(lines=(TITLE,))
    content = Path("samples/formats/boundary.docx").read_bytes()
    result = prepare(content, runtime, fake, "guide.docx")
    document = result.view.document
    assert document is not None
    assert fake.calls == [1, 2]
    assert [b.kind for b in document.blocks] == ["figure", "ocr_line", "ocr_line"]
    assert document.extraction_status == ProcessingStatus.PARTIAL
    assert result.view.artifact_kind == "preview_pdf"
    assert "ocr_text_used" in result.view.warnings
    assert all(m.mapping_status == "ocr_page" for m in document.mappings)


def test_docx_with_text_is_not_read_with_ocr(tmp_path: Path, text_pdf: bytes) -> None:
    runtime = runtime_for(tmp_path, text_pdf).model_copy(update={"ocr": OCR_CONFIG})
    fake = Pages()
    content = Path("samples/formats/boundary.docx").read_bytes()
    _ = prepare(content, runtime, fake, "report.docx")
    assert fake.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (OcrError(OcrErrorCode.TIMEOUT), "ocr_timeout"),
        (OcrError(OcrErrorCode.UNAVAILABLE), "ocr_unavailable"),
        (RuntimeError("boom"), "ocr_failed"),
    ],
)
def test_ocr_failure_records_warning_and_keeps_document(error: Exception, code: str) -> None:
    scanned = blank_pages(2)
    baseline = prepare(scanned, PairRuntime())
    result = prepare(scanned, RUNTIME, Pages(error=error))
    assert result.view.warnings == (code,)
    assert result.view.document == baseline.view.document
    assert result.view.extraction_status == baseline.view.extraction_status


def test_page_cap_limits_ocr_pages_and_warns() -> None:
    fake = Pages(lines=(TITLE,))
    result = prepare(blank_pages(ocr_pipeline.MAX_OCR_PAGES + 2), RUNTIME, fake)
    assert fake.calls == list(range(1, ocr_pipeline.MAX_OCR_PAGES + 1))
    assert result.view.warnings == ("ocr_page_limit", "ocr_text_used")


def test_expired_deadline_skips_ocr_with_warning() -> None:
    source = DocumentInput("scan.pdf", blank_pages(1), DocumentRole.GUIDE)
    document = prepare_role(source, PairRuntime(), monotonic() + 60).view.document
    assert document is not None
    fake = Pages()
    outcome = ocr_pipeline.apply_ocr(
        document, source.content, 1, RUNTIME, monotonic() - 1, read_page=fake
    )
    assert outcome.warnings == ("ocr_timeout",)
    assert outcome.document == document
    assert fake.calls == []


def test_default_reader_renders_page_then_runs_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def render(_pdf: bytes, page: int, binary: Path | None, **options: object) -> bytes:
        seen.update(page=page, binary=binary, options=options)
        return b"png"

    def run(image: bytes, config: OcrConfig, *, deadline: float) -> OcrResult:
        seen.update(image=image, config=config, deadline=deadline)
        observation = OcrObservation(text="안녕", confidence=0.9, box=(0.1, 0.1, 0.2, 0.05))
        return OcrResult(schema_version=1, width=10, height=10, observations=(observation,))

    monkeypatch.setattr(ocr_pipeline, "render_pdf_page", render)
    monkeypatch.setattr(ocr_pipeline, "run_ocr", run)
    runtime = PairRuntime(ocr=OCR_CONFIG, pdftoppm=Path("/usr/bin/pdftoppm"))
    lines = ocr_pipeline.recognize_page(b"%PDF", 3, runtime, 123.0)
    assert [line.text for line in lines] == ["안녕"]
    assert seen["page"] == 3
    assert seen["image"] == b"png"
    assert seen["config"] == OCR_CONFIG


COMPUTED = {
    "content_review_available",
    "display_artifact_available",
    "page_count_verification_available",
}


def reload(document: CommonDocument) -> CommonDocument:
    return CommonDocument.model_validate(document.model_dump(mode="json", exclude=COMPUTED))


def scanned_document() -> tuple[CommonDocument, bytes]:
    content = blank_pages(1)
    result = prepare(content, RUNTIME, Pages())
    assert result.view.document is not None
    return result.view.document, content


def test_ocr_blocks_are_sent_with_ocr_kind_and_instructions_explain_it() -> None:
    document, _ = scanned_document()
    payload = [json.loads(b.model_dump_json()) for b in request_blocks(document)]
    assert {item["kind"] for item in payload} == {"ocr"}
    for text in (REQUIREMENT_INSTRUCTIONS, REPORT_INSTRUCTIONS):
        assert "kind가 ocr인 블록은 이미지에서 기계가 읽은 글자" in text
        assert "확인 필요" in text


def test_text_blocks_keep_the_old_payload_shape(text_pdf: bytes) -> None:
    source = PdfInput("a.pdf", text_pdf, DocumentRole.GUIDE)
    document = adapt_pdf(source, extract_pdf(source))
    assert all("kind" not in json.loads(b.model_dump_json()) for b in request_blocks(document))
    assert "ocr" not in document.model_dump_json()
    assert (
        "from_ocr"
        not in verify_citation(
            CitationInput(
                block_id=document.blocks[0].block_id,
                char_range=CharacterRange(start=0, end=4),
                quote=document.blocks[0].raw_text[:4],
            ),
            document.blocks,
        ).model_dump_json()
    )


def test_citation_on_ocr_block_verifies_exactly_and_is_flagged() -> None:
    document, _ = scanned_document()
    block = document.blocks[1]
    citation = CitationInput(
        block_id=block.block_id,
        char_range=CharacterRange(start=0, end=2),
        quote=block.raw_text[:2],
    )
    verified = verify_citation(citation, document.blocks)
    assert verified.from_ocr is True
    assert json.loads(verified.model_dump_json())["from_ocr"] is True
    bad = citation.model_copy(update={"quote": "없는 문구"})
    with pytest.raises(Exception, match="invalid_citation"):
        _ = verify_citation(bad, document.blocks)
    assert VerifiedCitation.model_validate_json(verified.model_dump_json()) == verified


def test_evidence_on_ocr_block_maps_to_page_only_never_as_text_match() -> None:
    document, content = scanned_document()
    block = document.blocks[1]
    target = PdfArtifactInput(
        binding=ArtifactBinding(source=document.source, artifact=document.artifacts[0]),
        pdf=PdfInput("scan.pdf", content, DocumentRole.GUIDE),
    )
    request = EvidenceMapRequest(
        citation=CitationInput(
            block_id=block.block_id,
            char_range=CharacterRange(start=0, end=2),
            quote=block.raw_text[:2],
        )
    )
    mapped = map_evidence(EvidenceMapContext(document=document, target=target), request)
    assert mapped.mapping.mapping_status == "ocr_page"
    assert mapped.mapping.target_page_numbers == (1,)
    assert mapped.mapping.target_text_ranges == ()
    assert mapped.reason_code == "ocr_page_only"
    assert mapped.candidates == ()


def test_documents_without_ocr_round_trip_as_old_archives(text_pdf: bytes) -> None:
    source = PdfInput("a.pdf", text_pdf, DocumentRole.GUIDE)
    document = adapt_pdf(source, extract_pdf(source))
    legacy = document.model_dump(mode="json", exclude=COMPUTED)
    assert all("ocr" not in block for block in legacy["blocks"])
    assert CommonDocument.model_validate(legacy) == document


def test_ocr_document_round_trips_through_json() -> None:
    document, _ = scanned_document()
    assert reload(document) == document


@pytest.mark.skipif(
    platform.system() != "Darwin" or not Path(".runtime/ocr/vision-ocr").exists(),
    reason="needs macOS and the built Vision helper",
)
def test_real_vision_helper_reads_a_synthetic_scanned_page(tmp_path: Path) -> None:
    pdftoppm = shutil.which("pdftoppm") or "/usr/local/bin/pdftoppm"
    if not Path(pdftoppm).exists():
        pytest.skip("pdftoppm unavailable")
    # Rasterize a text page and wrap the pixels in an image-only PDF.
    canvas = Canvas(str(tmp_path / "text.pdf"))
    canvas.setFont("Helvetica", 40)
    canvas.drawString(72, 700, "Scanned guide 2026")
    canvas.save()
    _ = subprocess.run(  # noqa: S603
        [
            pdftoppm,
            "-singlefile",
            "-r",
            "150",
            "-png",
            *map(str, (tmp_path / "text.pdf", tmp_path / "scan")),
        ],
        check=True,
    )
    image_pdf = tmp_path / "scan.pdf"
    page = Canvas(str(image_pdf), pagesize=(595, 842))
    page.drawImage(ImageReader(str(tmp_path / "scan.png")), 0, 0, 595, 842)
    page.save()
    binary = Path(".runtime/ocr/vision-ocr").resolve()
    runtime = PairRuntime(
        pdftoppm=Path(pdftoppm),
        ocr=OcrConfig(binary_path=binary, sha256=sha256(binary.read_bytes()).hexdigest()),
    )
    document = prepare(image_pdf.read_bytes(), runtime).view.document
    assert document is not None
    assert "Scanned" in " ".join(b.raw_text for b in document.blocks if b.kind == "ocr_line")


def test_saved_ocr_role_passes_library_validation_and_environment_label() -> None:
    result = prepare(blank_pages(1), RUNTIME, Pages())
    validate_role(result, DocumentRole.GUIDE)
    assert f"ocr-helper:{'0' * 64}" in environment(RUNTIME)
    assert not any(label.startswith("ocr-helper") for label in environment(PairRuntime()))
