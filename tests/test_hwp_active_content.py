from pathlib import Path
from struct import pack

import pytest

from submission.conversion_contracts import ConversionError
from submission.hwp_content import check_docinfo, check_section, reject_hwp_active_content
from submission.input_contracts import InputLimits

BIN_DATA, CTRL_HEADER = 16 + 2, 16 + 55


def record(tag: int, body: bytes) -> bytes:
    return pack("<I", (len(body) << 20) | tag) + body


def bin_data(kind: int) -> bytes:
    return record(BIN_DATA, pack("<H", kind) + bytes(6))


def field(ctrl: str, command: str = "") -> bytes:
    text = command.encode("utf-16-le")
    body = ctrl[::-1].encode("latin-1") + bytes(5) + pack("<H", len(command)) + text + bytes(4)
    return record(CTRL_HEADER, body)


def test_minimal_hwp_fixture_passes() -> None:
    content = Path("samples/formats/minimal-5.1.1.0.hwp").read_bytes()

    reject_hwp_active_content(content, InputLimits())


def test_embedded_pictures_are_allowed() -> None:
    check_docinfo(bin_data(1))


@pytest.mark.parametrize("kind", [0, 2], ids=["linked-file", "ole-storage"])
def test_linked_files_and_ole_objects_are_rejected(kind: int) -> None:
    with pytest.raises(ConversionError, match="unsupported_active_content"):
        check_docinfo(bin_data(kind))


@pytest.mark.parametrize(
    "data",
    [
        record(CTRL_HEADER, b" lbt" + bytes(8)),
        field("%clk", "Clickhere:set:0:Direction:wstring:3:abc"),
        field("%fmu", "=SUM(A1:A3)"),
        field("%hlk", "http\\://www.example.invalid;1;0;0;"),
        field("%hlk", "www.daum.net|-;1;0;0"),
    ],
)
def test_inert_controls_and_safe_links_are_allowed(data: bytes) -> None:
    check_section(data)


@pytest.mark.parametrize(
    "data",
    [
        field("%dde", "excel|sheet"),
        field("%hlk", "file\\:///etc/passwd;1;0;0;"),
        field("%hlk", "../secret.hwp;1;0;0;"),
        field("%hlk", "C\\:\\\\Windows\\\\run.exe;1;0;0;"),
        record(CTRL_HEADER, b"klh%" + bytes(5) + pack("<H", 50) + b"x"),
    ],
)
def test_other_fields_unsafe_links_and_truncation_are_rejected(data: bytes) -> None:
    with pytest.raises(ConversionError, match="unsupported_active_content"):
        check_section(data)
