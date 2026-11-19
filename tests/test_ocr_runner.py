import hashlib
import json
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.ocr_contracts import OcrConfig, OcrError, OcrErrorCode, OcrResult
from submission.ocr_runner import run_ocr

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_header(width: int, height: int) -> bytes:
    return PNG_SIGNATURE + struct.pack(">I4sII", 13, b"IHDR", width, height) + b"\0" * 9


GOOD = {
    "schema_version": 1,
    "width": 10,
    "height": 20,
    "observations": [{"text": "안녕 hello", "confidence": 0.9, "box": [0.1, 0.2, 0.3, 0.4]}],
}


def make_config(tmp_path: Path, **overrides: object) -> OcrConfig:
    binary = tmp_path / "vision-ocr"
    _ = binary.write_bytes(b"fake-binary")
    digest = hashlib.sha256(b"fake-binary").hexdigest()
    return OcrConfig(binary_path=binary, sha256=digest, **overrides)  # pyright: ignore[reportArgumentType]


def writer(payload: object, seen: list[tuple[str, ...]] | None = None):
    def runner(arguments: tuple[str, ...], directory: Path, deadline: float, grace: float) -> bytes:
        _ = (directory, deadline, grace)
        if seen is not None:
            seen.append(arguments)
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        _ = Path(arguments[-1]).write_bytes(data)
        return b""

    return runner


def failing(code: ConversionErrorCode):
    def runner(arguments: tuple[str, ...], directory: Path, deadline: float, grace: float) -> bytes:
        _ = (arguments, directory, deadline, grace)
        raise ConversionError(code)

    return runner


def call(tmp_path: Path, runner, image: bytes = b"png", **overrides: object) -> OcrResult:
    return run_ocr(
        image, make_config(tmp_path, **overrides), deadline=time.monotonic() + 30, runner=runner
    )


def code_of(tmp_path: Path, runner, image: bytes = b"png", **overrides: object) -> OcrErrorCode:
    with pytest.raises(OcrError) as caught:
        _ = call(tmp_path, runner, image, **overrides)
    return caught.value.code


def test_parses_valid_output(tmp_path: Path) -> None:
    result = call(tmp_path, writer(GOOD))
    assert result.width == 10
    assert result.observations[0].text == "안녕 hello"
    assert result.observations[0].box == (0.1, 0.2, 0.3, 0.4)


def test_runs_with_cleared_environment_and_private_directory(tmp_path: Path) -> None:
    seen: list[tuple[str, ...]] = []
    _ = call(tmp_path, writer(GOOD, seen))
    assert seen[0][:2] == ("/usr/bin/env", "-i")
    assert seen[0][2] == str((tmp_path / "vision-ocr").resolve())


def test_cleans_temp_files(tmp_path: Path) -> None:
    seen: list[tuple[str, ...]] = []
    _ = call(tmp_path, writer(GOOD, seen))
    assert not Path(seen[0][-1]).parent.exists()
    seen.clear()
    _ = code_of(tmp_path, writer(b"{", seen))
    assert not Path(seen[0][-1]).parent.exists()


