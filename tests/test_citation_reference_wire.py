import json

import pytest

from submission.citation_reference_wire import reference_wire
from submission.report_check_contracts import ReportCheckResponse
from submission.semantic_wire import WireDocument


def request(text="한글🙂 문구", **overrides):
    return json.dumps(
        {
            "report_source_id": "source",
            "report_source_sha256": "a" * 64,
            "expected_items": [{"requirement_id": "r0", "subcondition_ids": []}],
            "response_schema_json": json.dumps(ReportCheckResponse.model_json_schema()),
            "blocks": [{"block_id": "original/paragraph", "raw_text": text}],
            **overrides,
        }
    )


def test_reference_roundtrip_preserves_source_and_resolves_only_evidence_paths():
    raw = request()
    wire = reference_wire(raw)
    prepared = json.loads(wire.prepare(raw))
    assert prepared["blocks"][0]["citation_refs"] == [
        {"citation_ref": "q0", "char_range": {"start": 0, "end": 6}}
    ]
    assert prepared["blocks"][0]["block_id"] == "b0"
    assert prepared["blocks"][0]["raw_text"] == "한글🙂 문구"
    for key in ("report_source_id", "report_source_sha256", "expected_items"):
        assert prepared[key] == json.loads(raw)[key]
    schema = json.loads(prepared["response_schema_json"])
    assert schema["$defs"]["CitationInput"]["properties"]["citation_ref"]["enum"] == ["q0"]
    citation = {"citation_ref": "q0"}
    body = {
        "items": [
            {
                "reason": "q0",
                "evidence": [{"citation": citation}],
                "subconditions": [{"evidence": [{"citation": citation}]}],
            }
        ],
        "reviewed_block_ids": ["b0"],
        "unrelated": citation,
    }
    result = json.loads(wire.restore(json.dumps(body)))
    expected = {
        "block_id": "original/paragraph",
        "quote": "한글🙂 문구",
        "char_range": {"start": 0, "end": 6},
    }
    assert result["items"][0]["evidence"][0]["citation"] == expected
    assert result["items"][0]["subconditions"][0]["evidence"][0]["citation"] == expected
    assert result["reviewed_block_ids"] == ["original/paragraph"]
    assert result["unrelated"] == citation
    assert result["items"][0]["reason"] == "q0"


@pytest.mark.parametrize(
    "citation",
    [
        {"citation_ref": "bad"},
        {"citation_ref": "b0"},
        {"citation_ref": "q0", "quote": "invented"},
        {"citation_ref": 0},
    ],
)
def test_invalid_reference_not_repaired(citation):
    raw = request()
    result = json.loads(
        reference_wire(raw).restore(
            json.dumps(
                {"items": [{"evidence": [{"citation": citation}]}], "reviewed_block_ids": ["q0"]}
            )
        )
    )
    assert result["items"][0]["evidence"][0]["citation"] == citation
    assert result["reviewed_block_ids"] == ["q0"]


def test_long_blocks_use_bounded_contiguous_unicode_chunks_without_duplicate_text():
    text = "한🙂" * 5001
    raw = request(text)
    wire = reference_wire(raw)
    prepared = json.loads(wire.prepare(raw))
    refs = prepared["blocks"][0]["citation_refs"]
    assert len(refs) == 3
    quotes = []
    for ref in refs:
        restored = json.loads(
            wire.restore(
                json.dumps(
                    {"items": [{"evidence": [{"citation": {"citation_ref": ref["citation_ref"]}}]}]}
                )
            )
        )
        cite = restored["items"][0]["evidence"][0]["citation"]
        assert len(cite["quote"]) <= 4000
        assert cite["quote"] == text[cite["char_range"]["start"] : cite["char_range"]["end"]]
        assert set(ref) == {"citation_ref", "char_range"}
        quotes.append(cite["quote"])
    assert "".join(quotes) == text


@pytest.mark.parametrize(
    "overrides",
    [
        {"report_source_id": None},
        {"response_schema_json": "{}"},
        {"response_schema_json": "invalid"},
        {"response_schema_json": None},
    ],
)
def test_non_report_or_invalid_schema_uses_legacy_wire(overrides):
    assert isinstance(reference_wire(request(**overrides)), WireDocument)


@pytest.mark.parametrize(
    "span", [{"start": 0, "end": 0}, {"start": -2, "end": -1}, {"start": 5, "end": 1}]
)
def test_unique_exact_legacy_quote_recovers_invalid_integer_offsets(span):
    wire = WireDocument((("original", "한글 문구"),))
    cite = {"block_id": "b0", "quote": "문구", "char_range": span}
    result = json.loads(wire.restore(json.dumps(cite)))
    assert result["char_range"] == {"start": 3, "end": 5}


@pytest.mark.parametrize(
    "span",
    [{"start": False, "end": 2}, {"start": "0", "end": 2}, {"start": 0.0, "end": 2}, {"start": 0}],
)
def test_malformed_legacy_range_is_not_repaired(span):
    cite = {"block_id": "b0", "quote": "문구", "char_range": span}
    result = json.loads(WireDocument((("original", "한글 문구"),)).restore(json.dumps(cite)))
    assert result["char_range"] == span


def test_empty_blocks_have_no_selectors_and_request_references_are_deterministic():
    raw = request(
        blocks=[
            {"block_id": "empty", "raw_text": " "},
            {"block_id": "other", "raw_text": "반복 반복"},
        ]
    )
    first = reference_wire(raw)
    second = reference_wire(raw)
    assert first == second
    prepared = json.loads(first.prepare(raw))
    assert prepared["blocks"][0]["citation_refs"] == []
    assert prepared["blocks"][1]["citation_refs"][0]["citation_ref"] == "q0"
    legacy = {"block_id": "b1", "quote": "반복", "char_range": {"start": 0, "end": 0}}
    restored = json.loads(
        first.restore(json.dumps({"items": [{"evidence": [{"citation": legacy}]}]}))
    )
    assert restored["items"][0]["evidence"][0]["citation"]["char_range"] == {"start": 0, "end": 0}
