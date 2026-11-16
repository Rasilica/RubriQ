from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from conversion_helpers import fake_renderer, pdf_bytes, source_docx

from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.docx_conversion import conversion_slot, convert_docx
from submission.input_contracts import DocumentInput


@pytest.mark.parametrize(
    ("mode", "content", "code"),
    [
        ("failure", b"", ConversionErrorCode.RENDERER_FAILED),
        ("missing", b"", ConversionErrorCode.OUTPUT_MISSING),
        ("success", b"invalid", ConversionErrorCode.OUTPUT_INVALID),
        ("success", pdf_bytes(0), ConversionErrorCode.OUTPUT_INVALID),
        ("success", pdf_bytes(encrypted=True), ConversionErrorCode.OUTPUT_INVALID),
        ("timeout", b"", ConversionErrorCode.TIMEOUT),
    ],
)
def test_failed_render_cleans_job(tmp_path: Path, mode: str, content: bytes, code) -> None:
    config = ConversionConfig(
        soffice=fake_renderer(tmp_path, content, mode),
        work_root=tmp_path / "jobs",
        timeout_seconds=0.5 if mode == "timeout" else 5.0,
        terminate_grace_seconds=0.1,
    )

    with pytest.raises(ConversionError) as caught:
        convert_docx(source_docx(), config)

    assert caught.value.code == code
    assert not tuple(config.work_root.iterdir())


@pytest.mark.parametrize("bytes_limit", [True, False])
def test_output_limits_reject_before_result(tmp_path: Path, *, bytes_limit: bool) -> None:
    config = ConversionConfig(
        soffice=fake_renderer(tmp_path, pdf_bytes(2)),
        work_root=tmp_path / "jobs",
        max_output_bytes=10 if bytes_limit else 10000,
        max_output_pages=1,
    )

    with pytest.raises(ConversionError) as caught:
        convert_docx(source_docx(), config)

    assert caught.value.code == ConversionErrorCode.OUTPUT_LIMIT


def test_busy_job_fails_without_creating_work_directory(tmp_path: Path) -> None:
    config = ConversionConfig(soffice=tmp_path / "none", work_root=tmp_path / "jobs")

    with conversion_slot(), pytest.raises(ConversionError) as caught:
        convert_docx(source_docx(), config)

    assert caught.value.code == ConversionErrorCode.BUSY
    assert not config.work_root.exists()


@pytest.mark.parametrize(
    "active_xml",
    [
        '<w:fldSimple w:instr="DATE"/>',
        "<w:instrText>PAGE</w:instrText>",
        "<w:object/>",
        "<w:altChunk/>",
    ],
)
def test_active_content_is_rejected_before_renderer(tmp_path: Path, active_xml: str) -> None:
    original = source_docx()
    output = BytesIO()
    with ZipFile(BytesIO(original.content)) as archive, ZipFile(output, "w") as replacement:
        for member in archive.infolist():
            data = archive.read(member)
            if member.filename == "word/document.xml":
                data = data.replace(b"</w:body>", active_xml.encode() + b"</w:body>")
            replacement.writestr(member, data)
    source = DocumentInput(original.filename, output.getvalue(), original.role)
    config = ConversionConfig(soffice=tmp_path / "none", work_root=tmp_path / "jobs")

    with pytest.raises(ConversionError) as caught:
        convert_docx(source, config)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT
    assert not config.work_root.exists()
