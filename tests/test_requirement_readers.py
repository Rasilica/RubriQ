import json

import pytest
from docx_reader_helpers import FIXTURE as DOCX_FIXTURE
from docx_reader_helpers import make_docx
from hwpx_reader_helpers import FIXTURE as HWPX_FIXTURE
from hwpx_reader_helpers import make_hwpx
from requirement_helpers import single_response

from submission.document_contracts import CommonDocument
from submission.docx_reader import read_docx
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.requirement_adapter import build_requirement_draft
from submission.requirement_contracts import RequirementError, RequirementErrorCode


def test_docx_reader_citation_keeps_xml_location_and_unknown_page() -> None:
    source = DocumentInput(DOCX_FIXTURE.name, DOCX_FIXTURE.read_bytes(), DocumentRole.GUIDE)
    document = read_docx(source)

    draft = build_requirement_draft(document, single_response(document, "표 첫째 셀"))

    cite = draft.requirements[0].citations[0]
    assert cite.source_locator.original_page_number is None
    assert "/w:tc[1]/w:p[1]" in cite.source_locator.path
    assert cite.source_locator.source_sha256 == document.source.content_sha256
    assert cite.quote == "표 첫째 셀"
    assert draft.coverage == document.coverage


def hwpx_fragment_document() -> CommonDocument:
    xml = (HWPX_FIXTURE.parent / "cases/hwpx-structure.xml").read_text()
    content = make_hwpx("", (("Contents/section1.xml", xml),))
    return read_hwpx(DocumentInput("guide.hwpx", content, DocumentRole.GUIDE))


def test_hwpx_fragment_citation_uses_local_not_canonical_offsets() -> None:
    document = hwpx_fragment_document()
    target = next(block for block in document.blocks if block.raw_text == "표 뒤")
    assert target.raw_char_range.start > 0

    draft = build_requirement_draft(document, single_response(document, "표 뒤"))

    cite = draft.requirements[0].citations[0]
    assert cite.char_range.start == 0
    assert cite.char_range.end == 3
    assert ":fragment:" in cite.block_id
    assert cite.source_locator == target.source_locator
    assert cite.source_locator.original_page_number is None


def test_hwpx_canonical_offset_is_rejected_for_fragment_citation() -> None:
    document = hwpx_fragment_document()
    target = next(block for block in document.blocks if block.raw_text == "표 뒤")
    payload = json.loads(single_response(document, "표 뒤"))
    payload["requirements"][0]["citations"][0]["char_range"] = {
        "start": target.raw_char_range.start,
        "end": target.raw_char_range.end,
    }

    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(document, json.dumps(payload))

    assert caught.value.code is RequirementErrorCode.INVALID_CITATION


def test_unicode_and_whitespace_citations_preserve_exact_hwp_projection() -> None:
    document = hwpx_fragment_document()

    draft = build_requirement_draft(document, single_response(document, "😀 \t뒤\n"))

    cite = draft.requirements[0].citations[0]
    assert cite.quote == "😀 \t뒤\n"
    assert cite.char_range.end - cite.char_range.start == 5


def test_repeated_combining_quote_stays_bound_to_selected_docx_block() -> None:
    body = "<w:p><w:r><w:t>첫째 e\u0301😀</w:t></w:r></w:p>"
    body += "<w:p><w:r><w:t>둘째 e\u0301😀</w:t></w:r></w:p>"
    document = read_docx(DocumentInput("guide.docx", make_docx(body), DocumentRole.GUIDE))
    second = next(block for block in document.blocks if block.raw_text == "둘째 e\u0301😀")
    payload = json.loads(single_response(document, "e\u0301😀"))
    payload["requirements"][0]["citations"][0]["block_id"] = second.block_id

    draft = build_requirement_draft(document, json.dumps(payload))

    cite = draft.requirements[0].citations[0]
    assert cite.source_locator == second.source_locator
    assert cite.char_range.end - cite.char_range.start == 3


def test_normalized_quote_cannot_replace_original_combining_characters() -> None:
    body = "<w:p><w:r><w:t>e\u0301😀</w:t></w:r></w:p>"
    document = read_docx(DocumentInput("guide.docx", make_docx(body), DocumentRole.GUIDE))
    payload = json.loads(single_response(document, "e\u0301😀"))
    payload["requirements"][0]["citations"][0]["quote"] = "é😀"

    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(document, json.dumps(payload))

    assert caught.value.code is RequirementErrorCode.INVALID_CITATION


def test_partial_reader_diagnostics_are_preserved_in_draft() -> None:
    body = "<w:p><w:r><w:t>본문</w:t><w:unknown>미지원</w:unknown></w:r></w:p>"
    document = read_docx(DocumentInput("guide.docx", make_docx(body), DocumentRole.GUIDE))
    assert document.warnings

    draft = build_requirement_draft(document, single_response(document, "본문"))

    assert draft.source_extraction_status == "partial"
    assert draft.warnings == document.warnings
    assert draft.coverage == document.coverage
