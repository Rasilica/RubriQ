"""Reject HWP binary content that could load outside files or objects during PDF rendering."""

import struct
import zlib
from collections.abc import Iterator
from io import BytesIO
from struct import unpack_from

from olefile import OleFileIO

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.hancom_content import is_safe_link
from submission.input_contracts import InputLimits

TAG_BIN_DATA = 16 + 2
TAG_CTRL_HEADER = 16 + 55
EXTENDED_SIZE = 0xFFF  # record size continues in the next 4 bytes
CONTROL_ID_BYTES = 4
BIN_LINK, BIN_STORAGE = 0, 2  # linked outside file, embedded OLE object
# Same inert set as HWPX: click-here placeholders, hyperlinks and table formulas.
INERT_FIELDS = frozenset({"%clk", "%hlk", "%fmu"})


def blocked() -> ConversionError:
    return ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)


def records(data: bytes) -> Iterator[tuple[int, bytes]]:
    offset = 0
    while offset < len(data):
        header = unpack_from("<I", data, offset)[0]
        offset += 4
        size = header >> 20
        if size == EXTENDED_SIZE:
            size = unpack_from("<I", data, offset)[0]
            offset += 4
        if offset + size > len(data):
            raise blocked()
        yield header & 0x3FF, data[offset : offset + size]
        offset += size


def check_docinfo(data: bytes) -> None:
    for tag, body in records(data):
        if tag == TAG_BIN_DATA and unpack_from("<H", body)[0] & 0xF in {BIN_LINK, BIN_STORAGE}:
            raise blocked()


def field_command(body: bytes) -> str:
    length = unpack_from("<H", body, 9)[0]
    if 11 + 2 * length > len(body):
        raise blocked()
    return body[11 : 11 + 2 * length].decode("utf-16-le")


def check_section(data: bytes) -> None:
    for tag, body in records(data):
        if tag != TAG_CTRL_HEADER or len(body) < CONTROL_ID_BYTES:
            continue
        control = body[:CONTROL_ID_BYTES][::-1].decode("latin-1")
        if not control.startswith("%"):
            continue
        if control not in INERT_FIELDS:
            raise blocked()
        if control == "%hlk" and not is_safe_link(field_command(body).split(";", 1)[0]):
            raise blocked()


def reject_hwp_active_content(content: bytes, limits: InputLimits) -> None:
    """Called after inspect_document, so the container and sizes are already validated."""
    try:
        container: OleFileIO[str] = OleFileIO(BytesIO(content))
        with container as document:
            header = document.openstream("FileHeader").read()
            compressed = bool(unpack_from("<I", header, 36)[0] & 1)

            def stream(path: str) -> bytes:
                raw = document.openstream(path).read()
                if not compressed:
                    return raw
                return zlib.decompressobj(-15).decompress(raw, limits.max_member_bytes)

            check_docinfo(stream("DocInfo"))
            for entry in document.listdir():
                if entry[0] == "BodyText":
                    check_section(stream("/".join(entry)))
    except ConversionError:
        raise
    except (OSError, ValueError, struct.error, UnicodeDecodeError, zlib.error) as error:
        raise blocked() from error
