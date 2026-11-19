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
EMF_TYPES: Final = frozenset({"image/x-emf", "image/emf"})
WMF_TYPES: Final = frozenset({"image/x-wmf", "image/wmf"})
IMAGE_TYPES: Final = frozenset(RASTER_SIGNATURES) | EMF_TYPES | WMF_TYPES
SIGNATURE_BYTES: Final = 44  # enough for the EMF header signature at offset 40
WMF_PLACEABLE: Final = b"\xd7\xcd\xc6\x9a"


def _is_emf(prefix: bytes) -> bool:
    return prefix[:4] == b"\x01\x00\x00\x00" and prefix[40:44] == b" EMF"


def _is_wmf(prefix: bytes) -> bool:
    """Placeable header, or a standard header: type 1 (memory) or 2 (disk), header size 9 words."""
    return prefix.startswith(WMF_PLACEABLE) or (
        prefix[:2] in (b"\x01\x00", b"\x02\x00") and prefix[2:4] == b"\x09\x00"
    )


def inspect_raster_signature(prefix: bytes, content_type: str) -> None:
    """Require the declared raster MIME type's signature, not an extension guess."""
    signatures = RASTER_SIGNATURES.get(content_type)
    if content_type in EMF_TYPES:
        is_valid = _is_emf(prefix)
    elif content_type in WMF_TYPES:
        is_valid = _is_wmf(prefix)
    else:
        is_valid = signatures is not None and prefix.startswith(signatures)
    if not is_valid:
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
