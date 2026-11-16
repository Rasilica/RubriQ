from zipfile import ZipFile

import pytest
from hwpx_reader_helpers import FIXTURE, PARA_NS, make_hwpx, section, source

from submission.document_contracts import ProcessingStatus
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import DocumentInput, InputErrorCode, InputValidationError
from submission.models import DocumentRole


@pytest.mark.parametrize("target", ["manifest", "spine"])
def test_foreign_package_reference_elements_are_rejected(target: str) -> None:
    with ZipFile(FIXTURE) as archive:
        package = archive.read("Contents/content.hpf").decode()
    old = "opf:item " if target == "manifest" else "opf:itemref "
    package = package.replace(old, 'x:item xmlns:x="urn:unknown" ', 1)
    content = make_hwpx("<hp:p/>", (("Contents/content.hpf", package),))
    with pytest.raises(InputValidationError) as caught:
        read_hwpx(source(content))
    assert caught.value.code is InputErrorCode.CORRUPT_DOCUMENT
    assert caught.value.role is DocumentRole.REPORT


def test_content_hidden_in_metadata_is_an_explicit_omission() -> None:
    with ZipFile(FIXTURE) as archive:
        head = archive.read("Contents/header.xml").decode()
    head = head.replace(
        "</hh:head>",
        f'<hp:p xmlns:hp="{PARA_NS}"><hp:run><hp:t>미처리 내용</hp:t></hp:run></hp:p></hh:head>',
    )
    document = read_hwpx(
        source(
            make_hwpx(
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>", (("Contents/header.xml", head),)
            )
        )
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert all(block.raw_text != "미처리 내용" for block in document.blocks)
    assert any(
        item.path.startswith("Contents/header.xml::") for item in document.coverage.omitted_locators
    )


@pytest.mark.parametrize(
    "hidden",
    [
        "미처리 내용",
        '<x:text xmlns:x="urn:unknown">미처리 내용</x:text>',
        "<hh:refList/>미처리 내용",
    ],
)
def test_unexpected_metadata_text_is_not_silently_ignored(hidden: str) -> None:
    head = f'<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">{hidden}</hh:head>'
    document = read_hwpx(source(make_hwpx("<hp:p/>", (("Contents/header.xml", head),))))
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert any(
        item.code == "unsupported_part"
        and item.source_locator is not None
        and item.source_locator.path == "Contents/header.xml::/hh:head[1]"
        for item in document.warnings
    )


def test_preview_cache_is_excluded_from_original_text() -> None:
    document = read_hwpx(
        source(
            make_hwpx(
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                (
                    ("Preview/PrvText.txt", "오래된 미리보기"),
                    ("Preview/PrvImage.png", "benign preview placeholder"),
                ),
            )
        )
    )
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert all("오래된" not in block.raw_text for block in document.blocks)
    assert not document.display_artifact_available


def test_section_xml_may_have_a_non_xml_filename_if_spine_resolves_it() -> None:
    with ZipFile(FIXTURE) as archive:
        package = archive.read("Contents/content.hpf").decode()
    package = package.replace("Contents/section1.xml", "Contents/body.part")
    document = read_hwpx(
        source(
            make_hwpx(
                "",
                (
                    ("Contents/content.hpf", package),
                    (
                        "Contents/body.part",
                        section("<hp:p><hp:run><hp:t>비표준 확장자 구역</hp:t></hp:run></hp:p>"),
                    ),
                ),
            )
        )
    )
    assert document.blocks[0].raw_text == "비표준 확장자 구역"
    assert document.coverage.processed_parts[0] == "Contents/body.part"
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert any(
        item.path.startswith("Contents/section1.xml::")
        for item in document.coverage.omitted_locators
    )


def test_reader_rejects_a_valid_other_format() -> None:
    docx = FIXTURE.parent / "boundary.docx"
    with pytest.raises(InputValidationError) as caught:
        read_hwpx(DocumentInput("report.docx", docx.read_bytes(), DocumentRole.REPORT))
    assert caught.value.code is InputErrorCode.UNSUPPORTED_FORMAT
    assert caught.value.detected_format == "docx"


def test_malformed_embedded_story_has_no_fabricated_target() -> None:
    body = "<hp:p><hp:run><hp:t>본문</hp:t><hp:ctrl><hp:footNote><hp:p>미지원</hp:p>"
    body += "</hp:footNote></hp:ctrl><hp:t>뒤</hp:t></hp:run></hp:p>"
    document = read_hwpx(source(make_hwpx(body)))
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.references[0].status == "unresolved"
    assert document.references[0].target_locator is None
    assert any(item.code == "invalid_structure" for item in document.warnings)


def test_hancom_script_parts_in_spine_are_not_parsed_as_sections() -> None:
    # 한컴 한글은 빈 스크립트 템플릿(UTF-16 JavaScript)을 spine에 넣어 저장한다.
    with ZipFile(FIXTURE) as archive:
        package = archive.read("Contents/content.hpf").decode()
    script_type = "application/x-javascript ;charset=utf-16"
    package = package.replace(
        "</opf:manifest>",
        f'<opf:item id="headersc" href="Scripts/headerScripts" media-type="{script_type}"/>'
        "</opf:manifest>",
    ).replace("</opf:spine>", '<opf:itemref idref="headersc" linear="yes"/></opf:spine>')
    script = "var Documents = XHwpDocuments;".encode("utf-16-le").decode("latin-1")
    content = make_hwpx(
        "<hp:p><hp:run><hp:t>한컴 저장본</hp:t></hp:run></hp:p>",
        (("Contents/content.hpf", package), ("Scripts/headerScripts", script)),
    )

    document = read_hwpx(source(content))

    assert any(block.raw_text == "한컴 저장본" for block in document.blocks)


def test_section_disguised_as_script_outside_scripts_folder_is_still_read() -> None:
    with ZipFile(FIXTURE) as archive:
        package = archive.read("Contents/content.hpf").decode()
    package = package.replace(
        'href="Contents/section1.xml" media-type="application/xml"',
        'href="Contents/section1.xml" media-type="application/x-javascript"',
    )
    content = make_hwpx(
        "<hp:p><hp:run><hp:t>숨긴 본문</hp:t></hp:run></hp:p>",
        (("Contents/content.hpf", package),),
    )

    document = read_hwpx(source(content))

    assert any(block.raw_text == "숨긴 본문" for block in document.blocks)
