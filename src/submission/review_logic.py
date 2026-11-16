from submission.requirement_contracts import RequirementItem
from submission.review_contracts import (
    CriteriaVersion,
    EditableItem,
    EditableSubcondition,
    ReviewedItem,
    ReviewError,
    ReviewErrorCode,
    ReviewSession,
    WorkingCopyRequest,
)


def initial_item(item: RequirementItem) -> ReviewedItem:
    return ReviewedItem(
        requirement_id=item.requirement_id,
        title=item.title,
        classification=item.classification,
        condition_description=item.condition.description if item.condition else None,
        subconditions=tuple(
            EditableSubcondition(subcondition_id=sub.subcondition_id, description=sub.description)
            for sub in item.subconditions
        ),
        included=True,
        exclusion_reason=None,
        application_status="undetermined" if item.classification == "conditional" else "applies",
        application_reason=None,
    )


def normalize_item(item: EditableItem, previous: ReviewedItem) -> EditableItem:
    if not item.included and item.exclusion_reason is None:
        raise ReviewError(ReviewErrorCode.EXCLUSION_REASON_REQUIRED)
    if (item.classification == "conditional") != (item.condition_description is not None):
        raise ReviewError(ReviewErrorCode.INVALID_CONDITION)
    if item.classification != "conditional":
        return item.model_copy(update={"application_status": "applies", "application_reason": None})
    changed = (
        item.classification != previous.classification
        or item.condition_description != previous.condition_description
    )
    if changed:
        return item.model_copy(
            update={"application_status": "undetermined", "application_reason": None}
        )
    if item.application_status != "undetermined" and item.application_reason is None:
        raise ReviewError(ReviewErrorCode.APPLICATION_REASON_REQUIRED)
    return item


def save_working_copy(session: ReviewSession, request: WorkingCopyRequest) -> ReviewSession:
    check_revision(session, request.expected_revision)
    if tuple(item.requirement_id for item in request.items) != tuple(
        item.requirement_id for item in session.items
    ):
        raise ReviewError(ReviewErrorCode.IMMUTABLE_IDENTITY)
    updated: list[ReviewedItem] = []
    for item, previous, original in zip(
        request.items, session.items, session.original_draft.requirements, strict=True
    ):
        if tuple(sub.subcondition_id for sub in item.subconditions) != tuple(
            sub.subcondition_id for sub in previous.subconditions
        ):
            raise ReviewError(ReviewErrorCode.IMMUTABLE_IDENTITY)
        normalized = normalize_item(item, previous)
        baseline = initial_item(original).model_dump(exclude={"edited_fields"})
        values = normalized.model_dump()
        updated.append(
            ReviewedItem.model_validate(
                {
                    **values,
                    "edited_fields": tuple(key for key in values if values[key] != baseline[key]),
                }
            )
        )
    return session.model_copy(
        update={
            "revision": session.revision + 1,
            "items": tuple(updated),
            "confirmed_revision": None,
        }
    )


def check_revision(session: ReviewSession, expected_revision: int) -> None:
    if session.revision != expected_revision:
        raise ReviewError(ReviewErrorCode.STALE_REVISION, 409)


def confirm_session(
    session: ReviewSession, expected_revision: int, max_versions: int
) -> ReviewSession:
    check_revision(session, expected_revision)
    if session.confirmed_revision == session.revision:
        return session
    if not any(item.included for item in session.items):
        raise ReviewError(ReviewErrorCode.EMPTY_CRITERIA)
    if any(item.included and item.application_status == "undetermined" for item in session.items):
        raise ReviewError(ReviewErrorCode.APPLICATION_UNDETERMINED)
    previous_version = session.versions[-1].version if session.versions else 0
    if previous_version >= max_versions:
        raise ReviewError(ReviewErrorCode.VERSION_LIMIT, 409)
    version = CriteriaVersion(
        version=previous_version + 1,
        revision=session.revision,
        document_version_id=session.original_draft.document_version_id,
        source_sha256=session.original_draft.source_sha256,
        items=session.items,
    )
    return session.model_copy(
        update={"versions": (*session.versions, version), "confirmed_revision": session.revision}
    )
