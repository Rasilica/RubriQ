import json
from dataclasses import dataclass, field
from secrets import token_urlsafe
from typing import Final

from pydantic import SecretStr

from submission import semantic_diagnostics as diagnostics
from submission.cloud_contracts import CloudCode, CloudError
from submission.credentials import CredentialStore, KeyringStore, resolve_key
from submission.pair_store import PairStore, Session
from submission.report_check_adapter import build_report_check, prepare_report_check_request
from submission.report_check_contracts import ReportCheckContext
from submission.report_check_validation import criteria_fingerprint
from submission.requirement_adapter import build_requirement_draft, prepare_requirement_request
from submission.requirement_contracts import RequirementLimits
from submission.result_rate_limit import ResultRateLimit
from submission.review_contracts import ReviewSession, WorkingCopyRequest
from submission.review_logic import confirm_session, initial_item, save_working_copy
from submission.semantic_client import PROVIDER_TIMEOUT, complete
from submission.semantic_context import CHECK_LIMITS, document, draft_view
from submission.semantic_contracts import (
    AIRequest,
    CheckRequest,
    CheckView,
    CriteriaRequest,
    DraftView,
    LiveReportResult,
    RequirementsRequest,
    SemanticCode,
    SemanticError,
    SemanticState,
)

REQUIREMENT_LIMITS: Final = RequirementLimits(
    max_blocks=200,
    max_input_characters=20000,
    max_response_bytes=262144,
    max_requirements=30,
    max_subconditions=10,
)


@dataclass(frozen=True, slots=True)
class Credentials:
    token: str
    key: SecretStr


def context(session: Session, state: SemanticState) -> ReportCheckContext:
    if state.review.confirmed_revision != state.review.revision or not state.review.versions:
        raise SemanticError(SemanticCode.CONFIRMATION_REQUIRED, 409)
    return ReportCheckContext(
        guide=document(session.guide),
        report=document(session.report),
        original_draft=state.review.original_draft,
        criteria=state.review.versions[-1],
    )


def current_state(session: Session, draft_id: str) -> SemanticState:
    state = session.semantic_state
    if state is None and session.semantic_archive is not None:
        return archived_state(session, draft_id)
    if state is None or state.review.session_id != draft_id:
        raise SemanticError(SemanticCode.STALE_DRAFT, 409)
    return state


def archived_state(session: Session, draft_id: str) -> SemanticState:
    from submission.semantic_archive import validate_archive  # noqa: PLC0415

    archive = session.semantic_archive
    if archive is None or archive.draft.draft_id != draft_id:
        raise SemanticError(SemanticCode.STALE_DRAFT, 409)
    validate_archive(archive, session.guide, session.report)
    return SemanticState(
        provider=archive.draft.provider,
        model=archive.draft.model,
        usage=archive.draft.usage,
        check=archive.check,
        review=ReviewSession(
            session_id=archive.draft.draft_id,
            revision=archive.draft.revision,
            confirmed_revision=archive.draft.revision,
            original_draft=archive.original_draft,
            source_blocks=(),
            items=archive.criteria.items,
            versions=(archive.criteria,),
        ),
    )


