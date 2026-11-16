import json
import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest
import test_persistence

from submission.document_contracts import ToolDescriptor
from submission.docx_reader import read_docx
from submission.evidence_contracts import ArtifactPage, SyntheticArtifactInput
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.page_rule_contracts import SubmissionCheckContext
from submission.persistence import PersistenceStore
from submission.persistence_contracts import (
    ExecutionSettings,
    OriginalPayload,
    PersistenceError,
    PersistenceErrorCode,
    PersistenceLimits,
)
from submission.result_structure_check import structure_response


@pytest.fixture
def request_data():
    return test_persistence.make_request()


@pytest.mark.parametrize(
    ("filename", "reader"), [("boundary.docx", read_docx), ("spine-order.hwpx", read_hwpx)]
)
def test_structural_document_reopens_without_invented_artifacts(
    tmp_path, request_data, filename, reader
):
    path = Path(__file__).resolve().parents[1] / "samples/formats" / filename
    content = path.read_bytes()
    document = reader(DocumentInput(filename, content, DocumentRole.REPORT))
    ctx = request_data.context.report_check.model_copy(update={"report": document})
    changed = request_data.model_copy(
        update={
            "context": SubmissionCheckContext(report_check=ctx, page_checks=()),
            "originals": (
                request_data.originals[0],
                OriginalPayload(source=document.source, content=content),
            ),
            "artifacts": request_data.artifacts[:1],
            "response_json": structure_response(ctx),
        }
    )
    database = tmp_path / "runs.db"
    with PersistenceStore(database) as store:
        run = store.execute("structural", changed)
    with PersistenceStore(database) as store:
        restored = store.get_run(run.run_id)
    assert restored == run
    assert restored.status == "succeeded"
    assert restored.request.context.report_check.report.artifacts == ()
    assert restored.request.context.report_check.report.page_count.count is None
    assert restored.request.context.report_check.report.stored is False


def test_criteria_and_settings_changes_append_distinct_versions(tmp_path, request_data):
    ctx = request_data.context.report_check
    revised = ctx.model_copy(
        update={"criteria": ctx.criteria.model_copy(update={"version": ctx.criteria.version + 1})}
    )
    changed = request_data.model_copy(
        update={
            "context": request_data.context.model_copy(update={"report_check": revised}),
            "settings": ExecutionSettings(
                toolchain=(ToolDescriptor(name="offline", version="2", options=("different",)),)
            ),
            "response_json": structure_response(revised),
        }
    )
    with PersistenceStore(tmp_path / "runs.db") as store:
        first = store.execute("versions", request_data)
        second = store.execute("versions", changed)
        assert first.run_id != second.run_id
        assert store.get_run(first.run_id).request == request_data
        assert store.get_run(second.run_id).request == changed
        assert second.result.semantic.criteria_version == revised.criteria.version


def test_synthetic_target_retains_explicit_unverified_origin(tmp_path, request_data):
    check = request_data.context.page_checks[0]
    target = SyntheticArtifactInput(
        binding=check.target.binding, pages=(ArtifactPage(number=1, text="synthetic"),)
    )
    changed = request_data.model_copy(
        update={
            "context": request_data.context.model_copy(
                update={
                    "page_checks": (check.model_copy(update={"target": target, "selection": None}),)
                }
            )
        }
    )
    with PersistenceStore(tmp_path / "runs.db") as store:
        run = store.execute("synthetic", changed)
        assert store.get_run(run.run_id).request.context.page_checks[0].target == target


@pytest.mark.parametrize("field", ["settings", "options"])
def test_unbounded_execution_settings_are_rejected(tmp_path, request_data, field):
    if field == "settings":
        settings = request_data.settings.model_copy(
            update={
                "check_limits": request_data.settings.check_limits.model_copy(
                    update={"max_total_target_bytes": 10**15}
                )
            }
        )
    else:
        settings = ExecutionSettings(
            toolchain=(ToolDescriptor(name="x", version="1", options=("x",) * 101),)
        )
    with PersistenceStore(tmp_path / "runs.db") as store:
        with pytest.raises(PersistenceError) as error:
            store.execute("project", request_data.model_copy(update={"settings": settings}))
        assert error.value.code == PersistenceErrorCode.INPUT_LIMIT


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("schema_version", "2", PersistenceErrorCode.UNSUPPORTED_SCHEMA),
        ("result_source", "wrong", PersistenceErrorCode.CORRUPT_STORE),
        ("page_fingerprint", "0" * 64, PersistenceErrorCode.CORRUPT_STORE),
        ("missing_page", None, PersistenceErrorCode.CORRUPT_STORE),
        ("durable", False, PersistenceErrorCode.CORRUPT_STORE),
        ("status", "failed", PersistenceErrorCode.CORRUPT_STORE),
    ],
)
def test_rehashed_invalid_manifest_is_rejected(tmp_path, request_data, field, value, expected):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        run = store.execute("project", request_data)
        with closing(sqlite3.connect(path)) as connection, connection:
            raw = json.loads(connection.execute("SELECT manifest FROM runs").fetchone()[0])
            if field == "result_source":
                raw["result"]["semantic"]["report_source_id"] = value
            elif field == "page_fingerprint":
                raw["result"]["items"][4]["page_rule"]["rule"]["criterion_sha256"] = value
            elif field == "missing_page":
                raw["result"]["items"][4]["page_rule"] = value
            else:
                raw[field] = value
            manifest = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "UPDATE runs SET manifest=?, manifest_sha256=?",
                (manifest, sha256(manifest.encode()).hexdigest()),
            )
        with pytest.raises(PersistenceError) as error:
            store.get_run(run.run_id)
        assert error.value.code == expected


def test_keyboard_interrupt_rolls_back_pending_insert(tmp_path, request_data, monkeypatch):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        run = store.execute("project", request_data)

        def interrupt(connection, _manifest, _blobs):
            connection.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                ("interrupted", "project", 2, "failed", "{}", "x"),
            )
            raise KeyboardInterrupt

        monkeypatch.setattr(store, "_check_capacity", interrupt)
        with pytest.raises(KeyboardInterrupt):
            store.execute("project", request_data)
        assert store.get_run(run.run_id) == run
        assert len(store.list_runs("project")) == 1


def test_forged_limits_fail_before_opening_database(tmp_path):
    path = tmp_path / "runs.db"
    with pytest.raises(PersistenceError) as error:
        PersistenceStore(
            path, limits=PersistenceLimits().model_copy(update={"timeout_seconds": float("nan")})
        )
    assert error.value.code == PersistenceErrorCode.INVALID_INPUT
    assert not path.exists()
