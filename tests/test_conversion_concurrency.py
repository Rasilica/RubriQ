from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import Event

import pytest
from conversion_helpers import fake_renderer, source_docx

from submission import docx_conversion
from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.conversion_fonts import collect_fonts
from submission.docx_conversion import convert_docx


def test_contending_thread_is_busy_then_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = Event()
    release = Event()
    original = docx_conversion.render_job

    def hold_job(source, identity, config, directory, deadline):
        entered.set()
        assert release.wait(5)
        return original(source, identity, config, directory, deadline)

    monkeypatch.setattr(docx_conversion, "render_job", hold_job)
    monkeypatch.setattr(docx_conversion, "collect_fonts", partial(collect_fonts, roots=()))
    config = ConversionConfig(soffice=fake_renderer(tmp_path), work_root=tmp_path / "jobs")

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(convert_docx, source_docx(), config)
        try:
            assert entered.wait(5)
            second = workers.submit(convert_docx, source_docx(), config)
            with pytest.raises(ConversionError) as caught:
                _ = second.result(timeout=5)
            assert caught.value.code == ConversionErrorCode.BUSY
        finally:
            release.set()
        result = first.result(timeout=5)
    retried = convert_docx(source_docx(), config)

    assert result.pdf_bytes == retried.pdf_bytes
    assert not tuple(config.work_root.iterdir())
