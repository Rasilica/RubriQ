import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from types import TracebackType
from typing import Annotated, Final, Self
from uuid import uuid4

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from submission.page_rule_contracts import PageRuleError
from submission.persistence_codec import admitted, canonical, decode, encode
from submission.persistence_contracts import (
    PersistenceError,
    PersistenceErrorCode,
    PersistenceLimits,
    PersistenceRequest,
    RunSummary,
    StoredRun,
)
from submission.persistence_schema import (
    check_read_bounds,
    initialize_schema,
    private_database_path,
)
from submission.persistence_validation import admit_request, validate_result
from submission.submission_check import build_submission_check

type RunRow = tuple[str, str, int, str, str, str]
ROWS: Final = TypeAdapter(tuple[RunRow, ...])
BLOBS: Final = TypeAdapter(tuple[tuple[str, int, bytes], ...])
IDENTIFIER: Final = TypeAdapter[str](
    Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
)
DEFAULT_LIMITS: Final = PersistenceLimits()


class PersistenceStore:
    def __init__(self, path: Path | str, *, limits: PersistenceLimits = DEFAULT_LIMITS) -> None:
        try:
            self.limits: PersistenceLimits = admitted(limits)
        except (ValidationError, ValueError, TypeError):
            raise PersistenceError(PersistenceErrorCode.INVALID_INPUT) from None
        self.path: Path = private_database_path(Path(path))
        with self._connection(write=True) as connection, connection:
            initialize_schema(connection)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    @contextmanager
    def _connection(self, *, write: bool = False) -> Generator[sqlite3.Connection]:
        try:
            with closing(
                sqlite3.connect(self.path, timeout=self.limits.timeout_seconds)
            ) as connection:
                _ = connection.execute("PRAGMA foreign_keys=ON")
                _ = connection.execute("PRAGMA synchronous=FULL")
                _ = connection.setlimit(
                    sqlite3.SQLITE_LIMIT_LENGTH,
                    self.limits.max_total_bytes + self.limits.max_manifest_bytes,
                )
                _ = connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.STORAGE_ERROR) from None
        except (ValidationError, UnicodeError):
            raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE) from None

    def execute(self, project_id: str, request: PersistenceRequest) -> StoredRun:
        project_id = self._identifier(project_id)
        try:
            value = admit_request(request, self.limits)
        except UnicodeError:
            raise PersistenceError(PersistenceErrorCode.INVALID_INPUT) from None
        started = monotonic()
        result, failure = None, None
        try:
            result = build_submission_check(
                value.context, value.response_json, limits=value.settings.check_limits
            )
        except PageRuleError as error:
            failure = error.code
        with self._connection(write=True) as connection, connection:
            previous = self._rows(connection, project_id)
            for row in previous:
                _ = self._load(connection, row)
            run = StoredRun(
                run_id=str(uuid4()),
                project_id=project_id,
                sequence=len(previous) + 1,
                predecessor_run_id=previous[-1][0] if previous else None,
                created_at=datetime.now(UTC),
                elapsed_ms=(monotonic() - started) * 1000,
                status="succeeded" if result is not None else "failed",
                request=value,
                result=result,
                failure_code=failure,
            )
            blobs: dict[str, bytes] = {}
            manifest = canonical(encode(run, blobs))
            if len(manifest.encode()) > self.limits.max_manifest_bytes:
                raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)
            self._check_capacity(connection, manifest, blobs)
            _ = connection.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.project_id,
                    run.sequence,
                    run.status,
                    manifest,
                    sha256(manifest.encode()).hexdigest(),
                ),
            )
            _ = connection.executemany(
                "INSERT INTO blobs VALUES (?,?,?,?)",
                ((run.run_id, digest, len(content), content) for digest, content in blobs.items()),
            )
        return run

    def _check_capacity(
        self, connection: sqlite3.Connection, manifest: str, blobs: dict[str, bytes]
    ) -> None:
        count, manifest_size = TypeAdapter(tuple[int, int]).validate_python(
            connection.execute(
                "SELECT count(*), coalesce(sum(length(CAST(manifest AS BLOB))),0) FROM runs"
            ).fetchone()
        )
        blob_size = TypeAdapter(tuple[int]).validate_python(
            connection.execute("SELECT coalesce(sum(length(content)),0) FROM blobs").fetchone()
        )[0]
        added_size = len(manifest.encode()) + sum(map(len, blobs.values()))
        if (
            count >= self.limits.max_runs
            or manifest_size + blob_size + added_size > self.limits.max_stored_bytes
        ):
            raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)

    def get_run(self, run_id: str) -> StoredRun:
        run_id = self._identifier(run_id)
        with self._connection() as connection, connection:
            check_read_bounds(connection, self.limits)
            rows = ROWS.validate_python(
                connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchall()
            )
            if not rows:
                raise PersistenceError(PersistenceErrorCode.NOT_FOUND)
            return self._load(connection, rows[0])

    def latest_success(self, project_id: str) -> StoredRun | None:
        project_id = self._identifier(project_id)
        with self._connection() as connection, connection:
            runs = tuple(self._load(connection, row) for row in self._rows(connection, project_id))
            return next((run for run in reversed(runs) if run.status == "succeeded"), None)

    def list_runs(self, project_id: str) -> tuple[RunSummary, ...]:
        project_id = self._identifier(project_id)
        with self._connection() as connection, connection:
            runs = tuple(self._load(connection, row) for row in self._rows(connection, project_id))
            return tuple(
                RunSummary.model_validate(run.model_dump(include=set(RunSummary.model_fields)))
                for run in runs
            )

    @staticmethod
    def _identifier(value: str) -> str:
        try:
            identifier = IDENTIFIER.validate_python(value, strict=True)
            _ = identifier.encode()
        except (ValidationError, UnicodeError):
            raise PersistenceError(PersistenceErrorCode.INVALID_INPUT) from None
        return identifier

    def _rows(self, connection: sqlite3.Connection, project_id: str) -> tuple[RunRow, ...]:
        check_read_bounds(connection, self.limits)
        return ROWS.validate_python(
            connection.execute(
                "SELECT * FROM runs WHERE project_id=? ORDER BY sequence", (project_id,)
            ).fetchall()
        )

    def _load(self, connection: sqlite3.Connection, row: RunRow) -> StoredRun:
        try:
            manifest = row[4]
            if (
                len(manifest.encode()) > self.limits.max_manifest_bytes
                or sha256(manifest.encode()).hexdigest() != row[5]
            ):
                raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
            raw = TypeAdapter[JsonValue](JsonValue).validate_json(manifest)
            if isinstance(raw, dict) and raw.get("schema_version") != "1":
                raise PersistenceError(PersistenceErrorCode.UNSUPPORTED_SCHEMA)
            payloads = BLOBS.validate_python(
                connection.execute(
                    "SELECT sha256, byte_size, content FROM blobs WHERE run_id=?", (row[0],)
                ).fetchall()
            )
            if (
                len(payloads) > self.limits.max_payloads
                or sum(len(content) for _, _, content in payloads) > self.limits.max_total_bytes
            ):
                raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
            if any(
                size != len(content) or sha256(content).hexdigest() != digest
                for digest, size, content in payloads
            ):
                raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
            blobs = {digest: content for digest, _, content in payloads}
            run = StoredRun.model_validate(decode(raw, blobs), strict=False)
            try:
                _ = admit_request(run.request, self.limits)
            except PersistenceError:
                raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE) from None
            validate_result(run)
            used: dict[str, bytes] = {}
            if (
                canonical(encode(run, used)) != manifest
                or used != blobs
                or (run.run_id, run.project_id, run.sequence, run.status) != row[:4]
            ):
                raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
        except (ValidationError, TypeError, KeyError, RecursionError):
            raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE) from None
        return run
