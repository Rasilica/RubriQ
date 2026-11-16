import hashlib
import shutil
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Final, assert_never
from zipfile import ZIP_STORED, ZipFile

import generate_format_fixtures as generator
import olefile
import pytest
from defusedxml import ElementTree
from format_fixture_models import Manifest, PdfLocator, RecordLocator, Truth, XmlLocator
from pypdf import PdfReader

SAMPLES: Final = Path(__file__).resolve().parents[1] / "samples" / "formats"


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return Manifest.model_validate_json((SAMPLES / "manifest.json").read_bytes())


@pytest.fixture(scope="module")
def truth() -> Truth:
    return Truth.model_validate_json((SAMPLES / "truth.json").read_bytes())


def test_manifest_hashes_sizes_and_provenance_match_actual_files(manifest: Manifest) -> None:
    # Given / When
    observed = tuple((item, (SAMPLES / item.path).read_bytes()) for item in manifest.documents)
    # Then
    assert {item.format for item, _ in observed} == {"pdf", "docx", "hwpx", "hwp", "unknown"}
    assert len(observed) == len({item.id for item, _ in observed}) == 5
    for item, data in observed:
        assert hashlib.sha256(data).hexdigest() == item.sha256
        assert len(data) == item.size_bytes
        assert item.provenance == "synthetic_development_fixture"
        assert item.authoring_application is None
        assert not any(
            (
                item.human_review_completed,
                item.independent_evaluation,
                item.authored_app_original,
                item.rendering_verified,
                item.full_document_reader_verified,
            )
        )
        expected_family = (
            "before-submit-development-001" if item.format == "pdf" else "format-boundary-001"
        )
        assert item.family_id == expected_family
    encrypted = next(item for item in manifest.documents if item.id == "encrypted-ooxml-boundary")
    assert encrypted.format == "unknown"
    assert encrypted.version is None


def test_authored_truth_covers_four_documents_and_eleven_locators(
    manifest: Manifest,
    truth: Truth,
) -> None:
    # Given / When
    by_id = {item.id: item for item in manifest.documents}
    # Then
    assert not truth.human_review_completed
    assert not truth.independent_evaluation
    assert {item.id for item in truth.documents} == {
        "pdf-baseline",
        "docx-boundary",
        "hwpx-spine",
        "hwp5-boundary",
    }
    assert sum(len(item.cases) for item in truth.documents) == 11
    for item in truth.documents:
        assert (item.path, item.sha256, item.family_id) == (
            by_id[item.id].path,
            by_id[item.id].sha256,
            by_id[item.id].family_id,
        )
        if item.id != "pdf-baseline":
            assert item.page_count is None
            assert all(case.locator.original_page is None for case in item.cases)


@pytest.mark.parametrize(
    "document_id", ["pdf-baseline", "docx-boundary", "hwpx-spine", "hwp5-boundary"]
)
def test_expected_text_exists_at_each_authored_locator(document_id: str, truth: Truth) -> None:
    # Given
    document = next(item for item in truth.documents if item.id == document_id)
    # When / Then
    for case in document.cases:
        match case.locator:
            case XmlLocator() as location:
                with ZipFile(SAMPLES / document.path) as archive:
                    root = ElementTree.fromstring(archive.read(location.member))
                _, root_name, relative = location.path.split("/", 2)
                prefix, local = root_name.split(":")
                assert root.tag == f"{{{truth.namespaces[prefix]}}}{local}"
                nodes = root.findall("./" + relative, truth.namespaces)
                assert len(nodes) == 1
                assert nodes[0].text == case.expected_text
            case RecordLocator() as location:
                with olefile.OleFileIO(str(SAMPLES / document.path)) as compound:
                    data = compound.openstream(location.stream).read()
                offset = 0
                for _ in range(location.record_index):
                    offset += 4 + (struct.unpack_from("<I", data, offset)[0] >> 20)
                assert offset == location.record_offset
                header = struct.unpack_from("<I", data, offset)[0]
                assert (header & 1023, (header >> 10) & 1023, header >> 20) == (
                    location.tag_id,
                    location.level,
                    location.payload_length,
                )
                assert location.payload_offset == offset + 4
                payload = data[
                    location.payload_offset : location.payload_offset + location.payload_length
                ]
                assert (
                    payload.decode(location.encoding) == case.expected_text + case.trailing_control
                )
            case PdfLocator() as location:
                pdf = PdfReader(SAMPLES / document.path)
                assert len(pdf.pages) == document.page_count == 2
                assert case.expected_text in pdf.pages[location.original_page - 1].extract_text()
            case unreachable:
                assert_never(unreachable)


