from io import BytesIO
from zipfile import ZipFile

import pytest
from test_conversion_profile import package_with_footer

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_fields import neutralize_picture_fields
from submission.conversion_profile import reject_active_content

URL = "https://example.invalid/pasted.png"
RESULT = "<w:r><w:drawing/></w:r>"
INCLUDE = f'INCLUDEPICTURE "{URL}"'


def complex_field(instruction: str, result: str = RESULT, *, split: bool = False) -> str:
    if split:
        half = len(instruction) // 2
        parts = (instruction[:half], instruction[half:])
    else:
        parts = (instruction,)
    code = "".join(
        "<w:r><w:rPr><w:noProof/></w:rPr>"
        f'<w:instrText xml:space="preserve">{part}</w:instrText></w:r>'
        for part in parts
    )
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'{code}<w:r><w:fldChar w:fldCharType="separate"/></w:r>{result}'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def footer_of(content: bytes) -> str:
    with ZipFile(BytesIO(content)) as package:
        return package.read("word/footer1.xml").decode()


def is_rejected(content: bytes) -> bool:
    try:
        reject_active_content(content)
    except ConversionError as error:
        return error.code == ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT
    return False


@pytest.mark.parametrize(
    "field",
    [
        complex_field(INCLUDE),
        complex_field(INCLUDE, split=True),
        complex_field(f"INCLUDEPICTURE {URL}"),
        complex_field(f'includepicture "{URL}" \\* MERGEFORMATINET'),
        f'<w:fldSimple w:instr="INCLUDEPICTURE &quot;{URL}&quot;">{RESULT}</w:fldSimple>',
    ],
)
def test_http_includepicture_is_neutralized_but_result_is_kept(field: str) -> None:
    original = package_with_footer(field)
    assert is_rejected(original)

    working = neutralize_picture_fields(original)

    assert not is_rejected(working)
    footer = footer_of(working)
    assert "instr" not in footer.lower()
    assert "fldChar" not in footer
    assert RESULT in footer


def test_pagination_fields_survive_beside_neutralized_picture_field() -> None:
    page = '<w:fldSimple w:instr="PAGE"/>'
    working = neutralize_picture_fields(package_with_footer(complex_field(INCLUDE) + page))

    assert not is_rejected(working)
    assert page in footer_of(working)


@pytest.mark.parametrize(
    "field",
    [
        complex_field('INCLUDEPICTURE "file:///etc/passwd"'),
        complex_field('INCLUDEPICTURE "C:\\\\x\\\\a.png"'),
        complex_field('INCLUDEPICTURE "pic.png"'),
        complex_field(f'INCLUDEPICTURE "{URL}" \\d'),
        complex_field(f'INCLUDEPICTURE "{URL}" \\c gif'),
        complex_field(f'INCLUDEPICTURE "{URL}"\\x'),
        complex_field('INCLUDETEXT "https://example.invalid/a.docx"'),
        complex_field('HYPERLINK "https://example.invalid/"'),
        complex_field(INCLUDE, result=""),
        complex_field(INCLUDE, result="<w:r><w:tab/></w:r>"),
        '<w:fldSimple w:instr="INCLUDEPICTURE &quot;file:///a.png&quot;"><w:r><w:drawing/></w:r></w:fldSimple>',
        f'<w:fldSimple w:instr="INCLUDEPICTURE &quot;{URL}&quot;"/>',
        complex_field(INCLUDE) + complex_field("DATE"),
        complex_field(INCLUDE, result=complex_field("PAGE")),
        '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText>' + INCLUDE + "</w:instrText></w:r>",
        (
            f'<w:fldSimple w:instr="INCLUDEPICTURE &quot;{URL}&quot;">'
            '<w:fldSimple w:instr="PAGE"/></w:fldSimple>'
        ),
    ],
)
def test_other_or_unneutralizable_fields_still_rejected(field: str) -> None:
    working = neutralize_picture_fields(package_with_footer(field))

    assert is_rejected(working)


def test_package_without_picture_fields_is_returned_unchanged() -> None:
    original = package_with_footer('<w:fldSimple w:instr="PAGE"/>')

    assert neutralize_picture_fields(original) is original


def test_non_zip_bytes_are_returned_unchanged() -> None:
    assert neutralize_picture_fields(b"not a zip") == b"not a zip"
