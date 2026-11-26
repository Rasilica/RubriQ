"""Windows 경로를 macOS에서 흉내 내 확인한다. 실기기 검증을 대신하지 않는다."""

import importlib
import os
import sys
from pathlib import Path
from time import monotonic

import pytest

from submission import conversion_process, file_flags, library_schema, pair_assets
from submission.conversion_contracts import ConversionError, ConversionErrorCode

SAMPLES = Path(__file__).resolve().parents[1] / "samples/pdf"


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def test_read_flags_work_without_posix_constants(monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW")
    monkeypatch.delattr(os, "O_NONBLOCK")
    monkeypatch.setattr(os, "O_BINARY", 0x8000, raising=False)
    try:
        assert importlib.reload(file_flags).READ_FLAGS == os.O_RDONLY | 0x8000
    finally:
        monkeypatch.undo()
        importlib.reload(file_flags)


@pytest.mark.usefixtures("windows")
def test_library_opens_without_getuid_on_windows(monkeypatch, tmp_path):
    monkeypatch.delattr(os, "getuid")
    tmp_path.chmod(0o755)

    with library_schema.database(tmp_path.resolve() / "documents.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM snapshots").fetchone() == (0,)


def python(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


@pytest.mark.usefixtures("windows")
def test_windows_process_returns_stdout(tmp_path):
    output = conversion_process.run_process(
        python("print('ok', end='')"), tmp_path, monotonic() + 10, 1.0
    )

    assert output == b"ok"


@pytest.mark.usefixtures("windows")
@pytest.mark.parametrize(
    ("code", "seconds", "expected"),
    [
        ("raise SystemExit(3)", 10, ConversionErrorCode.RENDERER_FAILED),
        ("import time; time.sleep(30)", 0.5, ConversionErrorCode.TIMEOUT),
        ("print('x' * 200000)", 10, ConversionErrorCode.PROCESS_OUTPUT_LIMIT),
    ],
)
def test_windows_process_reports_failures(tmp_path, code, seconds, expected):
    with pytest.raises(ConversionError) as raised:
        conversion_process.run_process(python(code), tmp_path, monotonic() + seconds, 1.0)

    assert raised.value.code == expected


@pytest.mark.usefixtures("windows")
def test_windows_process_reports_missing_program(tmp_path):
    with pytest.raises(ConversionError) as raised:
        conversion_process.run_process(
            (str(tmp_path / "missing.exe"),), tmp_path, monotonic() + 5, 1.0
        )

    assert raised.value.code == ConversionErrorCode.RENDERER_UNAVAILABLE


@pytest.mark.usefixtures("windows")
def test_windows_renders_page_without_poppler():
    image = pair_assets.render_pdf_page((SAMPLES / "guide.pdf").read_bytes(), 1, None)

    assert image.startswith(b"\x89PNG")
