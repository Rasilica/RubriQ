from hashlib import sha256

import pytest
from docx_reader_helpers import FIXTURE, OFFICE_NS, make_docx, source

from submission.document_contracts import CommonDocument, ProcessingStatus, StructuralCoverage
from submission.docx_reader import read_docx
from submission.docx_validation import WORD_NS
from submission.input_contracts import InputErrorCode, InputLimits, InputValidationError
from submission.models import DocumentRole


def test_fixture_structure_locations_references_and_deferred_pages() -> None:
    content = FIXTURE.read_bytes()
    document = read_docx(source(content))
    assert document.source.filename == "report.docx"
    assert document.source.content_sha256 == sha256(content).hexdigest()
    assert [block.raw_text for block in document.blocks if block.raw_text] == [
        "합성 DOCX 본문 위치 확인 문장.",
        "표 첫째 셀",
        "표 둘째 셀",
        "표 뒤의 본문 문장.",
        "합성 각주 위치 확인 문장.",
        "합성 머리말",
        "합성 꼬리말",
    ]
    assert len(document.blocks) == 12
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert document.warnings == document.typed_errors == ()
    assert isinstance(document.coverage, StructuralCoverage)
    assert set(document.coverage.processed_parts) == {
        "word/document.xml",
        "word/footnotes.xml",
        "word/header1.xml",
        "word/footer1.xml",
    }
    assert not document.coverage.guarantees_all_content
    assert document.coverage.omitted_locators == ()
    assert [block.reading_order for block in document.blocks] == list(range(12))
    assert all(block.source_locator.original_page_number is None for block in document.blocks)
    assert {item.kind for item in document.references} == {"footnote", "header", "footer"}
    assert all(item.status == "resolved" and item.target_locator for item in document.references)
    note = next(item for item in document.references if item.kind == "footnote")
    assert note.source_char_offset == len(document.blocks[0].raw_text)
    assert note.source_block_id == document.blocks[0].block_id
    assert note.target_locator is not None
    assert note.target_locator.path.endswith("/w:footnote[3]")
    for block in document.blocks:
        for span in block.source_spans:
            assert span.source_locator.source_sha256 == document.source.content_sha256
            assert span.block_char_range.end <= len(block.raw_text)
    assert document.artifacts == document.mappings == ()
    assert document.rendering_status is ProcessingStatus.NOT_STARTED
    assert document.page_count.basis == "unknown"
    assert document.page_count.status == "deferred"
    assert document.page_count.count is document.page_count.artifact_page_count is None
    assert document.content_review_available
    assert not any(
        (
            document.ai_called,
            document.stored,
            document.display_artifact_available,
            document.page_count_verification_available,
        )
    )
    assert CommonDocument.model_validate_json(document.model_dump_json(round_trip=True)) == document


def test_repeated_footnote_reference_is_many_to_one_with_exact_offsets() -> None:
    body = '<w:p><w:r><w:t>앞😀</w:t><w:footnoteReference w:id="9"/><w:t>뒤</w:t>'
    body += '<w:footnoteReference w:id="9"/></w:r></w:p>'
    notes = f'<w:footnotes xmlns:w="{WORD_NS}"><w:footnote w:id="9">'
    notes += "<w:p><w:r><w:t>주석</w:t></w:r></w:p></w:footnote></w:footnotes>"
    rel = f'<Relationship Id="n" Type="{OFFICE_NS}/footnotes" Target="notes.xml"/>'
    document = read_docx(source(make_docx(body, (("word/notes.xml", notes),), rel)))
    assert [item.source_char_offset for item in document.references] == [2, 3]
    assert document.references[0].target_locator == document.references[1].target_locator
    assert document.extraction_status is ProcessingStatus.COMPLETE


@pytest.mark.parametrize(
    "reference",
    [
        '<w:r><w:footnoteReference w:id="99"/></w:r>',
        '<w:pPr><w:sectPr><w:headerReference r:id="absent"/></w:sectPr></w:pPr>',
    ],
)
def test_missing_reference_retains_readable_text_and_reports_source(reference: str) -> None:
    document = read_docx(source(make_docx(f"<w:p>{reference}<w:r><w:t>본문</w:t></w:r></w:p>")))
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.references[0].status == "unresolved"
    assert document.references[0].target_locator is None
    diagnostic = next(item for item in document.warnings if item.code == "invalid_reference")
    assert diagnostic.source_locator == document.references[0].source_locator
    assert diagnostic.source_locator in document.coverage.omitted_locators
    assert document.content_review_available


