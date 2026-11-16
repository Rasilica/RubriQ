from hashlib import sha256
from pathlib import Path

from run_evidence_mapping_demo import run_demo


def test_real_pdf_identity_and_counts_stay_bound_to_the_submitted_bytes() -> None:
    # Given
    content = (Path(__file__).resolve().parents[1] / "samples/pdf/normal.pdf").read_bytes()
    # When
    result = run_demo()
    # Then
    assert result.pdf_source_sha256 == sha256(content).hexdigest()
    assert len(result.pdf_mappings) == 2
    for item in result.pdf_mappings:
        assert item.mapping.mapping_status == "identity"
        assert item.target_artifact_sha256 == result.pdf_source_sha256
        assert item.mapping.original_page_numbers == item.mapping.target_page_numbers
    counts = {item.case_name: item.result.assessment for item in result.counts}
    assert counts["original_all"].status == "verified"
    assert counts["original_all"].count == 2
    assert counts["original_body_only"].count == 1
    assert counts["original_body_only"].excluded_pages == (1,)
    assert counts["scope_unconfirmed"].status == "deferred"
    assert counts["scope_unconfirmed"].count is None
    assert counts["declared_pdf"].status == "verified"
    assert counts["declared_pdf"].basis == "declared_submission_pdf"
    assert counts["original_editable_layout"].status == "deferred"


def test_synthetic_page_pairs_expose_split_repetition_and_changed_content() -> None:
    # Given
    expected = {
        "unique": "verified_anchor",
        "split": "verified_anchor",
        "repeated": "ambiguous",
        "missing": "unmapped",
        "mismatch": "mismatch",
        "many_to_one_first": "verified_anchor",
        "many_to_one_second": "verified_anchor",
    }
    # When
    result = run_demo()
    # Then
    cases = {item.case_name: item.result for item in result.synthetic_mappings}
    assert {name: item.mapping.mapping_status for name, item in cases.items()} == expected
    assert cases["split"].mapping.target_page_numbers == (1, 2)
    assert len(cases["split"].mapping.target_text_ranges) == 2
    assert len(cases["repeated"].candidates) == 2
    assert cases["many_to_one_first"].mapping.target_page_numbers == (1,)
    assert cases["many_to_one_second"].mapping.target_page_numbers == (1,)
    assert (
        cases["many_to_one_first"].mapping.source_block_id
        != cases["many_to_one_second"].mapping.source_block_id
    )
    assert (
        cases["many_to_one_first"].mapping.target_text_ranges
        == cases["many_to_one_second"].mapping.target_text_ranges
    )
    for item in cases.values():
        assert item.mapping.original_page_numbers is None
        assert item.source_locator.original_page_number is None
        assert item.source_sha256 == result.docx_source_sha256
    synthetic_count = next(item for item in result.counts if item.case_name == "synthetic")
    assert synthetic_count.result.assessment.status == "deferred"
    assert synthetic_count.result.assessment.count is None
