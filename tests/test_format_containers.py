import struct
import zlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
from generate_format_fixtures import END, Directory, fixed_compound, record
from olefile import OleFileIO

from submission import compound_documents, format_containers
from submission.docx_validation import relationship_target
from submission.format_containers import parse_xml, read_package
from submission.formats import inspect_document
from submission.input_contracts import (
    DocumentInput,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)
from submission.models import DocumentRole


def raw_deflate(content: bytes) -> bytes:
    encoder = zlib.compressobj(wbits=-15)
    return encoder.compress(content) + encoder.flush()


def test_hwp_budget_includes_uncompressed_metadata_and_expanded_body() -> None:
    header = b"HWP Document File".ljust(32, b"\0")
    header += struct.pack("<II", 0x05010100, 1) + bytes(216)
    doc_info = raw_deflate(record(16, 0, b"D" * 56))
    section = raw_deflate(record(67, 0, ("S" * 28).encode("utf-16le")))
    metadata = b"O" * 64
    data = header + doc_info.ljust(64, b"\0") + section.ljust(64, b"\0") + metadata
    entries = (
        Directory("Root Entry", 5, child=2, start=3, size=len(data)),
        Directory("DocInfo", 2, left=5, start=4, size=len(doc_info)),
        Directory("BodyText", 1, left=1, right=3, child=4),
        Directory("FileHeader", 2, start=0, size=len(header)),
        Directory("Section0", 2, start=5, size=len(section)),
        Directory("Other", 2, start=6, size=len(metadata), color=0),
        Directory("", 0),
        Directory("", 0),
    )
    content = fixed_compound(entries, (1, 2, 3, END, END, END, END), data)
    source = DocumentInput("report.hwp", content, DocumentRole.REPORT)
    assert (
        inspect_document(source, InputLimits(max_expanded_bytes=450)).source.detected_format
        == "hwp"
    )
    with pytest.raises(InputValidationError) as caught:
        inspect_document(source, InputLimits(max_expanded_bytes=360))
    assert caught.value.code is InputErrorCode.PACKAGE_LIMIT


def test_hwp_sections_are_numeric_and_contiguous() -> None:
    paths = tuple(f"BodyText/Section{number}" for number in reversed(range(12)))
    assert compound_documents.order_sections(paths) == tuple(
        f"BodyText/Section{number}" for number in range(12)
    )


@pytest.mark.parametrize("path", ["BodyText/SectionX", "BodyText/Section1", "BodyText/Section00"])
def test_invalid_hwp_section_names_are_corrupt(path: str) -> None:
    with pytest.raises(InputValidationError) as caught:
        compound_documents.order_sections((path,))
    assert caught.value.code is InputErrorCode.CORRUPT_DOCUMENT


def test_malformed_relationship_url_is_a_safe_typed_rejection() -> None:
    with pytest.raises(InputValidationError) as caught:
        relationship_target("word/document.xml", "http://[invalid")
    assert caught.value.code is InputErrorCode.UNSAFE_PACKAGE_PATH


@pytest.mark.parametrize(
    ("content", "limits", "expected"),
    [
        (b"<a><b/></a>", InputLimits(max_xml_nodes=1), InputErrorCode.XML_LIMIT),
        (b"<a><b/></a>", InputLimits(max_xml_depth=1), InputErrorCode.XML_LIMIT),
        (b"<a/>", InputLimits(max_xml_bytes=3), InputErrorCode.XML_LIMIT),
        (b"<!DOCTYPE a><a/>", InputLimits(), InputErrorCode.UNSAFE_XML),
        (b"<a>", InputLimits(), InputErrorCode.CORRUPT_DOCUMENT),
    ],
)
def test_small_xml_boundaries(
    content: bytes, limits: InputLimits, expected: InputErrorCode
) -> None:
    with pytest.raises(InputValidationError) as caught:
        parse_xml(content, limits)
    assert caught.value.code is expected
    assert str(caught.value) == expected.value


