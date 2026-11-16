import os
import stat
import struct
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from typing import Final

from submission.conversion_contracts import ConversionError
from submission.conversion_process import run_process
from submission.document_contracts import BlockId, CharacterRange
from submission.evidence_contracts import (
    ArtifactBinding,
    BoundEvidenceMapping,
    EvidenceLimits,
    EvidenceMapContext,
    EvidenceMapRequest,
    PdfArtifactInput,
)
from submission.evidence_mapping import map_evidence
from submission.models import PdfInput
from submission.pair_contracts import EvidenceSelection, PairError, PairErrorCode, PreparedRole
from submission.requirement_contracts import CitationInput

IMAGE_LIMIT: Final = 8 * 1024 * 1024
MAX_EDGE: Final = 1600
PNG_HEADER_BYTES: Final = 24
RASTER_LOCK: Final = Lock()


def validated_pdf(role: PreparedRole) -> bytes:
    document = role.view.document
    if role.pdf is None or document is None or not document.artifacts:
        raise PairError(PairErrorCode.UNAVAILABLE)
    if sha256(role.pdf).hexdigest() != document.artifacts[0].artifact_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    return role.pdf


def read_png(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > IMAGE_LIMIT:
            raise PairError(PairErrorCode.UNAVAILABLE)
        content = stream.read(IMAGE_LIMIT + 1)
    if (
        len(content) < PNG_HEADER_BYTES
        or len(content) > IMAGE_LIMIT
        or content[:8] != b"\x89PNG\r\n\x1a\n"
    ):
        raise PairError(PairErrorCode.UNAVAILABLE)
    width, height = struct.unpack(">II", content[16:24])
    if not (0 < width <= MAX_EDGE and 0 < height <= MAX_EDGE):
        raise PairError(PairErrorCode.UNAVAILABLE)
    return content


def render_page(role: PreparedRole, page: int, binary: Path | None) -> bytes:
    pdf = validated_pdf(role)
    if page < 1 or page > (role.view.preview_page_count or 0):
        raise PairError(PairErrorCode.NOT_FOUND)
    if binary is None or not binary.is_absolute():
        raise PairError(PairErrorCode.UNAVAILABLE)
    if not RASTER_LOCK.acquire(blocking=False):
        raise PairError(PairErrorCode.BUSY)
    try:
        with TemporaryDirectory(prefix="pair-page-") as temporary:
            directory = Path(temporary)
            source = directory / "source.pdf"
            _ = source.write_bytes(pdf)
            _ = run_process(
                (
                    str(binary),
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-scale-to",
                    str(MAX_EDGE),
                    "-png",
                    str(source),
                    str(directory / "page"),
                ),
                directory,
                monotonic() + 15.0,
                1.0,
            )
            return read_png(directory / "page.png")
    except (OSError, ConversionError):
        raise PairError(PairErrorCode.UNAVAILABLE) from None
    finally:
        RASTER_LOCK.release()


def evidence(role: PreparedRole, selection: EvidenceSelection) -> BoundEvidenceMapping:
    pdf = validated_pdf(role)
    document = role.view.document
    if document is None:
        raise PairError(PairErrorCode.UNAVAILABLE)
    block = next((item for item in document.blocks if item.block_id == selection.block_id), None)
    if block is None or not 0 <= selection.start < selection.end <= len(block.raw_text):
        raise PairError(PairErrorCode.INVALID)
    return map_evidence(
        EvidenceMapContext(
            document=document,
            target=PdfArtifactInput(
                binding=ArtifactBinding(source=document.source, artifact=document.artifacts[0]),
                pdf=PdfInput("preview.pdf", pdf, document.source.role),
            ),
        ),
        EvidenceMapRequest(
            citation=CitationInput(
                block_id=BlockId(selection.block_id),
                char_range=CharacterRange(start=selection.start, end=selection.end),
                quote=block.raw_text[selection.start : selection.end],
            )
        ),
        limits=EvidenceLimits(max_blocks=10_000),
    )
