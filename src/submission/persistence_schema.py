import os
import sqlite3
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from submission.persistence_contracts import (
    PersistenceError,
    PersistenceErrorCode,
    PersistenceLimits,
)

APPLICATION_ID: Final = 1112753713


def private_database_path(path: Path) -> Path:
    try:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path
        with os.fdopen(descriptor, "wb"):
            return path
    except OSError:
        raise PersistenceError(PersistenceErrorCode.STORAGE_ERROR) from None


def initialize_schema(connection: sqlite3.Connection) -> None:
    version = TypeAdapter(tuple[int]).validate_python(
        connection.execute("PRAGMA user_version").fetchone()
    )[0]
    marker = TypeAdapter(tuple[int]).validate_python(
        connection.execute("PRAGMA application_id").fetchone()
    )[0]
    tables = TypeAdapter(tuple[tuple[str], ...]).validate_python(
        connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    )
    if version == 0 and marker == 0 and not tables:
        _ = connection.execute(
            """CREATE TABLE runs (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, status TEXT NOT NULL, manifest TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL, UNIQUE(project_id,sequence))"""
        )
        _ = connection.execute(
            """CREATE TABLE blobs (run_id TEXT NOT NULL REFERENCES runs(run_id),
            sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, content BLOB NOT NULL,
            PRIMARY KEY(run_id,sha256))"""
        )
        _ = connection.execute("PRAGMA user_version=1")
        _ = connection.execute("PRAGMA application_id=1112753713")
        return
    if version != 1 or marker != APPLICATION_ID or set(tables) != {("runs",), ("blobs",)}:
        raise PersistenceError(PersistenceErrorCode.UNSUPPORTED_SCHEMA)
    for table, columns in (
        ("runs", ("run_id", "project_id", "sequence", "status", "manifest", "manifest_sha256")),
        ("blobs", ("run_id", "sha256", "byte_size", "content")),
    ):
        actual = TypeAdapter(tuple[tuple[str], ...]).validate_python(
            connection.execute("SELECT name FROM pragma_table_info(?)", (table,)).fetchall()
        )
        if tuple(row[0] for row in actual) != columns:
            raise PersistenceError(PersistenceErrorCode.UNSUPPORTED_SCHEMA)


def check_read_bounds(connection: sqlite3.Connection, limits: PersistenceLimits) -> None:
    count, total, largest = TypeAdapter(tuple[int, int, int]).validate_python(
        connection.execute(
            """SELECT count(*),coalesce(sum(length(CAST(manifest AS BLOB))),0),
            coalesce(max(length(CAST(manifest AS BLOB))),0) FROM runs"""
        ).fetchone()
    )
    payloads = TypeAdapter(tuple[tuple[int, int], ...]).validate_python(
        connection.execute(
            "SELECT count(*),sum(length(content)) FROM blobs GROUP BY run_id"
        ).fetchall()
    )
    if (
        count > limits.max_runs
        or largest > limits.max_manifest_bytes
        or total + sum(size for _, size in payloads) > limits.max_stored_bytes
        or any(n > limits.max_payloads or size > limits.max_total_bytes for n, size in payloads)
    ):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
