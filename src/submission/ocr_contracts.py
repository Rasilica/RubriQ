import math
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, override

from pydantic import AfterValidator, Field

from submission.models import FrozenModel

MAX_OBSERVATIONS = 3000
MAX_TEXT_CHARS = 4000


class OcrErrorCode(StrEnum):
    UNAVAILABLE = "ocr_unavailable"
    BINARY_MISMATCH = "ocr_binary_mismatch"
    TIMEOUT = "ocr_timeout"
    FAILED = "ocr_failed"
    INVALID_OUTPUT = "ocr_invalid_output"
    INPUT_LIMIT = "ocr_input_limit"


class OcrError(Exception):
    code: OcrErrorCode

    def __init__(self, code: OcrErrorCode) -> None:
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code.value


class OcrConfig(FrozenModel):
    binary_path: Path
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30
    max_input_bytes: Annotated[int, Field(gt=0)] = 20 * 1024 * 1024
    max_pixel_side: Annotated[int, Field(gt=0)] = 4096
    max_output_bytes: Annotated[int, Field(gt=0)] = 4 * 1024 * 1024


def _unit_interval(value: float) -> float:
    if not math.isfinite(value) or not 0 <= value <= 1:
        message = "out of range"
        raise ValueError(message)
    return value


Unit = Annotated[float, AfterValidator(_unit_interval)]


class OcrObservation(FrozenModel):
    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]
    confidence: Unit
    # Normalized x, y, width, height with the origin at the top left.
    box: tuple[Unit, Unit, Unit, Unit]


class OcrResult(FrozenModel):
    schema_version: Literal[1]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    observations: Annotated[tuple[OcrObservation, ...], Field(max_length=MAX_OBSERVATIONS)]