def stored_package(members: tuple[tuple[str, bytes], ...]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


def test_zip_duplicate_aliases_are_rejected() -> None:
    content = stored_package((("a.xml", b"<a/>"), ("A.xml", b"<a/>")))
    with pytest.raises(InputValidationError) as caught:
        read_package(content, InputLimits())
    assert caught.value.code is InputErrorCode.DUPLICATE_MEMBER


@pytest.mark.parametrize(
    "limits", [InputLimits(max_member_bytes=3), InputLimits(max_expanded_bytes=7)]
)
def test_zip_small_expansion_limits(limits: InputLimits) -> None:
    content = stored_package((("a.xml", b"<a/>"), ("b.xml", b"<b/>")))
    with pytest.raises(InputValidationError) as caught:
        read_package(content, limits)
    assert caught.value.code is InputErrorCode.PACKAGE_LIMIT


def test_zip_crc_failure_is_corruption() -> None:
    content = stored_package((("a.xml", b"<a/>"),)).replace(b"<a/>", b"<b/>", 1)
    with pytest.raises(InputValidationError) as caught:
        read_package(content, InputLimits())
    assert caught.value.code is InputErrorCode.CORRUPT_DOCUMENT


def test_zip_member_limit_is_checked_before_zipfile_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = stored_package((("a.xml", b"<a/>"), ("b.xml", b"<b/>")))

    def unexpected_constructor(*_args: bytes, **_kwargs: str) -> None:
        pytest.fail("ZipFile construction must follow bounded directory preflight")

    monkeypatch.setattr(format_containers, "ZipFile", unexpected_constructor)
    with pytest.raises(InputValidationError) as caught:
        read_package(content, InputLimits(max_members=1))
    assert caught.value.code is InputErrorCode.PACKAGE_LIMIT


@pytest.mark.parametrize(
    ("content", "limit", "expected"),
    [
        (raw_deflate(b"small"), 3, InputErrorCode.PACKAGE_LIMIT),
        (raw_deflate(b"small")[:-1], 10, InputErrorCode.CORRUPT_DOCUMENT),
        (raw_deflate(b"small") + b"trailing", 10, InputErrorCode.CORRUPT_DOCUMENT),
    ],
)
def test_compressed_hwp_streams_have_bounded_complete_framing(
    content: bytes,
    limit: int,
    expected: InputErrorCode,
) -> None:
    with pytest.raises(InputValidationError) as caught:
        compound_documents.expand_hwp_stream(content, limit)
    assert caught.value.code is expected


@pytest.mark.parametrize("checksum_kind", ["crc32", "maintainer_zero"])
def test_hwp_verified_and_maintainer_footer_profiles(checksum_kind: str) -> None:
    payload = record(16, 0, b"small")
    checksum = zlib.crc32(payload) if checksum_kind == "crc32" else 0
    content = raw_deflate(payload) + struct.pack("<II", checksum, len(payload))
    assert compound_documents.expand_hwp_stream(content, 20) == len(payload)


@pytest.mark.parametrize(("checksum", "size"), [(1, 5), (0, 99)])
def test_invalid_hwp_footer_is_corruption(checksum: int, size: int) -> None:
    content = raw_deflate(b"small") + struct.pack("<II", checksum, size)
    with pytest.raises(InputValidationError) as caught:
        compound_documents.expand_hwp_stream(content, 20)
    assert caught.value.code is InputErrorCode.CORRUPT_DOCUMENT


def test_zip_directory_preflight_requires_same_position_as_parser() -> None:
    content = stored_package((("a.xml", b"<a/>"),))
    index = content.rfind(b"PK\x05\x06")
    original_offset = struct.unpack_from("<I", content, index + 16)[0]
    changed = content[: index + 16] + struct.pack("<I", original_offset - 1) + content[index + 20 :]
    with pytest.raises(InputValidationError) as caught:
        format_containers.directory_bounds(changed)
    assert caught.value.code is InputErrorCode.CORRUPT_DOCUMENT


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (2, InputErrorCode.ENCRYPTED_DOCUMENT),
        (256, InputErrorCode.ENCRYPTED_DOCUMENT),
        (4, InputErrorCode.PROTECTED_DOCUMENT),
        (16, InputErrorCode.PROTECTED_DOCUMENT),
        (1024, InputErrorCode.PROTECTED_DOCUMENT),
        (8192, InputErrorCode.PROTECTED_DOCUMENT),
        (8, InputErrorCode.UNSUPPORTED_FEATURE),
    ],
)
def test_hwp_protection_is_distinct_from_damage(flags: int, expected: InputErrorCode) -> None:
    content = (Path(__file__).parents[1] / "samples/formats/minimal-5.1.1.0.hwp").read_bytes()
    buffer = BytesIO(content)
    with OleFileIO(buffer, write_mode=True) as document:
        header = document.openstream("FileHeader").read()
        document.write_stream("FileHeader", header[:36] + struct.pack("<I", flags) + header[40:])
    with pytest.raises(InputValidationError) as caught:
        inspect_document(DocumentInput("report.hwp", buffer.getvalue(), DocumentRole.REPORT))
    assert caught.value.code is expected
    assert caught.value.detected_format == "hwp"


def test_encrypted_ooxml_does_not_invent_word_subtype() -> None:
    content = (Path(__file__).parents[1] / "samples/formats/encrypted-ooxml.cfb").read_bytes()
    with pytest.raises(InputValidationError) as caught:
        inspect_document(DocumentInput("report.docx", content, DocumentRole.REPORT))
    assert caught.value.code is InputErrorCode.ENCRYPTED_DOCUMENT
    assert caught.value.detected_format is None
