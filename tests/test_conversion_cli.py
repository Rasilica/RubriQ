import os
import shutil
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import anyio
import pytest
from conversion_helpers import fake_renderer
from pydantic import JsonValue, TypeAdapter
from pypdf import PdfReader

from tools import run_conversion_demo

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "samples/formats/boundary.docx"
JSON = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def process(arguments: tuple[str, ...]) -> ProcessResult:
    with anyio.fail_after(45):
        result = await anyio.run_process(
            [sys.executable, "-m", "tools.run_conversion_demo", *arguments],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            check=False,
        )
    return ProcessResult(result.returncode, result.stdout.decode(), result.stderr.decode())


def invoke(*arguments: str) -> ProcessResult:
    return anyio.run(process, arguments)


def test_cli_converts_docx_with_receipt_when_libreoffice_installed(tmp_path: Path) -> None:
    executable = shutil.which("soffice")
    if executable is None:
        pytest.skip("LibreOffice is unavailable")
    output = tmp_path / "result"

    completed = invoke(str(SOURCE), str(output), executable)

    assert completed.returncode == 0, completed.stderr
    receipt = JSON.validate_json(completed.stdout)
    assert receipt == JSON.validate_json((output / "receipt.json").read_bytes())
    assert receipt["preview_page_count"] == len(
        PdfReader(BytesIO((output / "preview.pdf").read_bytes()), strict=True).pages
    )
    warnings = receipt["warnings"]
    assert isinstance(warnings, list)
    assert "original_layout_unverified" in warnings
    assert (output / "font-manifest.json").is_file()
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / "preview.pdf").stat().st_mode & 0o777 == 0o600


def test_cli_preserves_existing_output_when_directory_already_exists(tmp_path: Path) -> None:
    output = tmp_path / "result"
    output.mkdir()
    sentinel = output / "preview.pdf"
    _ = sentinel.write_bytes(b"previous result")

    completed = invoke(str(SOURCE), str(output))

    assert completed.returncode == 1
    assert JSON.validate_json(completed.stderr)["error"] == "output_exists"
    assert sentinel.read_bytes() == b"previous result"


def test_cli_cleans_output_when_input_is_missing(tmp_path: Path) -> None:
    output = tmp_path / "result"

    completed = invoke(str(tmp_path / "missing.docx"), str(output))

    assert completed.returncode == 1
    assert JSON.validate_json(completed.stderr)["error"] == "input_io_error"
    assert not output.exists()


def test_cli_returns_safe_error_when_executable_is_missing(tmp_path: Path) -> None:
    output = tmp_path / "result"

    completed = invoke(str(SOURCE), str(output), str(tmp_path / "private-missing-tool"))

    assert completed.returncode == 1
    assert JSON.validate_json(completed.stderr)["error"] == "renderer_unavailable"
    assert "private-missing-tool" not in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not output.exists()


def test_cli_rejects_invalid_timeout_when_nonpositive(tmp_path: Path) -> None:
    output = tmp_path / "result"

    completed = invoke(str(SOURCE), str(output), "--timeout", "0")

    assert completed.returncode == 1
    assert JSON.validate_json(completed.stderr)["error"] == "invalid_config"
    assert not output.exists()


def test_cli_shows_usage_when_no_arguments() -> None:
    completed = invoke()

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr


def test_cli_removes_partial_output_when_publication_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "result"
    original_write = run_conversion_demo.write_private

    def interrupt_receipt(path: Path, content: bytes) -> None:
        if path.name == "receipt.json":
            raise KeyboardInterrupt
        original_write(path, content)

    monkeypatch.setattr(run_conversion_demo, "write_private", interrupt_receipt)
    arguments = run_conversion_demo.Arguments(SOURCE, output, fake_renderer(tmp_path), 5.0)

    with pytest.raises(KeyboardInterrupt):
        _ = run_conversion_demo.execute(arguments)

    assert not output.exists()
