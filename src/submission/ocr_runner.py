import hashlib
import struct
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pydantic import ValidationError

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_process import run_process
from submission.ocr_contracts import OcrConfig, OcrError, OcrErrorCode, OcrResult

Runner = Callable[[tuple[str, ...], Path, float, float], bytes]

PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
PNG_DIMENSIONS: Final = slice(16, 24)
STOP_GRACE_SECONDS: Final = 1.0
ENV_BINARY: Final = "/usr/bin/env"
PROCESS_ERRORS: Final = {
    ConversionErrorCode.TIMEOUT: OcrErrorCode.TIMEOUT,
    ConversionErrorCode.RENDERER_UNAVAILABLE: OcrErrorCode.UNAVAILABLE,
}


def verify_binary(config: OcrConfig) -> None:
    try:
        content = config.binary_path.read_bytes()
    except OSError as error:
        raise OcrError(OcrErrorCode.UNAVAILABLE) from error
    if hashlib.sha256(content).hexdigest() != config.sha256:
        raise OcrError(OcrErrorCode.BINARY_MISMATCH)


def check_input(image: bytes, config: OcrConfig) -> None:
    if not image or len(image) > config.max_input_bytes:
        raise OcrError(OcrErrorCode.INPUT_LIMIT)
    # shortcut: only PNG dimensions are checked from the header; other formats rely on byte limit.
    if image.startswith(PNG_SIGNATURE) and len(image) >= PNG_DIMENSIONS.stop:
        sides = struct.unpack(">II", image[PNG_DIMENSIONS])
        if max(sides) > config.max_pixel_side:
            raise OcrError(OcrErrorCode.INPUT_LIMIT)


def read_result(output: Path, config: OcrConfig) -> OcrResult:
    try:
        if output.stat().st_size > config.max_output_bytes:
            raise OcrError(OcrErrorCode.INVALID_OUTPUT)
        content = output.read_bytes()
    except OSError as error:
        raise OcrError(OcrErrorCode.INVALID_OUTPUT) from error
    try:
        return OcrResult.model_validate_json(content, strict=True)
    except ValidationError as error:
        raise OcrError(OcrErrorCode.INVALID_OUTPUT) from error


def run_ocr(
    image_bytes: bytes,
    config: OcrConfig,
    *,
    deadline: float,
    runner: Runner = run_process,
) -> OcrResult:
    """Run the pinned Vision helper in a private directory with an empty environment."""
    check_input(image_bytes, config)
    verify_binary(config)
    limit = min(deadline, time.monotonic() + config.timeout_seconds)
    if limit <= time.monotonic():
        raise OcrError(OcrErrorCode.TIMEOUT)
    with TemporaryDirectory(prefix="ocr-") as name:
        directory = Path(name)
        source, output = directory / "input.img", directory / "output.json"
        _ = source.write_bytes(image_bytes)
        arguments = (ENV_BINARY, "-i", str(config.binary_path.resolve()), str(source), str(output))
        try:
            _ = runner(arguments, directory, limit, STOP_GRACE_SECONDS)
        except ConversionError as error:
            raise OcrError(PROCESS_ERRORS.get(error.code, OcrErrorCode.FAILED)) from error
        return read_result(output, config)
