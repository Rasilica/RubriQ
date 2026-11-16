from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic

import pytest
from reportlab.pdfgen.canvas import Canvas
from run_compatibility import execute, main

from submission import compatibility_runner, evidence_artifacts
from submission.compatibility_contracts import (
    CompatibilityCase,
    CompatibilityError,
    CompatibilityManifest,
    ExpectedAnchor,
    LayoutReview,
    MaterialFile,
)
from submission.compatibility_io import read_bounded
from submission.compatibility_runner import run_manifest
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.pair_contracts import PairRuntime
from submission.pair_prepare import prepare_role


def make_case(tmp_path: Path, text_pdf: bytes) -> CompatibilityCase:
    source = tmp_path / "source.pdf"
    source.write_bytes(text_pdf)
    return CompatibilityCase(
        case_id="sample",
        family_id="family",
        split="development",
        provenance="synthetic",
        format="pdf",
        authoring_app="test",
        authoring_version="1",
        fonts=("Helvetica",),
        source=MaterialFile(path=source, sha256=sha256(text_pdf).hexdigest()),
        reference=None,
        anchors=(ExpectedAnchor(quote="Purpose: help students check requirements."),),
    )


def test_missing_reference_is_material_missing(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].status == "material_missing"
    assert report.cases[0].preview_pages == 2
    assert (tmp_path / "out/index.html").is_file()


def test_hash_mismatch_is_invalid_without_raw_paths(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    assert case.source is not None
    case.source.path.write_bytes(b"changed")
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].error == "hash_mismatch"
    assert str(tmp_path) not in report.model_dump_json()


def test_independent_reference_gives_pending_review(tmp_path, text_pdf, blank_pdf):
    reference = tmp_path / "ref.pdf"
    reference.write_bytes(blank_pdf)
    case = make_case(tmp_path, text_pdf).model_copy(
        update={
            "reference": MaterialFile(path=reference, sha256=sha256(blank_pdf).hexdigest()),
        }
    )
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].status == "review_pending"
    assert report.cases[0].anchors[0].reference_pages == ()
    assert report.cases[0].anchors[0].preview_pages == (1,)
    assert report.cases[0].actual_acceptance is False


def test_symlink_source_is_invalid(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    assert case.source is not None
    alias = tmp_path / "alias.pdf"
    alias.symlink_to(case.source.path)
    source = MaterialFile(path=alias, sha256=case.source.sha256)
    report = run_manifest(
        CompatibilityManifest(cases=(case.model_copy(update={"source": source}),)),
        PairRuntime(),
        tmp_path / "out",
    )
    assert report.cases[0].error == "input_io"


def test_output_never_overwritten(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    with pytest.raises(FileExistsError):
        run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path)


def test_service_preview_reference_is_rejected(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    case = case.model_copy(update={"reference": case.source, "reference_origin": "service_preview"})
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].error == "reference_not_independent"


def test_missing_source_is_reported(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf).model_copy(update={"source": None})
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].status == "material_missing"


def test_wrong_location_and_missing_quote_are_not_matches(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf).model_copy(
        update={
            "anchors": (
                ExpectedAnchor(quote="Purpose", locator_path="wrong"),
                ExpectedAnchor(quote="missing"),
            )
        }
    )
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert [anchor.source_matches for anchor in report.cases[0].anchors] == [0, 0]
    assert report.cases[0].anchors[1].preview_pages == ()


def test_stale_review_rejected(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    case = case.model_copy(
        update={
            "reference": case.source,
            "layout_review": LayoutReview(
                reviewer="tester",
                source_sha256="0" * 64,
                reference_sha256="0" * 64,
                preview_sha256="0" * 64,
                outcome="matches",
                notes="test",
            ),
        }
    )
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].error == "stale_layout_review"


def test_bound_review_recorded_without_certifying(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    digest = sha256(text_pdf).hexdigest()
    case = case.model_copy(
        update={
            "reference": case.source,
            "layout_review": LayoutReview(
                reviewer="tester",
                source_sha256=digest,
                reference_sha256=digest,
                preview_sha256=digest,
                outcome="differences",
                notes="test",
            ),
        }
    )
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].status == "review_recorded"
    assert report.support_certified is False