def test_rejects_binary_mismatch_before_running(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    _ = config.binary_path.write_bytes(b"tampered")
    seen: list[tuple[str, ...]] = []
    with pytest.raises(OcrError) as caught:
        _ = run_ocr(b"png", config, deadline=time.monotonic() + 30, runner=writer(GOOD, seen))
    assert caught.value.code is OcrErrorCode.BINARY_MISMATCH
    assert not seen


def test_missing_binary_is_unavailable(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.binary_path.unlink()
    with pytest.raises(OcrError) as caught:
        _ = run_ocr(b"png", config, deadline=time.monotonic() + 30, runner=writer(GOOD))
    assert caught.value.code is OcrErrorCode.UNAVAILABLE


@pytest.mark.parametrize(
    ("conversion", "expected"),
    [
        (ConversionErrorCode.TIMEOUT, OcrErrorCode.TIMEOUT),
        (ConversionErrorCode.RENDERER_UNAVAILABLE, OcrErrorCode.UNAVAILABLE),
        (ConversionErrorCode.RENDERER_FAILED, OcrErrorCode.FAILED),
        (ConversionErrorCode.CLEANUP_FAILED, OcrErrorCode.FAILED),
    ],
)
def test_maps_process_errors(
    tmp_path: Path, conversion: ConversionErrorCode, expected: OcrErrorCode
) -> None:
    assert code_of(tmp_path, failing(conversion)) is expected


def test_expired_deadline_times_out_without_running(tmp_path: Path) -> None:
    with pytest.raises(OcrError) as caught:
        _ = run_ocr(
            b"png", make_config(tmp_path), deadline=time.monotonic() - 1, runner=writer(GOOD)
        )
    assert caught.value.code is OcrErrorCode.TIMEOUT


def test_timeout_is_capped_by_config(tmp_path: Path) -> None:
    deadlines: list[float] = []

    def runner(arguments: tuple[str, ...], directory: Path, deadline: float, grace: float) -> bytes:
        deadlines.append(deadline)
        return writer(GOOD)(arguments, directory, deadline, grace)

    _ = run_ocr(
        b"png",
        make_config(tmp_path, timeout_seconds=5),
        deadline=time.monotonic() + 500,
        runner=runner,
    )
    assert deadlines[0] - time.monotonic() <= 5


def test_rejects_oversize_input(tmp_path: Path) -> None:
    assert (
        code_of(tmp_path, writer(GOOD), b"x" * 11, max_input_bytes=10) is OcrErrorCode.INPUT_LIMIT
    )


def test_rejects_empty_input(tmp_path: Path) -> None:
    assert code_of(tmp_path, writer(GOOD), b"") is OcrErrorCode.INPUT_LIMIT


def test_rejects_png_side_over_limit(tmp_path: Path) -> None:
    code = code_of(tmp_path, writer(GOOD), png_header(5000, 10))
    assert code is OcrErrorCode.INPUT_LIMIT
    assert call(tmp_path, writer(GOOD), png_header(4096, 10)).width == 10


def test_rejects_oversize_output(tmp_path: Path) -> None:
    assert code_of(tmp_path, writer(GOOD), max_output_bytes=20) is OcrErrorCode.INVALID_OUTPUT


def test_missing_output_is_invalid(tmp_path: Path) -> None:
    def runner(arguments: tuple[str, ...], directory: Path, deadline: float, grace: float) -> bytes:
        _ = (arguments, directory, deadline, grace)
        return b""

    assert code_of(tmp_path, runner) is OcrErrorCode.INVALID_OUTPUT


def with_observation(**changes: object) -> dict[str, object]:
    observation = {**GOOD["observations"][0], **changes}  # pyright: ignore[reportIndexIssue,reportGeneralTypeIssues]
    return {**GOOD, "observations": [observation]}


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"[]",
        {**GOOD, "schema_version": 2},
        {**GOOD, "extra": 1},
        {**GOOD, "width": 0},
        with_observation(text=""),
        with_observation(confidence=1.5),
        with_observation(confidence=-0.1),
        with_observation(box=[0.1, 0.2, 1.2, 0.4]),
        with_observation(box=[-0.1, 0.2, 0.3, 0.4]),
        with_observation(box=[0.1, 0.2, 0.3]),
        with_observation(box=[0.1, 0.2, float("nan"), 0.4]),
        {**GOOD, "observations": [GOOD["observations"][0]] * 3001},  # pyright: ignore[reportIndexIssue]
    ],
)
def test_rejects_invalid_output(tmp_path: Path, payload: object) -> None:
    assert code_of(tmp_path, writer(payload)) is OcrErrorCode.INVALID_OUTPUT


def test_error_messages_do_not_leak_paths(tmp_path: Path) -> None:
    with pytest.raises(OcrError) as caught:
        _ = call(tmp_path, writer(b"{"))
    assert str(tmp_path) not in str(caught.value)
    assert str(caught.value) == "ocr_invalid_output"


SWIFT_RENDER = """
import AppKit
let size = NSSize(width: 900, height: 480)
let image = NSImage(size: size)
image.lockFocus()
NSColor.white.setFill(); NSRect(origin: .zero, size: size).fill()
let attributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 72), .foregroundColor: NSColor.black]
let x = CGFloat(Double(CommandLine.arguments[2])!)
for (index, line) in ["Hello 안녕하세요", "Edge 가나다라", "Left 마바사아"].enumerated() {
    let point = NSPoint(x: x, y: CGFloat(20 + 150 * index))
    NSString(string: line).draw(at: point, withAttributes: attributes)
}
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
let png = bitmap.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
"""


def run_checked(arguments: list[str], timeout: int) -> None:
    _ = subprocess.run(arguments, check=True, timeout=timeout)  # noqa: S603


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None, reason="needs macOS and swiftc"
)
@pytest.mark.parametrize("left_margin", ["30", "0"])
def test_vision_helper_recognizes_text_with_boxes_in_range(
    tmp_path: Path, left_margin: str
) -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools"))
    try:
        from build_vision_ocr import build  # noqa: PLC0415
    finally:
        _ = sys.path.pop(0)
    binary = tmp_path / "vision-ocr"
    digest = build(binary)
    renderer_source = tmp_path / "render.swift"
    _ = renderer_source.write_text(SWIFT_RENDER, encoding="utf-8")
    renderer = tmp_path / "render"
    run_checked(["swiftc", str(renderer_source), "-o", str(renderer)], 120)
    png = tmp_path / "in.png"
    run_checked([str(renderer), str(png), left_margin], 60)

    result = run_ocr(
        png.read_bytes(),
        OcrConfig(binary_path=binary, sha256=digest),
        deadline=time.monotonic() + 60,
    )

    text = "".join(item.text for item in result.observations).replace(" ", "")
    assert "Hello" in text
    assert "안녕하세요" in text
    assert all(0 <= value <= 1 for item in result.observations for value in item.box)
