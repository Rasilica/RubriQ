import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.docx_conversion import convert_docx
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole


def test_missing_renderer_is_safe_and_cleans_job(tmp_path: Path) -> None:
    source = DocumentInput(
        "boundary.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )
    config = ConversionConfig(soffice=tmp_path / "missing", work_root=tmp_path / "jobs")

    with pytest.raises(ConversionError) as caught:
        convert_docx(source, config)

    assert caught.value.code == ConversionErrorCode.RENDERER_UNAVAILABLE
    assert not tuple(config.work_root.iterdir())


def test_real_conversion_binds_preview_to_source(tmp_path: Path) -> None:
    executable = shutil.which("soffice")
    if executable is None:
        pytest.skip("LibreOffice is unavailable")
    source = DocumentInput(
        "boundary.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )
    config = ConversionConfig(soffice=Path(executable), work_root=tmp_path / "jobs")

    result = convert_docx(source, config)

    assert result.preview_page_count > 0
    assert result.source.content_sha256 == sha256(source.content).hexdigest()
    assert result.artifact.artifact_sha256 == sha256(result.pdf_bytes).hexdigest()
    assert result.artifact.parent_source_id == result.source.source_id
    assert result.artifact.kind == "preview_pdf"
    assert result.artifact.storage_location is None
    assert (
        result.artifact.font_manifest_hash
        == sha256(result.font_manifest.model_dump_json().encode()).hexdigest()
    )
    assert not tuple(config.work_root.iterdir())
