from io import BytesIO
from zipfile import ZipFile

import pytest
from defusedxml import ElementTree
from docx_reader_helpers import FIXTURE, OFFICE_NS, make_docx, source
from format_fixture_models import Truth, XmlLocator

from submission.document_contracts import ProcessingStatus
from submission.docx_reader import read_docx
from submission.docx_validation import WORD_NS


def test_relationship_main_part_may_have_a_nondefault_path() -> None:
    result = BytesIO()
    with ZipFile(FIXTURE) as archive, ZipFile(result, "w") as renamed:
        for name in archive.namelist():
            renamed.writestr(
                name.replace("word/", "custom/"), archive.read(name).replace(b"word/", b"custom/")
            )
    document = read_docx(source(result.getvalue()))
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert all(block.source_locator.path.startswith("custom/") for block in document.blocks)


def test_metadata_containing_content_is_not_silently_ignored() -> None:
    xml = f'<w:styles xmlns:w="{WORD_NS}"><w:t>예상하지 못한 텍스트</w:t></w:styles>'
    document = read_docx(
        source(make_docx("<w:p><w:r><w:t>본문</w:t></w:r></w:p>", (("word/styles.xml", xml),)))
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert any(item.code == "unsupported_part" for item in document.warnings)


def test_foreign_header_relation_cannot_reuse_a_supported_header_target() -> None:
    body = "<w:p><w:r><w:t>본문</w:t></w:r></w:p><w:sectPr>"
    body += '<w:headerReference r:id="valid"/><w:headerReference r:id="foreign"/></w:sectPr>'
    header = f'<w:hdr xmlns:w="{WORD_NS}"><w:p><w:r><w:t>머리말</w:t></w:r></w:p></w:hdr>'
    relations = f'<Relationship Id="valid" Type="{OFFICE_NS}/header" Target="h.xml"/>'
    relations += '<Relationship Id="foreign" Type="urn:foreign/header" Target="h.xml"/>'
    document = read_docx(source(make_docx(body, (("word/h.xml", header),), relations)))
    assert [item.status for item in document.references] == ["resolved", "unresolved"]
    assert document.extraction_status is ProcessingStatus.PARTIAL


def test_authored_truth_and_each_text_span_match_original_xml_nodes() -> None:
    truth = Truth.model_validate_json((FIXTURE.parent / "truth.json").read_bytes())
    expected = next(item for item in truth.documents if item.id == "docx-boundary")
    document = read_docx(source(FIXTURE.read_bytes()))
    assert document.source.content_sha256 == expected.sha256
    observed: tuple[str, ...] = ()
    with ZipFile(FIXTURE) as archive:
        for block in document.blocks:
            for span in block.source_spans:
                part, path = span.source_locator.path.split("::", 1)
                root = ElementTree.fromstring(archive.read(part))
                relative = path.split("/", 2)[2]
                nodes = root.findall("./" + relative, truth.namespaces)
                assert len(nodes) == 1
                assert nodes[0].text is not None
                raw = nodes[0].text[span.source_char_range.start : span.source_char_range.end]
                assert (
                    raw == block.raw_text[span.block_char_range.start : span.block_char_range.end]
                )
                observed += (raw,)
        assert len(observed) == len(expected.cases) == 7
        for case in expected.cases:
            assert isinstance(case.locator, XmlLocator)
            root = ElementTree.fromstring(archive.read(case.locator.member))
            relative = case.locator.path.split("/", 2)[2]
            node = root.find("./" + relative, truth.namespaces)
            assert node is not None
            assert node.text == case.expected_text
            assert observed.count(case.expected_text) == 1


@pytest.mark.parametrize("identity", ["bad", "1_0", "-3"])
def test_invalid_normal_note_ids_cannot_be_reported_as_complete(identity: str) -> None:
    body = f'<w:p><w:r><w:t>본문</w:t><w:footnoteReference w:id="{identity}"/></w:r></w:p>'
    notes = f'<w:footnotes xmlns:w="{WORD_NS}"><w:footnote w:id="{identity}">'
    notes += "<w:p><w:r><w:t>각주</w:t></w:r></w:p></w:footnote></w:footnotes>"
    rel = f'<Relationship Id="n" Type="{OFFICE_NS}/footnotes" Target="notes.xml"/>'
    document = read_docx(source(make_docx(body, (("word/notes.xml", notes),), rel)))
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.references[0].status == "unresolved"
    assert any(item.code == "invalid_structure" for item in document.warnings)


def test_reserved_note_text_is_an_explicit_omission() -> None:
    notes = f'<w:footnotes xmlns:w="{WORD_NS}"><w:footnote w:type="separator" w:id="-1">'
    notes += "<w:p><w:r><w:t>기본 구분선 외의 내용</w:t></w:r></w:p></w:footnote></w:footnotes>"
    rel = f'<Relationship Id="n" Type="{OFFICE_NS}/footnotes" Target="notes.xml"/>'
    document = read_docx(
        source(
            make_docx("<w:p><w:r><w:t>본문</w:t></w:r></w:p>", (("word/notes.xml", notes),), rel)
        )
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert any(item.code == "invalid_structure" for item in document.warnings)


def test_related_note_xml_is_read_regardless_of_filename_extension() -> None:
    body = '<w:p><w:r><w:t>본문</w:t><w:footnoteReference w:id="1"/></w:r></w:p>'
    notes = f'<w:footnotes xmlns:w="{WORD_NS}"><w:footnote w:id="1">'
    notes += "<w:p><w:r><w:t>각주</w:t></w:r></w:p></w:footnote></w:footnotes>"
    rel = f'<Relationship Id="n" Type="{OFFICE_NS}/footnotes" Target="notes.part"/>'
    document = read_docx(source(make_docx(body, (("word/notes.part", notes),), rel)))
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert "word/notes.part" in document.coverage.processed_parts
    assert document.references[0].status == "resolved"


def test_notes_follow_first_reference_order_and_orphans_are_omitted_explicitly() -> None:
    body = '<w:p><w:r><w:t>본문</w:t><w:footnoteReference w:id="1"/>'
    body += '<w:footnoteReference w:id="2"/><w:footnoteReference w:id="1"/></w:r></w:p>'
    notes = f'<w:footnotes xmlns:w="{WORD_NS}">'
    notes += "".join(
        f'<w:footnote w:id="{key}"><w:p><w:r><w:t>각주{key}</w:t></w:r></w:p></w:footnote>'
        for key in (2, 1, 3)
    )
    notes += "</w:footnotes>"
    rel = f'<Relationship Id="n" Type="{OFFICE_NS}/footnotes" Target="notes.xml"/>'
    document = read_docx(source(make_docx(body, (("word/notes.xml", notes),), rel)))
    assert [block.raw_text for block in document.blocks if block.raw_text] == [
        "본문",
        "각주1",
        "각주2",
    ]
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert all(reference.status == "resolved" for reference in document.references)
    assert any(item.path.endswith("/w:footnote[3]") for item in document.coverage.omitted_locators)


@pytest.mark.parametrize("replacement", ["RAW<w:body>", "</w:body>TAIL"])
def test_raw_text_outside_document_body_is_not_silent(replacement: str) -> None:
    content = make_docx("<w:p><w:r><w:t>본문</w:t></w:r></w:p>")
    output = BytesIO()
    with ZipFile(BytesIO(content)) as archive, ZipFile(output, "w") as package:
        for path in archive.namelist():
            data = archive.read(path)
            if path == "word/document.xml":
                needle = b"<w:body>" if replacement.startswith("RAW") else b"</w:body>"
                data = data.replace(needle, replacement.encode())
            package.writestr(path, data)
    document = read_docx(source(output.getvalue()))
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert any(item.code == "invalid_structure" for item in document.warnings)
