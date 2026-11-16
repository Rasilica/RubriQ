import json

import pytest

from submission.semantic_wire import WireDocument


def wire():
    return WireDocument((("long/source/paragraph[2]", "한글 문구"), ("other", "반복 반복")))


def test_payload_uses_short_ids_and_authoritative_unicode_lengths():
    prepared = wire().prepare(
        json.dumps({"blocks": [{"block_id": "long/source/paragraph[2]", "raw_text": "한글 문구"}]})
    )
    block = json.loads(prepared)["blocks"][0]
    assert block == {"block_id": "b0", "raw_text": "한글 문구", "unicode_length": 5}


def test_unique_exact_quote_is_bound_to_source_even_when_model_counts_wrong():
    result = json.loads(
        wire().restore(
            json.dumps(
                {
                    "citation": {
                        "block_id": "b0",
                        "quote": "문구",
                        "char_range": {"start": 2, "end": 4},
                    },
                    "reviewed_block_ids": ["b0", "b1"],
                }
            )
        )
    )
    assert result["citation"] == {
        "block_id": "long/source/paragraph[2]",
        "quote": "문구",
        "char_range": {"start": 3, "end": 5},
    }
    assert result["reviewed_block_ids"] == ["long/source/paragraph[2]", "other"]


@pytest.mark.parametrize(
    ("quote", "block", "span"),
    [
        ("없는 문구", "b0", {"start": 0, "end": 3}),
        ("반복", "b1", {"start": 1, "end": 3}),
        ("문구", "unknown", {"start": 0, "end": 2}),
    ],
)
def test_invalid_or_ambiguous_citation_is_left_for_strict_rejection(quote, block, span):
    cite = {"block_id": block, "quote": quote, "char_range": span}
    result = json.loads(wire().restore(json.dumps(cite)))
    assert result["quote"] == quote
    assert result["char_range"] == span


def test_valid_duplicate_quote_offset_is_preserved():
    cite = {"block_id": "b1", "quote": "반복", "char_range": {"start": 3, "end": 5}}
    result = json.loads(wire().restore(json.dumps(cite)))
    assert result["char_range"] == cite["char_range"]


def test_identity_and_non_citation_data_are_not_repaired():
    data = {"source_id": "wrong", "source_sha256": "wrong", "items": [{"reason": "text"}]}
    assert json.loads(wire().restore(json.dumps(data))) == data


def test_overlapping_matches_are_ambiguous():
    document = WireDocument((("overlap", "aaa"),))
    cite = {"block_id": "b0", "quote": "aa", "char_range": {"start": 2, "end": 4}}
    result = json.loads(document.restore(json.dumps(cite)))
    assert result["char_range"] == cite["char_range"]