def test_hwpx_version_and_manifest_preserve_reversed_spine(truth: Truth) -> None:
    # Given
    document = next(item for item in truth.documents if item.id == "hwpx-spine")
    opf = {"opf": "http://www.idpf.org/2007/opf/"}
    # When
    with ZipFile(SAMPLES / document.path) as archive:
        version = ElementTree.fromstring(archive.read("version.xml"))
        package = ElementTree.fromstring(archive.read("Contents/content.hpf"))
        items = {
            item.attrib["id"]: item.attrib["href"]
            for item in package.findall("opf:manifest/opf:item", opf)
        }
        spine = tuple(
            items[item.attrib["idref"]] for item in package.findall("opf:spine/opf:itemref", opf)
        )
        sections = tuple(
            member
            for member in spine
            if ElementTree.fromstring(archive.read(member)).tag
            == f"{{{truth.namespaces['hs']}}}sec"
        )
        # Then
        assert archive.namelist()[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == ZIP_STORED
        assert archive.read("mimetype") == b"application/hwp+zip"
    assert version.tag == "{http://www.hancom.co.kr/hwpml/2011/version}HCFVersion"
    assert tuple(
        version.attrib[k] for k in ("major", "minor", "micro", "buildNumber", "xmlVersion")
    ) == ("5", "1", "1", "0", "1.5")
    assert (
        sections
        == document.ordered_section_members
        == ("Contents/section1.xml", "Contents/section0.xml")
    )
    assert tuple(
        case.locator.section_reading_index
        for case in document.cases
        if isinstance(case.locator, XmlLocator)
    ) == (0, 1)


@pytest.mark.parametrize("filename", ["boundary.docx", "spine-order.hwpx"])
def test_packaged_xml_is_well_formed_and_crc_valid(filename: str) -> None:
    # Given / When
    with ZipFile(SAMPLES / filename) as archive:
        # Then
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist()))
        for member in archive.namelist():
            if member != "mimetype":
                assert ElementTree.fromstring(archive.read(member)) is not None


def test_hwp_header_flags_and_record_frames_match_the_declared_boundary() -> None:
    # Given / When
    with olefile.OleFileIO(
        str(SAMPLES / "minimal-5.1.1.0.hwp"), raise_defects=olefile.DEFECT_UNSURE
    ) as compound:
        # Then
        assert compound.listdir() == [["BodyText", "Section0"], ["DocInfo"], ["FileHeader"]]
        header = compound.openstream("FileHeader").read()
        assert len(header) == 256
        assert header[:32] == b"HWP Document File".ljust(32, b"\0")
        assert struct.unpack_from("<II", header, 32) == (0x05010100, 0)
        for name, frames in (
            ("DocInfo", ((16, 0, 26),)),
            ("BodyText/Section0", ((66, 0, 24), (67, 1, 42), (68, 1, 8))),
        ):
            data = compound.openstream(name).read()
            offset = 0
            for expected in frames:
                value = struct.unpack_from("<I", data, offset)[0]
                assert (value & 1023, (value >> 10) & 1023, value >> 20) == expected
                offset += 4 + (value >> 20)
            assert offset == len(data)


def test_encrypted_marker_streams_are_explicit_placeholders() -> None:
    # Given / When
    with olefile.OleFileIO(
        str(SAMPLES / "encrypted-ooxml.cfb"), raise_defects=olefile.DEFECT_UNSURE
    ) as compound:
        # Then
        assert compound.listdir() == [["EncryptedPackage"], ["EncryptionInfo"]]
        assert compound.openstream("EncryptionInfo").read() == b"SYNTHETIC-NOT-ENCRYPTION"
        assert compound.openstream("EncryptedPackage").read() == b"UNDECRYPTABLE-PLACEHOLDER"


@pytest.mark.parametrize(
    ("filename", "builder"),
    [
        ("minimal-5.1.1.0.hwp", generator.build_hwp),
        ("encrypted-ooxml.cfb", generator.build_encrypted_placeholder),
    ],
)
def test_cfb_generation_reproduces_committed_bytes(
    filename: str, builder: Callable[[], bytes]
) -> None:
    # Given / When
    generated = builder()
    # Then
    assert generated == (SAMPLES / filename).read_bytes()


@pytest.mark.parametrize(
    ("source", "filename"), [("docx", "boundary.docx"), ("hwpx", "spine-order.hwpx")]
)
def test_zip_generation_reproduces_committed_bytes_in_temporary_directory(
    source: str,
    filename: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    shutil.copytree(SAMPLES / "sources" / source, tmp_path / "sources" / source)
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    # When
    generator.write_package(source, filename)
    # Then
    assert (tmp_path / filename).read_bytes() == (SAMPLES / filename).read_bytes()
