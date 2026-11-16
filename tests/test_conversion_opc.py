from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import SubElement, tostring
from zipfile import ZipFile

import pytest
from conversion_helpers import source_docx
from defusedxml.ElementTree import fromstring
from test_conversion_profile import package_with_footer

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_profile import reject_active_content

CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FOOTER_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"


def declared_package(name: str, content_type: str, payload: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            data = original.read(member)
            if member.filename == "[Content_Types].xml":
                root = fromstring(data)
                _ = SubElement(
                    root, f"{{{CONTENT_NS}}}Override", PartName=f"/{name}", ContentType=content_type
                )
                data = tostring(root)
            archive.writestr(member, data)
        archive.writestr(name, payload)
    return output.getvalue()


@pytest.mark.parametrize(
    "field",
    [
        "<w:delInstrText>PAGE</w:delInstrText>",
        '<w:fldSimple w:instr="PAGE"><w:delInstrText>DATE</w:delInstrText></w:fldSimple>',
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
            "<w:del><w:r><w:delInstrText>DATE</w:delInstrText></w:r></w:del>"
            '<w:fldChar w:fldCharType="end"/>'
        ),
    ],
)
def test_deleted_field_instructions_are_rejected(field: str) -> None:
    content = package_with_footer(field)

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize("name", ["word/other.bin", "word/other.XML", "word/other"])
@pytest.mark.parametrize("field", ['<w:fldSimple w:instr="DATE"/>', "<w:altChunk/>"])
def test_declared_xml_is_inspected_independently_of_filename(name: str, field: str) -> None:
    content = declared_package(
        name, FOOTER_TYPE, f'<w:ftr xmlns:w="{WORD_NS}">{field}</w:ftr>'.encode()
    )

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    "relation",
    [
        "vbaProject",
        "oleObject",
        "package",
        "control",
        "aFChunk",
        "subDocument",
        "attachedTemplate",
    ],
)
def test_active_relationships_are_rejected_with_inert_targets(relation: str) -> None:
    payload = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="r1" '
        f'Type="{OFFICE_REL}{relation}" Target="document.xml"/></Relationships>'
    ).encode()
    content = declared_package(
        "word/_rels/footer1.xml.rels",
        "application/vnd.openxmlformats-package.relationships+xml",
        payload,
    )

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    "content_type",
    [
        "application/vnd.ms-office.vbaProject",
        "application/vnd.openxmlformats-officedocument.oleObject",
        "application/vnd.ms-word.document.macroEnabled.main+xml",
        "application/vnd.ms-office.activeX+xml",
        "application/octet-stream",
        "image/svg+xml",
    ],
)
def test_unsupported_content_types_are_rejected(content_type: str) -> None:
    content = declared_package("word/innocent.bin", content_type, b"<root/>")

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize("name", ["word/other.bin", "word/other.XML", "word/other"])
def test_pagination_is_allowed_in_declared_xml(name: str) -> None:
    content = declared_package(
        name,
        FOOTER_TYPE,
        f'<w:ftr xmlns:w="{WORD_NS}"><w:fldSimple w:instr="PAGE"/></w:ftr>'.encode(),
    )

    result = reject_active_content(content)

    assert result is None


def test_synthetic_docx_with_embedded_png_is_accepted() -> None:
    content = declared_package(
        "word/media/screenshot.png",
        "image/png",
        Path("samples/result-demos/pages/normal-1.png").read_bytes(),
    )

    result = reject_active_content(content)

    assert result is None


def test_pagination_across_paragraphs_is_accepted() -> None:
    content = package_with_footer(
        '<w:fldChar w:fldCharType="begin"/></w:p><w:p>'
        "<w:instrText>PAGE</w:instrText></w:p><w:p>"
        '<w:fldChar w:fldCharType="end"/>'
    )

    result = reject_active_content(content)

    assert result is None


@pytest.mark.parametrize("part_type", ["drawing", "drawingml.chart", "drawingml.diagramData"])
def test_inert_drawing_xml_is_accepted(part_type: str) -> None:
    content = declared_package(
        "word/drawing.bin",
        f"application/vnd.openxmlformats-officedocument.{part_type}+xml",
        b"<root/>",
    )

    result = reject_active_content(content)

    assert result is None


def test_default_declaration_selects_xml_without_xml_extension() -> None:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            data = original.read(member)
            if member.filename == "[Content_Types].xml":
                root = fromstring(data)
                _ = SubElement(
                    root,
                    f"{{{CONTENT_NS}}}Default",
                    Extension="data",
                    ContentType="application/xml",
                )
                data = tostring(root)
            archive.writestr(member, data)
        archive.writestr(
            "word/extra.DATA", f'<w:ftr xmlns:w="{WORD_NS}"><w:fldSimple w:instr="DATE"/></w:ftr>'
        )
    content = output.getvalue()

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    "name", ["word/vbaProject.bin", "word/embeddings/data.png", "word/activex/a.png"]
)
def test_active_filenames_remain_rejected_even_if_declared_as_image(name: str) -> None:
    content = declared_package(name, "image/png", b"inert fixture")

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