def test_family_cannot_leak_between_development_and_evaluation(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    with pytest.raises(CompatibilityError, match="family_split_leakage"):
        CompatibilityManifest(
            cases=(case, case.model_copy(update={"case_id": "b", "split": "evaluation"}))
        )


def test_duplicate_id_rejected(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    with pytest.raises(CompatibilityError, match="duplicate_case"):
        CompatibilityManifest(cases=(case, case))


def test_report_escapes_markup(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf).model_copy(
        update={"authoring_app": "<script>alert(1)</script>"}
    )
    _ = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    html = (tmp_path / "out/index.html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_large_input_and_directory_rejected(tmp_path, text_pdf):
    case = make_case(tmp_path, text_pdf)
    assert case.source is not None
    with pytest.raises(CompatibilityError, match="input_limit"):
        read_bounded(case.source.path, 1)
    with pytest.raises(CompatibilityError, match="input_io"):
        read_bounded(tmp_path)


def test_ancestor_symlink_rejected(tmp_path, text_pdf):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "source.pdf").write_bytes(text_pdf)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(CompatibilityError, match="input_io"):
        read_bounded(alias / "source.pdf")


def test_repeated_anchor_uses_one_snapshot_parse(tmp_path, monkeypatch):
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for _ in range(2):
        canvas.drawString(72, 720, "Repeated phrase")
        canvas.showPage()
    canvas.save()
    case = make_case(tmp_path, buffer.getvalue()).model_copy(
        update={
            "anchors": (ExpectedAnchor(quote="Repeated phrase"),) * 100,
        }
    )
    calls = []
    original = evidence_artifacts.extract_pdf

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence_artifacts, "extract_pdf", counted)
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert len(calls) == 1
    assert all(
        anchor.mapping_reasons == ("source_ambiguous",) for anchor in report.cases[0].anchors
    )
    assert report.cases[0].anchors[0].preview_pages == (1, 2)


def test_conversion_failure_preserves_structure(tmp_path):
    path = Path(__file__).parents[1] / "samples/formats/boundary.docx"
    case = make_case(tmp_path, path.read_bytes()).model_copy(update={"format": "docx"})
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].extraction_status in {"complete", "partial"}
    assert report.cases[0].rendering_status == "failed"
    assert report.cases[0].status == "material_missing"


def test_deadline_checked_after_preparation(tmp_path, text_pdf, monkeypatch):
    case = make_case(tmp_path, text_pdf)
    monkeypatch.setattr(compatibility_runner, "monotonic", lambda: -1000.0)
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].status == "invalid"
    assert report.cases[0].error == "preparation_timeout"


def test_cli_runs_relative_manifest_paths(tmp_path, text_pdf, capsys):
    case = make_case(tmp_path, text_pdf)
    assert case.source is not None
    source = case.source.model_copy(update={"path": Path("source.pdf")})
    manifest = CompatibilityManifest(cases=(case.model_copy(update={"source": source}),))
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json())
    assert execute((str(path), str(tmp_path / "out"))) == 0
    assert '"material_missing"' in capsys.readouterr().out


def test_cli_usage_is_typed(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_compatibility"])
    assert main() == 2
    assert "MANIFEST OUTPUT" in capsys.readouterr().err


def test_cli_invalid_manifest_does_not_echo_raw_input(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    path.write_text('{"private":"secret"}')
    monkeypatch.setattr("sys.argv", ["run_compatibility", str(path), str(tmp_path / "out")])
    assert main() == 2
    assert capsys.readouterr().err == "invalid_manifest_or_runtime\n"


def test_identical_conversion_reference_is_rejected(tmp_path, text_pdf, monkeypatch):
    case = make_case(tmp_path, text_pdf)
    case = case.model_copy(update={"reference": case.source, "format": "docx"})
    preview = prepare_role(
        DocumentInput("test.pdf", text_pdf, DocumentRole.REPORT), PairRuntime(), monotonic() + 10
    )
    monkeypatch.setattr(compatibility_runner, "prepare_role", lambda *_: preview)
    report = run_manifest(CompatibilityManifest(cases=(case,)), PairRuntime(), tmp_path / "out")
    assert report.cases[0].error == "reference_not_independent"


def test_cli_runtime_and_invalid_exit(tmp_path, text_pdf, monkeypatch, capsys):
    case = make_case(tmp_path, text_pdf)
    assert case.source is not None
    case.source.path.write_bytes(b"changed")
    path = tmp_path / "manifest.json"
    path.write_text(CompatibilityManifest(cases=(case,)).model_dump_json())
    runtime = tmp_path / "runtime.json"
    runtime.write_text(PairRuntime().model_dump_json())
    arguments = ["run_compatibility", str(path), str(tmp_path / "out"), str(runtime)]
    monkeypatch.setattr("sys.argv", arguments)
    assert main() == 1
    assert '"hash_mismatch"' in capsys.readouterr().out


def test_cli_existing_output_keeps_file(tmp_path, text_pdf, monkeypatch, capsys):
    case = make_case(tmp_path, text_pdf)
    path = tmp_path / "manifest.json"
    path.write_text(CompatibilityManifest(cases=(case,)).model_dump_json())
    monkeypatch.setattr("sys.argv", ["run_compatibility", str(path), str(tmp_path)])
    assert main() == 2
    assert capsys.readouterr().err == "output_io\n"
    assert path.exists()
