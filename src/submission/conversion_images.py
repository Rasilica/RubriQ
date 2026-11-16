"""Identify allowed raster formats without claiming full image decoding or validity."""

from typing import Final

from submission.conversion_contracts import ConversionError, ConversionErrorCode

RASTER_SIGNATURES: Final = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/bmp": (b"BM",),
    "image/tiff": (b"II\x2a\x00", b"MM\x00\x2a"),
}
IMAGE_TYPES: Final = frozenset(RASTER_SIGNATURES)


def inspect_raster_signature(prefix: bytes, content_type: str) -> None:
    """Require the declared raster MIME type's signature, not an extension guess."""
    signatures = RASTER_SIGNATURES.get(content_type)
    if signatures is None or not prefix.startswith(signatures):
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