@pytest.mark.parametrize(
    "notes",
    [
        '<w:footnote w:id="1"><w:p/></w:footnote><w:footnote w:id="1"><w:p/></w:footnote>',
        "<w:footnote><w:p/></w:footnote>",
    ],
)
def test_invalid_note_identity_is_not_arbitrarily_resolved(notes: str) -> None:
    body = '<w:p><w:r><w:t>본문</w:t><w:footnoteReference w:id="1"/></w:r></w:p>'
    xml = f'<w:footnotes xmlns:w="{WORD_NS}">{notes}</w:footnotes>'
    rel = f'<Relationship Id="n" Type="{OFFICE_NS}/footnotes" Target="notes.xml"/>'
    document = read_docx(source(make_docx(body, (("word/notes.xml", xml),), rel)))
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.references[0].status == "unresolved"
    assert "invalid_structure" in {item.code for item in document.warnings}


@pytest.mark.parametrize(
    "relations",
    [
        '<Relationship Id="h" Type="{ns}/footer" Target="header.xml"/>',
        '<Relationship Id="h" Type="{ns}/header" TargetMode="External" Target="https://example.invalid/h"/>',
    ],
)
def test_wrong_or_external_header_target_is_not_resolved(relations: str) -> None:
    body = '<w:p><w:r><w:t>본문</w:t></w:r></w:p><w:sectPr><w:headerReference r:id="h"/></w:sectPr>'
    header = f'<w:hdr xmlns:w="{WORD_NS}"><w:p><w:r><w:t>머리말</w:t></w:r></w:p></w:hdr>'
    document = read_docx(
        source(make_docx(body, (("word/header.xml", header),), relations.format(ns=OFFICE_NS)))
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.references[0].status == "unresolved"


def test_repeated_header_is_read_once_and_linked_from_each_section() -> None:
    body = '<w:p><w:pPr><w:sectPr><w:headerReference r:id="h"/></w:sectPr></w:pPr>'
    body += '<w:r><w:t>본문</w:t></w:r></w:p><w:sectPr><w:headerReference r:id="h"/></w:sectPr>'
    header = f'<w:hdr xmlns:w="{WORD_NS}"><w:p><w:r><w:t>머리말</w:t></w:r></w:p></w:hdr>'
    rel = f'<Relationship Id="h" Type="{OFFICE_NS}/header" Target="header.xml"/>'
    document = read_docx(source(make_docx(body, (("word/header.xml", header),), rel)))
    assert [block.raw_text for block in document.blocks].count("머리말") == 1
    assert len(document.references) == 2
    assert document.references[0].target_locator == document.references[1].target_locator
    assert document.extraction_status is ProcessingStatus.COMPLETE


@pytest.mark.parametrize(
    "extra",
    [
        (
            f'<w:endnotes xmlns:w="{WORD_NS}"><w:endnote w:id="1"><w:p><w:r><w:t>끝주</w:t>'
            "</w:r></w:p></w:endnote></w:endnotes>"
        ),
        f'<w:hdr xmlns:w="{WORD_NS}"><w:p><w:r><w:t>미연결 머리말</w:t></w:r></w:p></w:hdr>',
    ],
)
def test_unprocessed_content_part_is_explicitly_partial(extra: str) -> None:
    document = read_docx(
        source(make_docx("<w:p><w:r><w:t>본문</w:t></w:r></w:p>", (("word/extra.xml", extra),)))
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert "unsupported_part" in {item.code for item in document.warnings}
    assert any(
        item.path.startswith("word/extra.xml::") for item in document.coverage.omitted_locators
    )


def test_empty_content_is_failed_even_with_empty_paragraphs() -> None:
    document = read_docx(source(make_docx("<w:p/>")))
    assert document.extraction_status is ProcessingStatus.FAILED
    assert not document.content_review_available
    assert document.typed_errors[0].code == "empty_content"


def test_source_role_and_identity_are_preserved_and_deterministic() -> None:
    content = FIXTURE.read_bytes()
    report = read_docx(source(content))
    assert report == read_docx(source(content))
    guide = read_docx(source(content, DocumentRole.GUIDE))
    assert guide.source.role is DocumentRole.GUIDE
    assert guide.source.content_sha256 == report.source.content_sha256
    assert guide.source.source_id != report.source.source_id
    assert {item.block_id for item in guide.blocks}.isdisjoint(
        item.block_id for item in report.blocks
    )


def test_reader_freshly_validates_input_and_honors_limits() -> None:
    with pytest.raises(InputValidationError) as caught:
        read_docx(source(FIXTURE.read_bytes()), InputLimits(max_xml_bytes=4))
    assert caught.value.code is InputErrorCode.XML_LIMIT
    with pytest.raises(InputValidationError):
        read_docx(source(b"not a docx"))
