from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from threading import RLock
from time import monotonic
from typing import final

from pydantic import ValidationError

from submission.document_contracts import ContractError
from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput, UploadError
from submission.pdf_adapter import adapt_pdf
from submission.requirement_adapter import OfflineRequirementAdapter
from submission.requirement_contracts import RequirementError
from submission.review_contracts import (
    CreatedSession,
    ReviewError,
    ReviewErrorCode,
    ReviewSession,
    SourceBlock,
    WorkingCopyRequest,
)
from submission.review_logic import confirm_session, initial_item, save_working_copy


def demo_session(session_id: str) -> ReviewSession:
    samples = Path(__file__).resolve().parents[2] / "samples"
    source = PdfInput("guide.pdf", (samples / "pdf/guide.pdf").read_bytes(), DocumentRole.GUIDE)
    document = adapt_pdf(source, extract_pdf(source))
    response = (samples / "requirements/guide-offline-response.json").read_text(encoding="utf-8")
    draft = OfflineRequirementAdapter(response).extract(document)
    return ReviewSession(
        session_id=session_id,
        original_draft=draft,
        source_blocks=tuple(
            SourceBlock(
                block_id=block.block_id,
                raw_text=block.raw_text,
                source_locator=block.source_locator,
            )
            for block in document.blocks
        ),
        items=tuple(initial_item(item) for item in draft.requirements),
    )


@dataclass(frozen=True, slots=True)
class SessionEntry:
    token: str
    expires: float
    session: ReviewSession


@final
class ReviewStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        ttl_seconds: float = 1800,
        max_sessions: int = 32,
        max_versions: int = 20,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._max_versions = max_versions
        self._entries: dict[str, SessionEntry] = {}
        self._lock = RLock()

    def create(self) -> CreatedSession:
        with self._lock:
            self._entries = {
                key: entry for key, entry in self._entries.items() if entry.expires > self._clock()
            }
            if len(self._entries) >= self._max_sessions:
                raise ReviewError(ReviewErrorCode.SESSION_LIMIT, 429)
            try:
                session = demo_session(token_urlsafe(24))
            except (
                OSError,
                UnicodeError,
                UploadError,
                ContractError,
                RequirementError,
                ValidationError,
            ):
                raise ReviewError(ReviewErrorCode.DEMO_UNAVAILABLE, 503) from None
            token = token_urlsafe(32)
            self._entries = {
                **self._entries,
                session.session_id: SessionEntry(token, self._clock() + self._ttl, session),
            }
            return CreatedSession.model_validate({**session.model_dump(), "session_token": token})

    def _entry(self, session_id: str, token: str) -> SessionEntry:
        entry = self._entries.get(session_id)
        if (
            entry is None
            or entry.expires <= self._clock()
            or not token.isascii()
            or len(token) != len(entry.token)
            or not compare_digest(entry.token, token)
        ):
            raise ReviewError(ReviewErrorCode.SESSION_UNAVAILABLE, 404)
        return entry

    def get(self, session_id: str, token: str) -> ReviewSession:
        with self._lock:
            return self._entry(session_id, token).session

    def save(self, session_id: str, token: str, request: WorkingCopyRequest) -> ReviewSession:
        with self._lock:
            entry = self._entry(session_id, token)
            session = save_working_copy(entry.session, request)
            self._entries = {
                **self._entries,
                session_id: SessionEntry(entry.token, entry.expires, session),
            }
            return session

    def confirm(self, session_id: str, token: str, revision: int) -> ReviewSession:
        with self._lock:
            entry = self._entry(session_id, token)
            session = confirm_session(entry.session, revision, self._max_versions)
            self._entries = {
                **self._entries,
                session_id: SessionEntry(entry.token, entry.expires, session),
            }
            return session