@dataclass(frozen=True, slots=True)
class SemanticService:
    store: PairStore
    quota: ResultRateLimit
    credential_store: CredentialStore = field(default_factory=KeyringStore)

    def admit(self, request: AIRequest, credentials: Credentials) -> SecretStr:
        if not request.consent:
            raise SemanticError(SemanticCode.CONSENT_REQUIRED)
        if request.provider == "ollama":
            return credentials.key
        return resolve_key(
            request.provider,
            credentials.key,
            use_saved=request.use_saved_key,
            store=self.credential_store,
        )

    def ensure_call_time(self, session: Session) -> None:
        # Sessions expire on schedule even mid-call, so refuse calls whose result would be lost.
        if session.expires - self.store.clock() < PROVIDER_TIMEOUT:
            raise SemanticError(SemanticCode.SESSION_EXPIRING, 409)

    def requirements(
        self,
        identifier: str,
        request: RequirementsRequest,
        credentials: Credentials,
    ) -> DraftView:
        with self.store.lease(identifier, credentials.token) as session:
            key = self.admit(request, credentials)
            guide = document(session.guide)
            if guide.source.content_sha256 != request.guide_sha256:
                raise SemanticError(SemanticCode.SOURCE_MISMATCH, 409)
            prepared = prepare_requirement_request(guide, limits=REQUIREMENT_LIMITS)
            self.ensure_call_time(session)
            if self.quota.retry_after():
                raise CloudError(CloudCode.RATE_LIMITED, 429)
            completion = complete(request, prepared.instructions, prepared.model_dump_json(), key)
            diagnostics.mark("report_validation", "report_contract_invalid")
            draft = build_requirement_draft(guide, completion.suggestion, limits=REQUIREMENT_LIMITS)
            diagnostics.mark("result_build", "result_invalid")
            state = SemanticState(
                provider=request.provider,
                model=request.model,
                usage=completion.usage,
                review=ReviewSession(
                    session_id=token_urlsafe(24),
                    original_draft=draft,
                    source_blocks=(),
                    items=tuple(initial_item(item) for item in draft.requirements),
                ),
            )
            self.store.semantic_commit(
                identifier, credentials.token, session.semantic_revision, state
            )
            return draft_view(session, state)

    def current_criteria(
        self,
        identifier: str,
        draft_id: str,
        credentials: Credentials,
    ) -> DraftView:
        with self.store.lease(identifier, credentials.token) as session:
            state = current_state(session, draft_id)
            result = draft_view(session, state)
            self.store.semantic_current(identifier, credentials.token, session.semantic_revision)
            return result

    def criteria(
        self,
        identifier: str,
        request: CriteriaRequest,
        credentials: Credentials,
    ) -> DraftView:
        with self.store.lease(identifier, credentials.token) as session:
            state = current_state(session, request.draft_id)
            review = state.review
            if (
                review.confirmed_revision == review.revision
                and request.expected_revision <= review.revision
                and tuple(item.model_dump() for item in request.items)
                == tuple(item.model_dump(exclude={"edited_fields"}) for item in review.items)
            ):
                result = draft_view(session, state)
                self.store.semantic_current(
                    identifier, credentials.token, session.semantic_revision
                )
                return result
            saved = save_working_copy(
                state.review,
                WorkingCopyRequest(
                    expected_revision=request.expected_revision,
                    items=request.items,
                ),
            )
            if any(
                current.application_status != requested.application_status
                for current, requested in zip(saved.items, request.items, strict=True)
                if current.classification == "conditional"
            ):
                saved = save_working_copy(
                    saved,
                    WorkingCopyRequest(
                        expected_revision=saved.revision,
                        items=request.items,
                    ),
                )
            confirmed = confirm_session(saved, saved.revision, 20)
            updated = state.model_copy(update={"review": confirmed, "check": None})
            result = draft_view(session, updated)
            self.store.semantic_commit(
                identifier, credentials.token, session.semantic_revision, updated
            )
            return result

    def check(
        self,
        identifier: str,
        request: CheckRequest,
        credentials: Credentials,
    ) -> CheckView:
        with self.store.lease(identifier, credentials.token) as session:
            key = self.admit(request, credentials)
            state = current_state(session, request.draft_id)
            ctx = context(session, state)
            if (
                request.guide_sha256 != ctx.guide.source.content_sha256
                or request.report_sha256 != ctx.report.source.content_sha256
                or request.criteria_sha256 != criteria_fingerprint(ctx)
            ):
                raise SemanticError(SemanticCode.SOURCE_MISMATCH, 409)
            if len(ctx.guide.blocks) + len(ctx.report.blocks) > CHECK_LIMITS.max_blocks:
                raise SemanticError(SemanticCode.INPUT_LIMIT)
            prepared = prepare_report_check_request(ctx, limits=CHECK_LIMITS)
            payload = json.dumps(
                {
                    **prepared.model_dump(mode="json"),
                    "guide_blocks": [
                        {"block_id": block.block_id, "raw_text": block.raw_text}
                        for block in ctx.guide.blocks
                        if block.raw_text.strip()
                    ],
                },
                ensure_ascii=False,
            )
            self.ensure_call_time(session)
            if self.quota.retry_after():
                raise CloudError(CloudCode.RATE_LIMITED, 429)
            completion = complete(request, prepared.instructions, payload, key)
            diagnostics.mark("report_validation", "report_contract_invalid")
            checked = build_report_check(ctx, completion.suggestion, limits=CHECK_LIMITS)
            diagnostics.mark("result_build", "result_invalid")
            result = LiveReportResult.model_validate(
                checked.model_dump(
                    exclude={
                        "fake",
                        "response_label",
                        "adapter_id",
                        "ai_called",
                        "stored",
                    }
                )
            )
            view = CheckView(
                provider=request.provider,
                model=request.model,
                result=result,
                usage=completion.usage,
            )

            self.store.semantic_commit(
                identifier,
                credentials.token,
                session.semantic_revision,
                state.model_copy(update={"check": view}),
            )
            return view
