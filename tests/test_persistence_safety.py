import sqlite3
import stat
from contextlib import closing

import pytest
from run_evidence_mapping_demo import synthetic_target
from test_persistence import make_request

from submission.persistence import PersistenceStore
from submission.persistence_contracts import (
    PersistenceError,
    PersistenceErrorCode,
    PersistenceLimits,
)


def test_new_database_is_owner_only_and_existing_mode_is_preserved(tmp_path):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        store.execute("project", make_request())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o640)
    with PersistenceStore(path) as store:
        assert len(store.list_runs("project")) == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_unavailable_parent_returns_safe_error(tmp_path):
    with pytest.raises(PersistenceError) as error:
        PersistenceStore(tmp_path / "absent" / "secret.db")
    assert str(error.value) == "storage_error"


@pytest.mark.parametrize("identifier", [None, 7, "\ud800"])
def test_invalid_identifier_types_and_unicode_are_safe(tmp_path, identifier):
    with PersistenceStore(tmp_path / "runs.db") as store:
        with pytest.raises(PersistenceError) as error:
            store.list_runs(identifier)
        assert error.value.code == PersistenceErrorCode.INVALID_INPUT


def test_invalid_response_unicode_is_safe(tmp_path):
    request = make_request().model_copy(update={"response_json": "\ud800"})
    with PersistenceStore(tmp_path / "runs.db") as store:
        with pytest.raises(PersistenceError) as error:
            store.execute("project", request)
        assert error.value.code == PersistenceErrorCode.INVALID_INPUT


def test_unknown_version_one_database_is_not_adopted(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version=1")
    before = path.read_bytes()
    with pytest.raises(PersistenceError) as error:
        PersistenceStore(path)
    assert error.value.code == PersistenceErrorCode.UNSUPPORTED_SCHEMA
    assert path.read_bytes() == before


def test_existing_view_only_database_is_not_adopted(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE VIEW existing AS SELECT 1")
    before = path.read_bytes()
    with pytest.raises(PersistenceError) as error:
        PersistenceStore(path)
    assert error.value.code == PersistenceErrorCode.UNSUPPORTED_SCHEMA
    assert path.read_bytes() == before


def test_changed_schema_columns_are_rejected(tmp_path):
    path = tmp_path / "runs.db"
    PersistenceStore(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("ALTER TABLE runs ADD COLUMN surprise TEXT")
    with pytest.raises(PersistenceError) as error:
        PersistenceStore(path)
    assert error.value.code == PersistenceErrorCode.UNSUPPORTED_SCHEMA


def test_malformed_sql_scalar_is_safe(tmp_path):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        run = store.execute("project", make_request())
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE runs SET sequence=?", (b"malformed",))
        with pytest.raises(PersistenceError) as error:
            store.get_run(run.run_id)
        assert error.value.code == PersistenceErrorCode.CORRUPT_STORE


def test_read_bounds_reject_oversized_history_before_loading(tmp_path):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        run = store.execute("project", make_request())
    with PersistenceStore(path, limits=PersistenceLimits(max_total_bytes=1)) as store:
        with pytest.raises(PersistenceError) as error:
            store.get_run(run.run_id)
        assert error.value.code == PersistenceErrorCode.CORRUPT_STORE


def test_synthetic_demo_does_not_require_fabricated_pdf_payload(tmp_path):
    request = make_request()
    ctx = request.context.report_check
    check = request.context.page_checks[0].model_copy(
        update={
            "target": synthetic_target(ctx.report, ("synthetic", "synthetic")),
            "selection": None,
        }
    )
    changed = request.model_copy(
        update={"context": request.context.model_copy(update={"page_checks": (check,)})}
    )
    with PersistenceStore(tmp_path / "runs.db") as store:
        run = store.execute("synthetic", changed)
        restored = store.get_run(run.run_id)
    assert restored.status == "succeeded"
    assert restored.request.context.page_checks == (check,)
    assert len(restored.request.artifacts) == 2
    assert check.target.binding.artifact.artifact_sha256 not in {
        artifact.binding.artifact.artifact_sha256 for artifact in restored.request.artifacts
    }
