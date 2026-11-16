from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from conversion_helpers import source_docx
from defusedxml.ElementTree import fromstring
from pydantic import ValidationError

from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.conversion_profile import prepare_profile, reject_active_content


def test_profiles_are_independent_and_disable_loading_active_content(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    profiles = (prepare_profile(first), prepare_profile(second))

    assert profiles[0] != profiles[1]
    for profile in profiles:
        tree = fromstring((profile / "user/registrymodifications.xcu").read_bytes())
        properties = {
            node.attrib["{http://openoffice.org/2001/registry}name"]: node.findtext("value")
            for node in tree.iter("prop")
        }
        assert properties["DisableMacrosExecution"] == "true"
        assert properties["DisableActiveContent"] == "true"
        assert properties["BlockUntrustedRefererLinks"] == "true"
        assert properties["Link"] == "2"
        assert properties["Field"] == "false"
        assert properties["Chart"] == "false"


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), "60", True])
def test_config_rejects_unsafe_deadlines(tmp_path: Path, timeout) -> None:
    with pytest.raises(ValidationError):
        ConversionConfig(soffice=tmp_path, work_root=tmp_path, timeout_seconds=timeout)


@pytest.mark.parametrize("part", ["external", "embedding", "macro"])
def test_package_preflight_rejects_unsupported_active_parts(part: str) -> None:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            archive.writestr(member, original.read(member))
        if part == "external":
            archive.writestr(
                "word/_rels/extra.xml.rels",
                '<Relationships><Relationship TargetMode="External" Target="https://example.invalid/"/></Relationships>',
            )
        elif part == "embedding":
            archive.writestr("word/embeddings/object.bin", b"benign test")
        else:
            archive.writestr("word/vbaProject.bin", b"benign test")

    with pytest.raises(ConversionError) as caught:
        reject_active_content(output.getvalue())

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


def package_with_footer(field_xml: str) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(source_docx().content)) as original, ZipFile(output, "w") as archive:
        for member in original.infolist():
            if member.filename != "word/footer1.xml":
                archive.writestr(member, original.read(member))
        archive.writestr(
            "word/footer1.xml",
            '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:p>{field_xml}</w:p></w:ftr>",
        )
    return output.getvalue()


@pytest.mark.parametrize(
    "field_xml",
    [
        '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>',
        '<w:fldSimple w:instr=" NUMPAGES "/>',
        r'<w:fldSimple w:instr="PAGE \* MERGEFORMAT"/>',
        r'<w:fldSimple w:instr="NUMPAGES \* Arabic"/>',
        (
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText>PA</w:instrText></w:r>"
            "<w:r><w:instrText>GE</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>1</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        ),
        (
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText> NUMPAGES </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        ),
        '<w:fldSimple w:instr="PAGE"/><w:fldSimple w:instr="NUMPAGES"/>',
    ],
)
def test_package_preflight_accepts_only_complete_pagination_fields(field_xml: str) -> None:
    content = package_with_footer(field_xml)

    result = reject_active_content(content)

    assert result is None


@pytest.mark.parametrize(
    "field_xml",
    [
        '<w:fldSimple w:instr="DATE"/>',
        '<w:fldSimple w:instr="PAGE extra"/>',
        '<w:fldSimple w:instr="PAGE NUMPAGES"/>',
        r'<w:fldSimple w:instr="PAGE \* UNKNOWN"/>',
        "<w:fldSimple/>",
        '<w:fldSimple instr="PAGE"/>',
        '<w:fldSimple w:instr="PAGE"><w:fldSimple w:instr="NUMPAGES"/></w:fldSimple>',
        '<w:fldSimple w:instr="PAGE"><w:instrText>PAGE</w:instrText></w:fldSimple>',
        "<w:instrText>PAGE</w:instrText>",
        '<w:fldChar w:fldCharType="end"/>',
        '<w:fldChar w:fldCharType="separate"/>',
        '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>',
        '<w:fldChar w:fldCharType="begin"/><w:fldChar w:fldCharType="end"/>',
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>DATE</w:instrText>'
            '<w:fldChar w:fldCharType="end"/>'
        ),
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
            '<w:fldChar w:fldCharType="begin"/><w:instrText>NUMPAGES</w:instrText>'
            '<w:fldChar w:fldCharType="end"/><w:fldChar w:fldCharType="end"/>'
        ),
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
            '<w:fldSimple w:instr="NUMPAGES"/><w:fldChar w:fldCharType="end"/>'
        ),
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
            '<w:fldChar w:fldCharType="separate"/><w:instrText>NUMPAGES</w:instrText>'
            '<w:fldChar w:fldCharType="end"/>'
        ),
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
            '<w:fldChar w:fldCharType="separate"/><w:fldChar w:fldCharType="separate"/>'
            '<w:fldChar w:fldCharType="end"/>'
        ),
        '<w:fldChar w:fldCharType="unknown"/>',
        '<w:fldChar w:fldCharType="begin"><w:fldData/></w:fldChar>',
        (
            '<w:fldChar w:fldCharType="begin"/>'
            "<w:instrText>PAGE<w:t>extra</w:t></w:instrText>"
            '<w:fldChar w:fldCharType="end"/>'
        ),
        '<w:fldSimple xmlns:w="urn:unknown" w:instr="PAGE"/>',
        '<w:fldSimple w:instr="PAGE"><w:object/></w:fldSimple>',
    ],
)
def test_package_preflight_rejects_other_or_ambiguous_fields(field_xml: str) -> None:
    content = package_with_footer(field_xml)

    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)

    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


@pytest.mark.parametrize(
    "field",
    [
        '<w:fldSimple w:instr="PAGE"/>',
        (
            '<w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText>'
            '<w:fldChar w:fldCharType="end"/>'
        ),
    ],
)
def test_fields_inside_alternate_content_are_conservatively_rejected(field: str) -> None:
    content = package_with_footer(
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        f'<mc:Choice Requires="w">{field}</mc:Choice><mc:Fallback/>'
        "</mc:AlternateContent>"
    )
    with pytest.raises(ConversionError) as caught:
        reject_active_content(content)
    assert caught.value.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT


def test_alternate_content_without_fields_is_accepted() -> None:
    content = package_with_footer(
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        '<mc:Choice Requires="w"><w:r><w:t>Choice</w:t></w:r></mc:Choice>'
        "<mc:Fallback><w:r><w:t>Fallback</w:t></w:r></mc:Fallback></mc:AlternateContent>"
    )
    assert reject_active_content(content) is None
