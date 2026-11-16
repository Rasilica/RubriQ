from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from secrets import compare_digest, token_urlsafe
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from submission.semantic_contracts import SemanticArchive, SemanticState

from submission.models import DocumentRole
from submission.pair_contracts import (
    PairError,
    PairErrorCode,
    PreparedRole,
    SavedOrigin,
    SessionView,
)


@dataclass(frozen=True, slots=True)
class Session:
    identifier: str
    token: str
    project: str
    expires: float
    expires_at: datetime
    guide: PreparedRole
    report: PreparedRole
    semantic_state: SemanticState | None = None
    semantic_archive: SemanticArchive | None = None
    semantic_revision: int = 0
    leases: int = 0
    deleted: bool = False
    images: tuple[tuple[str, bytes], ...] = ()
    saved_id: str | None = None
    saved_at: datetime | None = None
    saved_environment: tuple[str, ...] = ()
    current_environment: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return (
            (len(self.semantic_archive.model_dump_json().encode()) if self.semantic_archive else 0)
            + self.guide.size
            + self.report.size
            + (len(self.semantic_state.model_dump_json().encode()) if self.semantic_state else 0)
        )

    def role(self, role: DocumentRole) -> PreparedRole:
        return self.guide if role == DocumentRole.GUIDE else self.report

    def view(self, *, include_token: bool = False) -> SessionView:
        return SessionView(
            semantic_archive=self.semantic_archive,
            session_id=self.identifier,
            project_name=self.project,
            expires_at=self.expires_at,
            guide=self.guide.view,
            report=self.report.view,
            access_token=self.token if include_token else None,
            saved_id=self.saved_id,
            saved_at=self.saved_at,
            saved_environment=self.saved_environment,
            current_environment=self.current_environment,
        )


@final
class PairStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        ttl: float = 1800,
        max_sessions: int = 4,
        max_bytes: int = 256 * 1024 * 1024,
        image_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.clock = clock
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.max_bytes = max_bytes
        self.image_bytes = image_bytes
        self._lock = Lock()
        self._sessions: tuple[Session, ...] = ()

    def _prune(self) -> None:
        now = self.clock()
        self._sessions = tuple(
            replace(item, deleted=True) if item.expires <= now else item
            for item in self._sessions
            if item.leases or (not item.deleted and item.expires > now)
        )

    def cleanup(self) -> None:
        with self._lock:
            self._prune()

    def clear(self) -> None:
        with self._lock:
            self._sessions = tuple(replace(item, deleted=True) for item in self._sessions)
            self._prune()

    def create(
        self,
        project: str,
        guide: PreparedRole,
        report: PreparedRole,
        *,
        origin: SavedOrigin | None = None,
        semantic_archive: SemanticArchive | None = None,
    ) -> Session:
        with self._lock:
            self._prune()
            if (
                len(self._sessions) >= self.max_sessions
                or sum(item.size for item in self._sessions)
                + guide.size
                + report.size
                + (len(semantic_archive.model_dump_json().encode()) if semantic_archive else 0)
                > self.max_bytes
            ):
                raise PairError(PairErrorCode.LIMIT)
            session = Session(
                token_urlsafe(24),
                token_urlsafe(32),
                project,
                self.clock() + self.ttl,
                datetime.now(UTC) + timedelta(seconds=self.ttl),
                guide,
                report,
                semantic_archive=semantic_archive,
                saved_id=origin.saved_id if origin else None,
                saved_at=origin.saved_at if origin else None,
                saved_environment=origin.saved_environment if origin else (),
                current_environment=origin.current_environment if origin else (),
            )
            self._sessions = (*self._sessions, session)
            return session

    def _find(self, identifier: str, token: str) -> Session:
        self._prune()
        session = next((item for item in self._sessions if item.identifier == identifier), None)
        if (
            session is None
            or session.deleted
            or not compare_digest(session.token.encode(), token.encode())
        ):
            raise PairError(PairErrorCode.NOT_FOUND)
        return session

    def _replace(self, session: Session) -> None:
        self._sessions = tuple(
            session if item.identifier == session.identifier else item for item in self._sessions
        )

    @contextmanager
    def lease(self, identifier: str, token: str) -> Generator[Session]:
        with self._lock:
            session = self._find(identifier, token)
            self._replace(replace(session, leases=session.leases + 1))
        try:
            yield session
        finally:
            with self._lock:
                current = next(item for item in self._sessions if item.identifier == identifier)
                self._replace(replace(current, leases=current.leases - 1))
                self._prune()

    def delete(self, identifier: str, token: str) -> None:
        with self._lock:
            session = self._find(identifier, token)
            self._replace(replace(session, deleted=True))
            self._prune()

    def cache(self, identifier: str, token: str, key: str, content: bytes) -> None:
        with self._lock:
            session = self._find(identifier, token)
            total = sum(len(data) for item in self._sessions for _, data in item.images)
            if total + len(content) > self.image_bytes:
                self._sessions = tuple(replace(item, images=()) for item in self._sessions)
                session = replace(session, images=())
            if len(content) <= self.image_bytes:
                images = tuple(item for item in session.images if item[0] != key)
                self._replace(replace(session, images=(*images, (key, content))))

    def semantic_commit(
        self, identifier: str, token: str, expected: int, state: SemanticState
    ) -> None:
        with self._lock:
            session = self._find(identifier, token)
            if session.semantic_revision != expected:
                raise PairError(PairErrorCode.BUSY)
            updated = replace(
                session, semantic_state=state, semantic_archive=None, semantic_revision=expected + 1
            )
            if (
                len(state.model_dump_json().encode()) > 1024 * 1024
                or sum(item.size for item in self._sessions) - session.size + updated.size
                > self.max_bytes
            ):
                raise PairError(PairErrorCode.LIMIT)
            self._replace(updated)

    def semantic_current(self, identifier: str, token: str, expected: int) -> None:
        with self._lock:
            if self._find(identifier, token).semantic_revision != expected:
                raise PairError(PairErrorCode.BUSY)
