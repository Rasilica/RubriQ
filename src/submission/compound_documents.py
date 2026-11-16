import zlib
from io import BytesIO
from struct import error as StructError  # noqa: N812
from struct import unpack_from
from typing import Final

from olefile import DEFECT_INCORRECT, OleFileIO

from submission.input_contracts import (
    FormatDetails,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)

HWP_HEADER_SIZE: Final = 256
HWP_TRAILER_SIZE: Final = 8


def validate_hwp_trailer(trailer: bytes, expanded: bytes) -> None:
    if not trailer:
        return
    if len(trailer) != HWP_TRAILER_SIZE:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
    checksum, size = unpack_from("<II", trailer)
    if size != len(expanded) & 0xFFFFFFFF or checksum not in {0, zlib.crc32(expanded)}:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)


def expand_hwp_stream(content: bytes, limit: int) -> int:
    try:
        decoder = zlib.decompressobj(wbits=-15)
        expanded = decoder.decompress(content, limit + 1)
        if len(expanded) > limit or decoder.unconsumed_tail:
            raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)
        if not decoder.eof:
            raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
        validate_hwp_trailer(decoder.unused_data, expanded)
        return len(expanded)
    except zlib.error as error:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT) from error


def inspect_hwp_header(header: bytes) -> tuple[str, bool]:
    if len(header) != HWP_HEADER_SIZE or header[:32] != b"HWP Document File".ljust(32, b"\x00"):
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
    version, flags = unpack_from("<II", header, 32)
    components = tuple((version >> shift) & 0xFF for shift in (24, 16, 8, 0))
    # 5.1.0.1 and 5.0.2.4 come from older Hangul releases; real files read correctly.
    if components not in {(5, 1, 1, 0), (5, 1, 0, 1), (5, 0, 3, 4), (5, 0, 2, 4)}:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="hwp")
    if flags & ((1 << 1) | (1 << 8)):
        raise InputValidationError(InputErrorCode.ENCRYPTED_DOCUMENT, detected_format="hwp")
    if flags & ((1 << 2) | (1 << 4) | (1 << 10) | (1 << 13)):
        raise InputValidationError(InputErrorCode.PROTECTED_DOCUMENT, detected_format="hwp")
    if flags & (1 << 3) or flags >> 12:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_FEATURE, detected_format="hwp")
    return ".".join(str(part) for part in components), bool(flags & 1)


def order_sections(paths: tuple[str, ...]) -> tuple[str, ...]:
    sections = tuple(path for path in paths if path.startswith("BodyText/Section"))
    suffixes = tuple(path.removeprefix("BodyText/Section") for path in sections)
    if any(not suffix.isascii() or not suffix.isdecimal() for suffix in suffixes):
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwp")
    ordered = tuple(sorted(sections, key=lambda path: int(path.removeprefix("BodyText/Section"))))
    if ordered != tuple(f"BodyText/Section{number}" for number in range(len(ordered))):
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwp")
    return ordered


def inspect_compound(content: bytes, limits: InputLimits) -> FormatDetails:
    try:
        container: OleFileIO[str] = OleFileIO(BytesIO(content), raise_defects=DEFECT_INCORRECT)
        with container as document:
            paths = tuple("/".join(parts) for parts in document.listdir())
            if len(document.listdir(streams=True, storages=True)) > limits.max_members:
                raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)
            total = 0
            for path in paths:
                size = document.get_size(path)
                total += size
                if size > limits.max_member_bytes or total > limits.max_expanded_bytes:
                    raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)
            if document.exists("EncryptionInfo") and document.exists("EncryptedPackage"):
                raise InputValidationError(InputErrorCode.ENCRYPTED_DOCUMENT)
            if not document.exists("FileHeader"):
                raise InputValidationError(InputErrorCode.UNSUPPORTED_FORMAT)
            with document.openstream("FileHeader") as stream:
                version, compressed = inspect_hwp_header(stream.read())
            sections = order_sections(paths)
            if not document.exists("DocInfo") or not sections:
                raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwp")
            expanded_total = total - sum(document.get_size(path) for path in ("DocInfo", *sections))
            for path in ("DocInfo", *sections):
                with document.openstream(path) as stream:
                    data = stream.read()
                budget = min(limits.max_member_bytes, limits.max_expanded_bytes - expanded_total)
                expanded_total += expand_hwp_stream(data, budget) if compressed else len(data)
            return FormatDetails(
                detected_format="hwp",
                version=version,
                members=paths,
                content_members=sections,
            )
    except (
        OSError,
        ValueError,
        EOFError,
        IndexError,
        RecursionError,
        TypeError,
        StructError,
    ) as error:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT) from error