def test_footer_relationship_cannot_hide_xml_as_an_image() -> None:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            data = original.read(member)
            if member.filename == "[Content_Types].xml":
                root = fromstring(data)
                for node in root:
                    if node.get("PartName") == "/word/footer1.xml":
                        node.set("PartName", "/word/footer1.bin")
                        node.set("ContentType", "image/jpeg")
                data = tostring(root)
            if member.filename == "word/_rels/document.xml.rels":
                root = fromstring(data)
                for node in root:
                    if node.get("Type") == f"{OFFICE_REL}footer":
                        node.set("Target", "footer1.bin")
                data = tostring(root)
            if member.filename != "word/footer1.xml":
                archive.writestr(member, data)
        archive.writestr(
            "word/footer1.bin", f'<w:ftr xmlns:w="{WORD_NS}"><w:fldSimple w:instr="DATE"/></w:ftr>'
        )
    content = output.getvalue()

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    "payload", [b"<unfinished", b'<!DOCTYPE x [<!ENTITY y "value">]><x>&y;</x>']
)
@pytest.mark.parametrize("name", ["word/extra.bin", "word/extra"])
def test_malformed_or_forbidden_declared_xml_uses_conversion_error(
    name: str, payload: bytes
) -> None:
    content = declared_package(name, "application/xml", payload)

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


def test_standard_glossary_content_type_is_accepted() -> None:
    content = declared_package(
        "word/glossary/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml",
        f'<w:glossaryDocument xmlns:w="{WORD_NS}"/>'.encode(),
    )
    assert reject_active_content(content) is None


@pytest.mark.parametrize(
    "content_type", ["image/png", "image/jpeg", "image/gif", "image/bmp", "image/tiff"]
)
@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not an image",
        b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF",
    ],
)
def test_declared_raster_must_have_matching_signature(content_type: str, payload: bytes) -> None:
    content = declared_package("word/media/image.bin", content_type, payload)
    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    ("content_type", "signature"),
    [
        ("image/png", b"\x89PNG\r\n\x1a\n"),
        ("image/jpeg", b"\xff\xd8\xff"),
        ("image/gif", b"GIF87a"),
        ("image/gif", b"GIF89a"),
        ("image/bmp", b"BM"),
        ("image/tiff", b"II\x2a\x00"),
        ("image/tiff", b"MM\x00\x2a"),
    ],
)
def test_raster_signature_matches_declared_type(content_type: str, signature: bytes) -> None:
    # This boundary identifies formats; it deliberately does not decode complete images.
    assert (
        reject_active_content(declared_package("word/media/image.bin", content_type, signature))
        is None
    )
    different_type = "image/jpeg" if content_type == "image/png" else "image/png"
    with pytest.raises(ConversionError) as caught:
        reject_active_content(declared_package("word/media/image.bin", different_type, signature))
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    "relationship_type",
    [
        f"{OFFICE_REL}image",
        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail",
    ],
)
def test_image_relationship_requires_raster_content_type(relationship_type: str) -> None:
    payload = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="r1" '
        f'Type="{relationship_type}" Target="document.xml"/></Relationships>'
    ).encode()
    content = declared_package(
        "word/_rels/image.xml.rels",
        "application/vnd.openxmlformats-package.relationships+xml",
        payload,
    )
    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize("name", ["word/extra.xml", "word/extra.rels"])
def test_xml_payload_declared_as_raster_is_rejected(name: str) -> None:
    content = declared_package(name, "image/png", b"<root/>")
    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


def replace_content_types(payload: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            archive.writestr(
                member,
                payload if member.filename == "[Content_Types].xml" else original.read(member),
            )
    return output.getvalue()


@pytest.mark.parametrize(
    "declarations",
    [
        '<Default Extension="" ContentType="application/xml"/>',
        (
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="XML" ContentType="application/xml"/>'
        ),
        '<Override PartName="" ContentType="application/xml"/>',
        (
            '<Override PartName="/word/document.xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/xml"/>'
        ),
        '<Other ContentType="application/xml"/>',
    ],
)
def test_empty_duplicate_or_unknown_declarations_are_rejected(declarations: str) -> None:
    content = replace_content_types(f'<Types xmlns="{CONTENT_NS}">{declarations}</Types>'.encode())
    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


def test_undeclared_binary_part_is_rejected() -> None:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            archive.writestr(member, original.read(member))
        archive.writestr("word/unknown.bin", b"benign data")
    with pytest.raises(ConversionError) as caught:
        reject_active_content(output.getvalue())
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("word/_rels/extra.xml.rels", "missing.xml"),
        ("word/_rels/extra.xml.rels", ""),
        ("word/_rels/extra.xml.rels", "../../../outside.xml"),
        ("word/invalid.rels", "document.xml"),
    ],
)
def test_invalid_relationship_owner_or_target_is_rejected(name: str, target: str) -> None:
    payload = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="r1" '
        f'Type="{OFFICE_REL}footer" Target="{target}"/></Relationships>'
    ).encode()
    content = declared_package(
        name, "application/vnd.openxmlformats-package.relationships+xml", payload
    )
    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT
