"""Submitting, reading, classifying and progressing complaints."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.access import accessible_properties
from app.ai.classifier import ComplaintClassifier
from app.config import COMPLAINT_CATEGORIES
from app.db import get_engine
from app.errors import ApiError
from app.models import Complaint as ComplaintRow
from app.models import ComplaintStatusChange as StatusChangeRow
from app.models import Lease as LeaseRow
from app.models import Property as PropertyRow
from app.models import Room as RoomRow
from app.models import UserAccount
from app.schemas.auth import UserRole
from app.schemas.complaints import (
    AiComplaintClassification,
    Complaint,
    ComplaintClassification,
    ComplaintClassificationInput,
    ComplaintClassificationState,
    ComplaintList,
    ComplaintStatus,
    ComplaintStatusChange,
    ComplaintStatusChangeInput,
    ComplaintSummary,
    ComplaintUrgency,
    PropertyRef,
)
from app.schemas.tenants import RoomRef
from app.services.subscriptions import has_active_subscription

logger = logging.getLogger(__name__)

# Looked up when a classification starts, so tests can change it.
CLASSIFICATION_TIMEOUT_SECONDS = 10.0

# Management sees these urgencies first, in this order; the rest follow.
URGENCY_RANK = {
    ComplaintUrgency.HIGH: 0,
    ComplaintUrgency.MEDIUM: 1,
    ComplaintUrgency.LOW: 2,
}

# A complaint only moves forward, one status at a time.
NEXT_STATUS = {
    ComplaintStatus.NEW: ComplaintStatus.IN_PROGRESS,
    ComplaintStatus.IN_PROGRESS: ComplaintStatus.DONE,
}

type Row = tuple[ComplaintRow, RoomRow, PropertyRow, UserAccount]


def _rows() -> Select[Row]:
    return (
        select(ComplaintRow, RoomRow, PropertyRow, UserAccount)
        .join(RoomRow, RoomRow.id == ComplaintRow.room_id)
        .join(PropertyRow, PropertyRow.id == RoomRow.property_id)
        .join(UserAccount, UserAccount.id == ComplaintRow.tenant_id)
    )


def _readable_by(user: UserAccount) -> Select[Row]:
    """Select the complaints the user may read."""
    if user.role == UserRole.TENANT:
        return _rows().where(ComplaintRow.tenant_id == user.id)
    properties = accessible_properties(user).subquery()
    return _rows().where(PropertyRow.id.in_(select(properties.c.id)))


def _view(
    db: Session, row: Row, plans: dict[UUID, bool]
) -> tuple[ComplaintSummary, ComplaintUrgency | None]:
    """Build the summary of a complaint; also return its urgency when visible."""
    complaint, room, prop, tenant = row
    if prop.owner_id not in plans:
        plans[prop.owner_id] = has_active_subscription(db, prop.owner_id)
    has_ai = complaint.ai_category is not None
    visible_ai = has_ai and plans[prop.owner_id]
    classification = None
    urgency = None
    withheld = has_ai and not visible_ai
    state = None
    if complaint.manual_category is not None:
        urgency = ComplaintUrgency(complaint.manual_urgency)
        classifier = db.get(UserAccount, complaint.classified_by_id)
        classification = ComplaintClassification(
            category=complaint.manual_category,
            urgency=urgency,
            suggested_action=None,
            classified_by_name=classifier.name,
            original_ai_classification=AiComplaintClassification(
                category=complaint.ai_category,
                urgency=ComplaintUrgency(complaint.ai_urgency),
                suggested_action=complaint.ai_suggested_action,
            )
            if visible_ai
            else None,
        )
        withheld = False
    elif visible_ai:
        urgency = ComplaintUrgency(complaint.ai_urgency)
        classification = ComplaintClassification(
            category=complaint.ai_category,
            urgency=urgency,
            suggested_action=complaint.ai_suggested_action,
            classified_by_name=None,
            original_ai_classification=None,
        )
    elif not has_ai:
        state = complaint.classification_state
    summary = ComplaintSummary(
        id=complaint.id,
        description=complaint.description,
        status=ComplaintStatus(complaint.status),
        property=PropertyRef(id=prop.id, name=prop.name),
        room=RoomRef(id=room.id, number=room.number),
        tenant_name=tenant.name,
        created_at=complaint.created_at,
        has_photo=False,
        classification=classification,
        classification_state=state and ComplaintClassificationState(state),
        classification_withheld=withheld,
    )
    return summary, urgency


def _detail(db: Session, row: Row, plans: dict[UUID, bool]) -> Complaint:
    summary, _ = _view(db, row, plans)
    changes = db.scalars(
        select(StatusChangeRow)
        .where(StatusChangeRow.complaint_id == row[0].id)
        .order_by(StatusChangeRow.changed_at, StatusChangeRow.id)
    )
    return Complaint(
        **summary.__dict__,
        status_changes=[
            ComplaintStatusChange(
                status=ComplaintStatus(change.status),
                handling_note=change.handling_note,
                changed_at=change.changed_at,
            )
            for change in changes
        ],
    )


def create_complaint(db: Session, tenant: UserAccount, description: str) -> Complaint:
    """Save a new complaint in the room of the tenant's active lease.

    The state is `notClassified` when the property owner has no running paid
    subscription, otherwise `classifying`. Flushes, never commits. Raises 403
    NO_ACTIVE_LEASE when the tenant has no active lease.
    """
    lease = db.scalars(
        select(LeaseRow).where(
            LeaseRow.tenant_id == tenant.id, LeaseRow.ended_at.is_(None)
        )
    ).first()
    if lease is None:
        raise ApiError(403, "NO_ACTIVE_LEASE")
    owner_id = db.scalars(
        select(PropertyRow.owner_id)
        .join(RoomRow, RoomRow.property_id == PropertyRow.id)
        .where(RoomRow.id == lease.room_id)
    ).one()
    state = (
        ComplaintClassificationState.CLASSIFYING
        if has_active_subscription(db, owner_id)
        else ComplaintClassificationState.NOT_CLASSIFIED
    )
    now = datetime.now(UTC)
    row = ComplaintRow(
        tenant_id=tenant.id,
        room_id=lease.room_id,
        description=description,
        status=ComplaintStatus.NEW.value,
        classification_state=state.value,
        created_at=now,
    )
    db.add(row)
    db.flush()
    db.add(
        StatusChangeRow(
            complaint_id=row.id, status=ComplaintStatus.NEW.value, changed_at=now
        )
    )
    db.flush()
    return get_complaint(db, tenant, row.id)


def list_complaints(db: Session, user: UserAccount) -> ComplaintList:
    """List the complaints the user may read.

    Tenants get theirs newest first. Owners and managers get them by visible
    urgency (high, medium, low, then the rest), newest first within a group.
    """
    rows = db.execute(
        _readable_by(user).order_by(ComplaintRow.created_at.desc(), ComplaintRow.id)
    ).all()
    plans: dict[UUID, bool] = {}
    views = [_view(db, tuple(row), plans) for row in rows]
    if user.role != UserRole.TENANT:
        # The sort is stable, so the newest-first order holds within a group.
        views.sort(key=lambda view: URGENCY_RANK.get(view[1], len(URGENCY_RANK)))
    return ComplaintList(items=[summary for summary, _ in views])


def get_complaint(db: Session, user: UserAccount, complaint_id: UUID) -> Complaint:
    """Return a complaint the user may read, with its status history.

    Raises 404 COMPLAINT_NOT_FOUND for an unknown or unreadable complaint.
    """
    row = db.execute(_readable_by(user).where(ComplaintRow.id == complaint_id)).first()
    if row is None:
        raise ApiError(404, "COMPLAINT_NOT_FOUND")
    return _detail(db, tuple(row), {})


def notify_complaint_status_change(
    complaint: ComplaintRow, change: StatusChangeRow
) -> None:
    """Tell the tenant that their complaint moved to a new status."""


def change_complaint_status(
    db: Session, user: UserAccount, complaint_id: UUID, data: ComplaintStatusChangeInput
) -> Complaint:
    """Move a complaint to its next status and record it in the history.

    A blank handling note is stored as none. Flushes, never commits. The tenant
    is notified after the change is flushed, before the commit; a failing
    notification is logged and does not undo the change. Raises 404
    COMPLAINT_NOT_FOUND for an unknown or unreadable complaint and 409
    COMPLAINT_STATUS_NOT_NEXT when the status is not the next one.
    """
    row = db.execute(_readable_by(user).where(ComplaintRow.id == complaint_id)).first()
    if row is None:
        raise ApiError(404, "COMPLAINT_NOT_FOUND")
    complaint = row[0]
    if NEXT_STATUS.get(ComplaintStatus(complaint.status)) != data.status:
        raise ApiError(409, "COMPLAINT_STATUS_NOT_NEXT", field="status")
    complaint.status = data.status.value
    change = StatusChangeRow(
        complaint_id=complaint.id,
        status=data.status.value,
        handling_note=(data.handling_note or "").strip() or None,
        changed_at=datetime.now(UTC),
    )
    db.add(change)
    db.flush()
    # Detached rows keep their loaded values after the request session commits.
    db.expunge(complaint)
    db.expunge(change)
    try:
        notify_complaint_status_change(complaint, change)
    except Exception:
        logger.exception("Notifying about the status change of %s failed", complaint.id)
    return _detail(db, tuple(row), {})


def classify_complaint_manually(
    db: Session,
    user: UserAccount,
    complaint_id: UUID,
    data: ComplaintClassificationInput,
) -> Complaint:
    """Set the category and urgency of a complaint by hand.

    Submitting the classification already shown changes nothing, so the actor
    and time of an earlier one are kept. Flushes, never commits. Raises 404
    COMPLAINT_NOT_FOUND for an unknown or unreadable complaint and 422
    COMPLAINT_CATEGORY_INVALID for a category outside the list.
    """
    row = db.execute(_readable_by(user).where(ComplaintRow.id == complaint_id)).first()
    if row is None:
        raise ApiError(404, "COMPLAINT_NOT_FOUND")
    if data.category not in COMPLAINT_CATEGORIES:
        raise ApiError(422, "COMPLAINT_CATEGORY_INVALID", field="category")
    complaint, _, prop, _ = row
    if complaint.manual_category is not None:
        shown = (complaint.manual_category, complaint.manual_urgency)
    elif complaint.ai_category is not None and has_active_subscription(
        db, prop.owner_id
    ):
        shown = (complaint.ai_category, complaint.ai_urgency)
    else:
        shown = None
    if shown != (data.category, data.urgency.value):
        complaint.manual_category = data.category
        complaint.manual_urgency = data.urgency.value
        complaint.classified_by_id = user.id
        complaint.classified_at = datetime.now(UTC)
        db.flush()
    return _detail(db, tuple(row), {})


def _classify_within_timeout(
    classifier: ComplaintClassifier, description: str
) -> AiComplaintClassification:
    """Run the blocking classifier in a worker thread and wait for its result.

    A result arriving after the timeout is discarded.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(classifier.classify, description, COMPLAINT_CATEGORIES)
        return future.result(timeout=CLASSIFICATION_TIMEOUT_SECONDS)
    finally:
        executor.shutdown(wait=False)


