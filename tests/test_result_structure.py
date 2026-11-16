from functools import partial
from shutil import copytree

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from submission import result_demo
from submission.main import create_app
from submission.models import DocumentRole
from submission.result_assets import SAMPLES, load_raster, report_document_id
from submission.result_contracts import ResultCase, ResultError
from submission.result_demo import common_document
from submission.result_structure import structure_document, structure_viewer
from submission.result_structure_contracts import StructuralViewerDocument


@pytest.mark.parametrize("case", ["docx_structure", "hwpx_structure"])
def test_structure_result_preserves_real_reader_coordinates_without_pages(case):
    client = TestClient(create_app())
    response = client.get(f"/api/result-demos/{case}")
    assert response.status_code == 200
    data = response.json()["data"]
    report = data["documents"]["report"]
    assert report["representation"] == "source_structure"
    assert report["artifact"] is report["page_count"] is report["original_url"] is None
    assert report["pages"] == []
    assert report["rendering_status"] == "not_started"
    assert report["page_count_assessment"]["status"] == "deferred"
    assert report["page_count_assessment"]["count"] is None
    assert {b["kind"] for b in report["blocks"]} >= {
        "paragraph",
        "table_cell",
        "footnote",
        "header",
        "footer",
    }
    assert all(b["source_locator"]["original_page_number"] is None for b in report["blocks"])
    assert all(
        b["source_locator"]["source_sha256"] == report["source"]["content_sha256"]
        for b in report["blocks"]
    )
    assert data["check"]["items"][4]["page_rule"]["status"] == "deferred"
    assert data["check"]["ai_called"] is False
    assert data["conversion_performed"] is False
    scenarios = data["structure_scenarios"]
    assert {s["result"]["mapping"]["mapping_status"] for s in scenarios} == {
        "ambiguous",
        "unmapped",
        "mismatch",
    }
    assert all(s["result"]["snapshot_origin"] == "synthetic" for s in scenarios)
    assert all(s["result"]["mapping"]["original_page_numbers"] is None for s in scenarios)
    assert report["coverage"]["guarantees_all_content"] is False
    assert client.get(f"/api/result-demos/{case}/documents/report/original.pdf").status_code == 404
    assert client.get(f"/api/result-demos/{case}/documents/report/pages/1.png").status_code == 404


@pytest.mark.parametrize("case", ["docx_structure", "hwpx_structure"])
def test_structure_citations_and_loss_are_bound_to_reader_output(case):

    source = structure_document(ResultCase(case))
    response = TestClient(create_app()).get(f"/api/result-demos/{case}")
    assert response.status_code == 200
    data = response.json()["data"]
    report = data["documents"]["report"]
    assert report["blocks"] == [block.model_dump(mode="json") for block in source.blocks]
    assert report["warnings"] == [warning.model_dump(mode="json") for warning in source.warnings]
    assert report["extraction_status"] == "partial"
    assert report["coverage"]["omitted_locators"]
    assert any(item["code"] == "unsupported_element" for item in report["warnings"])
    citations = [
        evidence["citation"] for evidence in data["check"]["items"][0]["semantic"]["evidence"]
    ]
    citations += [scenario["citation"] for scenario in data["structure_scenarios"]]
    assert citations
    for citation in citations:
        block = next(block for block in source.blocks if block.block_id == citation["block_id"])
        assert citation["source_locator"] == block.source_locator.model_dump(mode="json")
        span = citation["char_range"]
        assert block.raw_text[span["start"] : span["end"]] == citation["quote"]
        assert citation["verification"] == "exact_quote"
    assert {
        e["citation"]["block_id"] for e in data["check"]["items"][0]["semantic"]["evidence"]
    } >= {
        next(
            b.block_id
            for b in source.blocks
            if b.parent_block_id == next(p.block_id for p in source.blocks if p.kind == kind)
            and b.raw_text.strip()
        )
        for kind in ("table_cell", "footnote", "header", "footer")
    }
    assert structure_document(ResultCase(case)) == source


@pytest.mark.parametrize("case", ["docx_structure", "hwpx_structure"])
@pytest.mark.parametrize("damage", ["missing", "hash_mismatch"])
def test_structure_when_fixed_asset_missing_or_changed_returns_safe_503(
    case, damage, tmp_path, monkeypatch
):

    copytree(SAMPLES / "formats", tmp_path / "formats")
    path = (
        tmp_path / "formats" / ("boundary.docx" if case == "docx_structure" else "spine-order.hwpx")
    )
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"private-path-sentinel")
    monkeypatch.setattr(
        result_demo, "structure_document", partial(structure_document, samples=tmp_path)
    )
    client = TestClient(create_app())
    response = client.get(f"/api/result-demos/{case}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "result_demo_unavailable"
    assert "private-path-sentinel" not in response.text
    assert str(tmp_path) not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/health").status_code == 200


def test_structure_contract_is_frozen_strict_and_rejects_fake_pages():

    document = structure_viewer(structure_document(ResultCase.DOCX_STRUCTURE))
    with pytest.raises(ValidationError):
        document.original_url = "/fake.pdf"
    payload = document.model_dump()
    for change in (
        {"page_count": 1},
        {"pages": ({"page_number": 1},)},
        {"original_url": "/fake.pdf"},
        {"extra": True},
    ):
        with pytest.raises(ValidationError):
            StructuralViewerDocument.model_validate(payload | change)


def test_structure_helpers_reject_pdf_and_unknown_case():

    for operation in (
        lambda: structure_document(ResultCase.NORMAL),
        lambda: report_document_id(ResultCase.DOCX_STRUCTURE),
        lambda: structure_viewer(common_document(load_raster("normal"), DocumentRole.REPORT)),
    ):
        with pytest.raises(ResultError):
            operation()
