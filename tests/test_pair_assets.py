import base64
import os
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest

from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.pair_assets import RASTER_LOCK, evidence, read_png, render_page, validated_pdf
from submission.pair_contracts import EvidenceSelection, PairError, PairRuntime
from submission.pair_prepare import prepare_role

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWZsAAAAASUVORK5CYII="
)


def raster_binary(directory: Path, mode: str = "good") -> Path:
    binary = directory / "pdftoppm"
    _ = binary.write_text(
        "\n".join(
            (
                f"#!{sys.executable}",
                "import pathlib,sys,base64",
                f"mode={mode!r}",
                "if mode == 'fail': sys.exit(2)",
                "output=pathlib.Path(sys.argv[-1]+'.png')",
                f"output.write_bytes(base64.b64decode({base64.b64encode(PNG).decode()!r}))",
                "",
            )
        )
    )
    binary.chmod(0o700)
    return binary


def test_raster_bounds_failures_and_retry(tmp_path: Path, text_pdf: bytes) -> None:
    role = prepare_role(
        DocumentInput("test.pdf", text_pdf, DocumentRole.GUIDE), PairRuntime(), monotonic() + 10
    )
    assert render_page(role, 1, raster_binary(tmp_path)) == PNG
    for page, binary in ((0, None), (3, None), (1, None), (1, Path("relative"))):
        with pytest.raises(PairError):
            _ = render_page(role, page, binary)
    with RASTER_LOCK, pytest.raises(PairError, match="preparation_busy"):
        _ = render_page(role, 1, tmp_path / "pdftoppm")
    with pytest.raises(PairError, match="asset_unavailable"):
        _ = render_page(role, 1, raster_binary(tmp_path, "fail"))
    assert render_page(role, 2, raster_binary(tmp_path)) == PNG
    with pytest.raises(PairError):
        _ = validated_pdf(replace(role, pdf=b"modified"))
    with pytest.raises(PairError):
        _ = validated_pdf(replace(role, pdf=None))


@pytest.mark.parametrize(
    "content", [b"bad", PNG[:16] + b"\x00\x00\x10\x00" + PNG[20:], b"x" * (8 * 1024 * 1024 + 1)]
)
def test_png_invalid_or_oversized(tmp_path: Path, content: bytes) -> None:
    file = tmp_path / "page.png"
    _ = file.write_bytes(content)
    with pytest.raises(PairError):
        _ = read_png(file)


def test_png_symlink_and_fifo_refused(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _ = target.write_bytes(PNG)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(target)
    with pytest.raises(OSError, match="Too many levels"):
        _ = read_png(symlink)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(PairError):
        _ = read_png(fifo)


def test_invalid_selections(text_pdf: bytes) -> None:
    role = prepare_role(
        DocumentInput("test.pdf", text_pdf, DocumentRole.GUIDE), PairRuntime(), monotonic() + 10
    )
    assert role.view.document is not None
    block = role.view.document.blocks[0]
    for selection in (
        EvidenceSelection(block_id="missing", start=0, end=1),
        EvidenceSelection(block_id=block.block_id, start=1, end=1),
        EvidenceSelection(block_id=block.block_id, start=0, end=10000),
    ):
        with pytest.raises(PairError):
            _ = evidence(role, selection)