def _check(result: AiComplaintClassification) -> None:
    if result.category not in COMPLAINT_CATEGORIES:
        raise ValueError(f"Unknown category {result.category!r}")
    ComplaintUrgency(result.urgency)
    if not result.suggested_action.strip():
        raise ValueError("Empty suggested action")


def classify_complaint(
    complaint_id: UUID, description: str, classifier: ComplaintClassifier
) -> None:
    """Classify a saved complaint with its own database session.

    A valid result is stored and the interim state cleared. Any failure,
    timeout or invalid result leaves the complaint awaiting classification.
    Never raises, and never undoes the complaint.
    """
    result = None
    try:
        result = _classify_within_timeout(classifier, description)
        _check(result)
    except Exception:
        logger.exception("Classifying complaint %s failed", complaint_id)
        result = None
    try:
        with Session(get_engine()) as db:
            row = db.get(ComplaintRow, complaint_id)
            if result is None:
                row.classification_state = (
                    ComplaintClassificationState.AWAITING_CLASSIFICATION.value
                )
            else:
                row.classification_state = None
                row.ai_category = result.category
                row.ai_urgency = ComplaintUrgency(result.urgency).value
                row.ai_suggested_action = result.suggested_action
            db.commit()
    except Exception:
        logger.exception("Storing the classification of %s failed", complaint_id)
