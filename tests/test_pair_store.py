from dataclasses import replace

import pytest

from submission.document_contracts import ProcessingStatus
from submission.models import DocumentRole
from submission.pair_contracts import PairError, PairErrorCode, PreparedRole, RoleView
from submission.pair_store import PairStore


def item(role: DocumentRole = DocumentRole.GUIDE) -> PreparedRole:
    return PreparedRole(
        RoleView(
            role=role,
            document=None,
            extraction_status=ProcessingStatus.FAILED,
            rendering_status=ProcessingStatus.FAILED,
        ),
        b"source",
    )


def test_expired_lease_is_retained_until_release_and_never_republished() -> None:
    now = [0.0]
    store = PairStore(clock=lambda: now[0], ttl=1, max_sessions=1)
    session = store.create("one", item(), item(DocumentRole.REPORT))
    with store.lease(session.identifier, session.token) as leased:
        now[0] = 2.0
        store.cleanup()
        assert leased.guide.original == b"source"
        with pytest.raises(PairError, match="session_not_found"):
            store.cache(session.identifier, session.token, "page", b"late")
        with pytest.raises(PairError, match="session_limit"):
            _ = store.create("two", item(), item())
    replacement = store.create("two", item(), item())
    assert replacement.identifier != session.identifier


def test_delete_during_lease_and_clear() -> None:
    store = PairStore(max_sessions=1)
    session = store.create("one", item(), item())
    with store.lease(session.identifier, session.token):
        store.delete(session.identifier, session.token)
        with (
            pytest.raises(PairError, match="session_not_found"),
            store.lease(session.identifier, session.token),
        ):
            pytest.fail("deleted session accessible")
        store.clear()
    _ = store.create("two", item(), item())
    store.clear()
    _ = store.create("three", item(), item())


def test_wrong_token_and_non_ascii_are_not_found() -> None:
    store = PairStore()
    session = store.create("one", item(), item())
    for token in ("", "wrong", "잘못된토큰"):
        with pytest.raises(PairError) as error, store.lease(session.identifier, token):
            pytest.fail("wrong token accepted")
        assert error.value.code == PairErrorCode.NOT_FOUND


def test_memory_and_image_cache_limits() -> None:
    small = PairStore(max_bytes=1)
    with pytest.raises(PairError, match="session_limit"):
        _ = small.create("too large", item(), item())
    store = PairStore(image_bytes=4)
    session = store.create("test", item(), item())
    store.cache(session.identifier, session.token, "first", b"123")
    store.cache(session.identifier, session.token, "second", b"456")
    with store.lease(session.identifier, session.token) as state:
        assert state.images == (("second", b"456"),)
        assert state.role(DocumentRole.REPORT) == session.report
        assert state.view().access_token is None
    store.cache(session.identifier, session.token, "oversize", b"12345")
    with store.lease(session.identifier, session.token) as state:
        assert state.images == ()
    large = replace(item(), original=b"large")
    assert large.size > len(large.original)
