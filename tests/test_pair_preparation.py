from pathlib import Path
from time import monotonic

import pytest
from conversion_helpers import fake_renderer

from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.document_contracts import CommonDocument, ProcessingStatus
from submission.extraction import extract_pdf
from submission.formats import inspect_document
from submission.hancom_contracts import HancomConversionConfig
from submission.hancom_profile import seal_profile
from submission.hwp_reading import provision_hwp_reader
from submission.hwp_reading_contracts import HwpReadConfig
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole, PdfInput
from submission.pair_contracts import PairError, PairRuntime
from submission.pair_prepare import convert_source, prepare_role, read_source, remaining
from submission.pdf_adapter import adapt_pdf
from tests.test_conversion_opc import FOOTER_TYPE, declared_package
from tests.test_hancom_profile import profile_fixture


def runtime_for(directory: Path, pdf: bytes) -> PairRuntime:
    profile, _, java = profile_fixture(directory)
    renderer = fake_renderer(directory, pdf)
    provision = seal_profile(profile, renderer, java)
    worker = directory / "worker.java"
    _ = worker.write_text("fixture")
    hwp = provision_hwp_reader(java, Path("vendor/hwplib/1.1.11/hwplib-1.1.11.jar"), worker)
    return PairRuntime(
        docx=ConversionConfig(soffice=renderer, work_root=directory / "docx-jobs"),
        hancom=HancomConversionConfig(
            soffice=renderer,
            work_root=directory / "hancom-jobs",
            provision=provision,
        ),
        hwp=HwpReadConfig(provision=hwp, work_root=directory / "hwp-jobs"),
    )


@pytest.mark.parametrize("extension", ["pdf", "docx", "hwpx", "hwp"])
def test_dispatch_preserves_sources_and_real_conversion_boundary(
    tmp_path: Path,
    text_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
    extension: str,
) -> None:
    runtime = runtime_for(tmp_path, text_pdf)
    paths = {
        "docx": "samples/formats/boundary.docx",
        "hwpx": "samples/formats/spine-order.hwpx",
        "hwp": "samples/formats/minimal-5.1.1.0.hwp",
    }
    content = text_pdf if extension == "pdf" else Path(paths[extension]).read_bytes()
    source = DocumentInput(f"sample.{extension}", content, DocumentRole.GUIDE)
    pdf_source = PdfInput("source.pdf", text_pdf, DocumentRole.GUIDE)
    fake_document = adapt_pdf(pdf_source, extract_pdf(pdf_source))

    def hwp_fixture(_source: DocumentInput, _config: HwpReadConfig) -> CommonDocument:
        return fake_document.model_copy(
            update={
                "source": inspect_document(_source).source,
                "artifacts": (),
            }
        )

    monkeypatch.setattr("submission.pair_prepare.read_hwp", hwp_fixture)
    result = prepare_role(source, runtime, monotonic() + 30)
    assert result.view.document is not None
    assert result.original == content
    assert result.view.document.source.detected_format == extension
    assert result.view.rendering_status == ProcessingStatus.COMPLETE
    assert result.pdf == text_pdf
    assert str(tmp_path) not in result.view.model_dump_json()


def test_unconfigured_converters_preserve_read_structure() -> None:
    source = DocumentInput(
        "sample.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )
    prepared = prepare_role(source, PairRuntime(), monotonic() + 10)
    assert prepared.view.document is not None
    assert prepared.view.document.blocks
    assert prepared.view.rendering_status == ProcessingStatus.FAILED
    assert prepared.view.error_code == "asset_unavailable"
    assert prepared.pdf is None
    assert prepared.original == source.content


def test_malformed_declared_xml_preserves_report_structure_and_guide(
    tmp_path: Path,
    text_pdf: bytes,
) -> None:
    renderer = fake_renderer(tmp_path, text_pdf)
    runtime = PairRuntime(docx=ConversionConfig(soffice=renderer, work_root=tmp_path / "docx-jobs"))
    guide = prepare_role(
        DocumentInput("guide.pdf", text_pdf, DocumentRole.GUIDE), runtime, monotonic() + 30
    )
    content = declared_package("word/other.bin", FOOTER_TYPE, b"<broken")
    report = prepare_role(
        DocumentInput("report.docx", content, DocumentRole.REPORT), runtime, monotonic() + 30
    )

    assert guide.view.rendering_status == ProcessingStatus.COMPLETE
    assert guide.pdf == text_pdf
    assert report.view.error_code == "unsupported_active_content"
    assert report.view.rendering_status == ProcessingStatus.FAILED
    assert report.view.document is not None
    assert report.view.document.blocks
    assert report.original == content
    assert report.pdf is None


def test_hwp_without_reader_and_deadlines() -> None:
    source = DocumentInput(
        "a.hwp", Path("samples/formats/minimal-5.1.1.0.hwp").read_bytes(), DocumentRole.GUIDE
    )
    assert prepare_role(source, PairRuntime(), monotonic() + 10).view.document is None
    with pytest.raises(PairError, match="preparation_timeout"):
        _ = remaining(monotonic() - 1, 30)
    with pytest.raises(PairError, match="asset_unavailable"):
        _ = convert_source(source, PairRuntime(), monotonic() + 10)


def test_conversion_timeout_preserves_structure_and_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = DocumentInput(
        "a.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )

    def fail(_source: DocumentInput, _runtime: PairRuntime, _deadline: float) -> None:
        raise ConversionError(ConversionErrorCode.TIMEOUT)

    monkeypatch.setattr("submission.pair_prepare.convert_source", fail)
    result = prepare_role(source, PairRuntime(), monotonic() + 10)
    assert result.view.error_code == "conversion_timeout"
    assert result.view.document is not None
    assert read_source(source, PairRuntime(), monotonic() + 10).blocks
