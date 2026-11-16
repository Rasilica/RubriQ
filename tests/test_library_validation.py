from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest
from hwpx_reader_helpers import FIXTURE

from submission.document_contracts import ProcessingStatus
from submission.hwp_reader import read_hwp
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import DocumentInput
from submission.library_contracts import LibraryError
from submission.library_validation import binary_identity, environment, validate_role
from submission.models import DocumentRole
from submission.pair_contracts import PairRuntime, PreparedRole, RoleView
from submission.pair_prepare import prepare_role
from submission.pair_process import restored_role, timeout_role
from tests.test_hwp_reader import config_for, payload, result_body, source_input
from tests.test_pair_preparation import runtime_for


def test_runtime_provenance_identifies_changed_binary(tmp_path: Path, text_pdf: bytes) -> None:
    runtime = runtime_for(tmp_path, text_pdf)
    initial = environment(runtime)
    assert any(item.startswith("hwplib:") for item in initial)
    assert any(item.startswith("hancom-profile:") for item in initial)
    assert all(str(tmp_path) not in value for value in initial)
    assert runtime.docx is not None
    _ = runtime.docx.soffice.write_bytes(b"changed")
    assert environment(runtime) != initial
    assert binary_identity(tmp_path / "missing") == "identity-unavailable"


def test_hwpx_and_hwp_structure_validation(tmp_path: Path) -> None:
    source = source_input()
    document = read_hwp(source, config_for(tmp_path, result_body(payload())))
    view = RoleView(
        role=DocumentRole.REPORT,
        document=document,
        extraction_status=document.extraction_status,
        rendering_status=document.rendering_status,
    )
    validate_role(PreparedRole(view, source.content), DocumentRole.REPORT)
    content = FIXTURE.read_bytes()
    document = read_hwpx(DocumentInput("r.hwpx", content, DocumentRole.REPORT))
    view = RoleView(
        role=DocumentRole.REPORT,
        document=document,
        extraction_status=document.extraction_status,
        rendering_status=document.rendering_status,
    )
    validate_role(PreparedRole(view, content), DocumentRole.REPORT)
    bad = document.model_copy(update={"blocks": (document.blocks[0], document.blocks[0])})
    with pytest.raises(LibraryError):
        validate_role(
            PreparedRole(view.model_copy(update={"document": bad}), content), DocumentRole.REPORT
        )


def test_failed_and_invalid_roles(text_pdf: bytes) -> None:
    failed = prepare_role(
        DocumentInput("r.pdf", b"invalid", DocumentRole.REPORT), PairRuntime(), monotonic() + 10
    )
    validate_role(failed, DocumentRole.REPORT)
    good = prepare_role(
        DocumentInput("r.pdf", text_pdf, DocumentRole.REPORT), PairRuntime(), monotonic() + 10
    )
    with pytest.raises(LibraryError):
        validate_role(replace(good, pdf=b"bad"), DocumentRole.REPORT)
    document = good.view.document
    assert document is not None
    invalid = document.model_copy(
        update={"blocks": (document.blocks[0].model_copy(update={"reading_order": 55}),)}
    )
    with pytest.raises(LibraryError):
        validate_role(
            replace(good, view=good.view.model_copy(update={"document": invalid})),
            DocumentRole.REPORT,
        )


def test_failed_original_restoration_is_bounded(tmp_path: Path, text_pdf: bytes) -> None:
    source = DocumentInput("bad.pdf", b"bad", DocumentRole.REPORT)
    failed = prepare_role(source, PairRuntime(), monotonic() + 10)
    assert restored_role(tmp_path, source, failed.view).original == b"bad"
    assert timeout_role(tmp_path, source).original == b"bad"
    oversized = DocumentInput("bad.pdf", b"x" * (10 * 1024 * 1024 + 1), DocumentRole.REPORT)
    assert restored_role(tmp_path, oversized, failed.view).original == b""
    assert timeout_role(tmp_path, oversized).original == b""
    assert prepare_role(oversized, PairRuntime(), monotonic() + 10).original == b""
    good = prepare_role(
        DocumentInput("r.pdf", text_pdf, DocumentRole.REPORT), PairRuntime(), monotonic() + 10
    )
    document = good.view.document
    assert document is not None
    invalid = document.model_copy(update={"rendering_status": ProcessingStatus.FAILED})
    with pytest.raises(LibraryError):
        validate_role(
            replace(good, view=good.view.model_copy(update={"document": invalid})),
            DocumentRole.REPORT,
        )
