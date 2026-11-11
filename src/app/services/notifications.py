"""Creating, pushing, listing and reading notifications, and the push settings."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, String, cast, event, or_, select, text
from sqlalchemy.orm import Session

from app import push
from app.db import get_engine
from app.errors import ApiError
from app.models import (
    Lease,
    ManagerAssignment,
    Property,
    RentBill,
    UserAccount,
    UserSession,
)
from app.models import Notification as NotificationRow
from app.models import NotificationSetting as SettingRow
from app.schemas.auth import UserRole
from app.schemas.base import ApiModel
from app.schemas.notifications import (
    Notification,
    NotificationCategory,
    NotificationList,
    NotificationRentBill,
    NotificationSettingItem,
    NotificationSettings,
    NotificationSettingsInput,
    NotificationType,
    NotificationUrgencyScope,
)
from app.services.sessions import _active_sessions_of

logger = logging.getLogger(__name__)

# Key in `Session.info` of the pushes waiting for the outermost commit.
PENDING_PUSHES = "pending_pushes"

CATEGORY_OF_TYPE = {
    NotificationType.BILL_ISSUED: NotificationCategory.BILLING,
    NotificationType.DUE_DATE_REMINDER: NotificationCategory.BILLING,
    NotificationType.BILL_OVERDUE: NotificationCategory.BILLING,
    NotificationType.PAYMENT_STATUS_CHANGED: NotificationCategory.PAYMENT_STATUS,
    NotificationType.COMPLAINT_STATUS_CHANGED: NotificationCategory.COMPLAINT_PROGRESS,
    NotificationType.COMPLAINT_SUBMITTED: NotificationCategory.NEW_COMPLAINT,
    NotificationType.RECEIPT_UPLOADED: NotificationCategory.RECEIPT_UPLOAD,
    NotificationType.CASH_PAYMENT_RECORDED: NotificationCategory.ACCOUNT_ACTIVITY,
    NotificationType.TENANT_ACTIVATED: NotificationCategory.ACCOUNT_ACTIVITY,
    NotificationType.MANAGER_ACTIVATED: NotificationCategory.ACCOUNT_ACTIVITY,
}

STAFF_CATEGORIES = [
    NotificationCategory.NEW_COMPLAINT,
    NotificationCategory.RECEIPT_UPLOAD,
    NotificationCategory.OVERDUE_BILL,
    NotificationCategory.ACCOUNT_ACTIVITY,
]
CATEGORIES_OF_ROLE = {
    UserRole.TENANT: [
        NotificationCategory.BILLING,
        NotificationCategory.PAYMENT_STATUS,
        NotificationCategory.COMPLAINT_PROGRESS,
    ],
    UserRole.OWNER: STAFF_CATEGORIES,
    UserRole.MANAGER: STAFF_CATEGORIES,
}

# A bill is reminded this many days before its due date.
REMINDER_DAYS = 3

# Fields of `Notification` that hold the facts of the event.
FACT_FIELDS = ("rent_bill", "complaint", "tenant", "room", "property", "actor_name")


def management_of(db: Session, property_id: UUID) -> list[UUID]:
    """Return the ids of the property's Owner and of the Managers assigned to it."""
    owner_id = db.scalars(select(Property.owner_id).where(Property.id == property_id))
    managers = db.scalars(
        select(ManagerAssignment.manager_id).where(
            ManagerAssignment.property_id == property_id
        )
    )
    return [*owner_id, *managers]


def _fact(value: ApiModel | str | None) -> object:
    return (
        value.model_dump(mode="json", by_alias=True)
        if isinstance(value, ApiModel)
        else value
    )


def _schema(row: NotificationRow) -> Notification:
    return Notification(
        id=row.id,
        type=NotificationType(row.type),
        created_at=row.created_at.astimezone(UTC),
        read=row.read_at is not None,
        **{field: row.payload.get(field) for field in FACT_FIELDS},
    )


def _deliver(
    db: Session, row: NotificationRow, complaint_scope: NotificationUrgencyScope
) -> None:
    """Queue the push to every live device of its recipient, if wanted.

    The queued pushes are sent after the session's outermost commit and dropped
    on rollback. A new complaint is only pushed to a recipient whose setting has
    the given urgency scope.
    """
    try:
        type_ = NotificationType(row.type)
        category = CATEGORY_OF_TYPE[type_]
        if (
            type_ == NotificationType.BILL_OVERDUE
            and db.get(UserAccount, row.recipient_id).role != UserRole.TENANT
        ):
            category = NotificationCategory.OVERDUE_BILL
        setting = db.get(SettingRow, (row.recipient_id, category.value))
        if setting is not None and not setting.push_enabled:
            return
        if type_ == NotificationType.COMPLAINT_SUBMITTED:
            scope = (
                NotificationUrgencyScope.ALL_URGENCIES
                if setting is None or setting.urgency_scope is None
                else NotificationUrgencyScope(setting.urgency_scope)
            )
            if scope != complaint_scope:
                return
        devices = db.scalars(
            _active_sessions_of(row.recipient_id).where(
                UserSession.push_token.is_not(None)
            )
        ).all()
        notification = _schema(row)
        sender = push.get_push_sender()
    except Exception:
        logger.exception("Preparing the push of notification %s failed", row.id)
        return
    pending = db.info.setdefault(PENDING_PUSHES, [])
    for device in devices:
        pending.append((device.id, device.push_token, notification, sender))


def _clear_token(session_id: UUID, token: str) -> None:
    """Remove a dead token from its session unless it was replaced meanwhile."""
    with Session(get_engine()) as db:
        db.execute(
            text(
                "UPDATE sessions SET push_token = NULL "
                "WHERE id = :id AND push_token = :token"
            ),
            {"id": session_id, "token": token},
        )
        db.commit()


@event.listens_for(Session, "after_commit")
def _send_pending_pushes(db: Session) -> None:
    """Send the pushes queued on the session once its outermost commit succeeded.

    A failing device is logged and never stops the others; nothing is raised.
    """
    if db.in_nested_transaction():
        # A savepoint was released; the outer transaction may still roll back.
        return
    for session_id, token, notification, sender in db.info.pop(PENDING_PUSHES, []):
        try:
            sender.send(token, notification)
        except push.InvalidPushToken:
            try:
                _clear_token(session_id, token)
            except Exception:
                logger.exception("Removing a dead push token failed")
        except Exception:
            logger.exception("Pushing notification %s failed", notification.id)


@event.listens_for(Session, "after_rollback")
def _drop_pending_pushes(db: Session) -> None:
    db.info.pop(PENDING_PUSHES, None)


def notify(
    db: Session,
    recipient_ids: list[UUID],
    type_: NotificationType,
    property_id: UUID | None,
    *,
    rent_bill: ApiModel | None = None,
    complaint: ApiModel | None = None,
    tenant: ApiModel | None = None,
    room: ApiModel | None = None,
    property_: ApiModel | None = None,
    actor_name: str | None = None,
) -> None:
    """Store one notification per recipient and push it to their devices.

    The facts are copied now, so later changes never alter the notification.
    Storing happens in a savepoint and flushes without committing. Nothing is
    raised: a failure is logged and the event that caused it goes on.
    """
    facts = {
        "rent_bill": rent_bill,
        "complaint": complaint,
        "tenant": tenant,
        "room": room,
        "property": property_,
        "actor_name": actor_name,
    }
    payload = {name: _fact(value) for name, value in facts.items()}
    try:
        rows = [
            NotificationRow(
                recipient_id=recipient_id,
                type=type_.value,
                property_id=property_id,
                payload=payload,
            )
            for recipient_id in recipient_ids
        ]
        with db.begin_nested():
            db.add_all(rows)
    except Exception:
        logger.exception("Storing %s notifications failed", type_.value)
        return
    for row in rows:
        _deliver(db, row, NotificationUrgencyScope.ALL_URGENCIES)


def push_high_urgency_complaint(db: Session, complaint_id: UUID) -> None:
    """Push the stored new-complaint notifications to recipients who want only high urgency.

    Called once the complaint is known to be of high urgency. Creates nothing
    and never raises.
    """
    try:
        rows = db.scalars(
            select(NotificationRow).where(
                NotificationRow.type == NotificationType.COMPLAINT_SUBMITTED.value,
                NotificationRow.payload["complaint"]["complaintId"].as_string()
                == str(complaint_id),
            )
        ).all()
    except Exception:
        logger.exception(
            "Finding the notifications of complaint %s failed", complaint_id
        )
        return
    for row in rows:
        _deliver(db, row, NotificationUrgencyScope.HIGH_ONLY)


def _unnotified_bills(db: Session, type_: NotificationType) -> list:
    """Return the rows of unpaid or rejected bills of active leases never notified as `type_`."""
    from app.services import rent_bills

    already = (
        select(NotificationRow.id)
        .where(
            NotificationRow.type == type_.value,
            NotificationRow.payload["rent_bill"]["rentBillId"].as_string()
            == cast(RentBill.id, String),
        )
        .exists()
    )
    query = rent_bills._rows().where(
        RentBill.payment_status.in_([s.value for s in rent_bills.UPLOADABLE]),
        Lease.ended_at.is_(None),
        ~already,
    )
    return [tuple(row) for row in db.execute(query)]


def _notify_bill(
    db: Session, row: tuple, type_: NotificationType, recipients: list[UUID] | None
) -> None:
    """Notify the bill's tenant, and when `recipients` is given also those, of `type_`."""
    from app.services import rent_bills

    bill = row[0]
    summary = rent_bills._summary(row, rent_bills.today_jakarta(), False)
    facts = NotificationRentBill(
        rent_bill_id=bill.id,
        period_start=bill.period_start,
        period_end=bill.period_end,
        due_date=bill.due_date,
        amount=bill.amount,
        payment_status=summary.payment.status,
        payment_method=None,
        reason=None,
        days_overdue=summary.days_overdue,
    )
    prop = summary.property
    notify(
        db,
        [row[4].id],
        type_,
        prop.id,
        rent_bill=facts,
        room=summary.room,
        property_=prop,
    )
    if recipients:
        notify(
            db,
            recipients,
            type_,
            prop.id,
            rent_bill=facts,
            tenant=summary.tenant,
            room=summary.room,
            property_=prop,
        )


def notify_bills_issued(db: Session, bill_ids: list[UUID]) -> None:
    """Tell the tenant of each given bill that it was issued.

    Only the tenant is notified. A failure for one bill is logged and never
    stops the others or raises.
    """
    from app.services import rent_bills

    if not bill_ids:
        return
    rows = [
        tuple(row)
        for row in db.execute(rent_bills._rows().where(RentBill.id.in_(bill_ids)))
    ]
    for row in rows:
        try:
            _notify_bill(db, row, NotificationType.BILL_ISSUED, None)
        except Exception:
            logger.exception("Notifying about the new bill %s failed", row[0].id)


def send_due_date_reminders(db: Session) -> int:
    """Remind the tenant of each unpaid or rejected bill due within three days.

    A bill is reminded once, and only when it was issued at least three days
    before its due date (Asia/Jakarta calendar). Only bills of active leases
    count. Flushes, never commits, and returns the number of bills reminded.
    """
    from app.services import rent_bills

    today = rent_bills.today_jakarta()
    count = 0
    for row in _unnotified_bills(db, NotificationType.DUE_DATE_REMINDER):
        bill = row[0]
        lead = bill.due_date - timedelta(days=REMINDER_DAYS)
        issued = bill.created_at.astimezone(rent_bills.TIMEZONE).date()
        if lead <= today < bill.due_date and issued <= lead:
            _notify_bill(db, row, NotificationType.DUE_DATE_REMINDER, None)
            count += 1
    db.flush()
    return count


def send_overdue_notices(db: Session) -> int:
    """Tell the tenant, the Owner and the assigned Managers of each overdue bill.

    Covers unpaid or rejected bills of active leases past their due date, once
    per bill. Flushes, never commits, and returns the number of bills notified.
    """
    from app.services import rent_bills

    today = rent_bills.today_jakarta()
    count = 0
    for row in _unnotified_bills(db, NotificationType.BILL_OVERDUE):
        if today > row[0].due_date:
            management = management_of(db, row[3].id)
            _notify_bill(db, row, NotificationType.BILL_OVERDUE, management)
            count += 1
    db.flush()
    return count


def _visible_to(user: UserAccount) -> Select[tuple[NotificationRow]]:
    """Select the user's notifications they may see.

    A Manager does not see those of properties they are no longer assigned to.
    """
    query = select(NotificationRow).where(NotificationRow.recipient_id == user.id)
    if user.role == UserRole.MANAGER:
        query = query.where(
            or_(
                NotificationRow.property_id.is_(None),
                NotificationRow.property_id.in_(
                    select(ManagerAssignment.property_id).where(
                        ManagerAssignment.manager_id == user.id
                    )
                ),
            )
        )
    return query


def list_notifications(db: Session, user: UserAccount) -> NotificationList:
    """List the user's visible notifications, newest first, with the unread count."""
    rows = db.scalars(
        _visible_to(user).order_by(
            NotificationRow.created_at.desc(), NotificationRow.id.desc()
        )
    ).all()
    return NotificationList(
        items=[_schema(row) for row in rows],
        unread_count=sum(row.read_at is None for row in rows),
    )


def mark_read(db: Session, user: UserAccount, notification_id: UUID) -> Notification:
    """Mark one of the user's visible notifications read; the first read time is kept.

    Raises 404 NOTIFICATION_NOT_FOUND for an unknown, foreign or hidden notification.
    """
    row = db.scalars(
        _visible_to(user).where(NotificationRow.id == notification_id)
    ).first()
    if row is None:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        db.flush()
    return _schema(row)


def mark_all_read(db: Session, user: UserAccount) -> None:
    """Mark the user's visible unread notifications read."""
    now = datetime.now(UTC)
    for row in db.scalars(_visible_to(user).where(NotificationRow.read_at.is_(None))):
        row.read_at = now
    db.flush()


def get_settings(db: Session, user: UserAccount) -> NotificationSettings:
    """Return the user's push settings in the order of their role's categories.

    A category never saved is on, and newComplaint then covers all urgencies.
    """
    stored = {
        setting.category: setting
        for setting in db.scalars(
            select(SettingRow).where(SettingRow.user_id == user.id)
        )
    }
    items = []
    for category in CATEGORIES_OF_ROLE[user.role]:
        setting = stored.get(category.value)
        scope = (
            NotificationUrgencyScope.ALL_URGENCIES
            if category == NotificationCategory.NEW_COMPLAINT
            else None
        )
        items.append(
            NotificationSettingItem(
                category=category,
                push_enabled=True if setting is None else setting.push_enabled,
                urgency_scope=scope
                if setting is None or setting.urgency_scope is None
                else NotificationUrgencyScope(setting.urgency_scope),
            )
        )
    return NotificationSettings(items=items)


def replace_settings(
    db: Session, user: UserAccount, data: NotificationSettingsInput
) -> NotificationSettings:
    """Replace the user's push settings and return them.

    Flushes, never commits. Raises 422 NOTIFICATION_CATEGORIES_INVALID unless the
    items hold exactly the categories of the user's role once each, and 422
    VALIDATION_FAILED on `items.N.urgencyScope` unless newComplaint, and only it,
    has an urgency scope.
    """
    if sorted(item.category for item in data.items) != sorted(
        CATEGORIES_OF_ROLE[user.role]
    ):
        raise ApiError(422, "NOTIFICATION_CATEGORIES_INVALID", field="items")
    for index, item in enumerate(data.items):
        is_new_complaint = item.category == NotificationCategory.NEW_COMPLAINT
        if is_new_complaint != (item.urgency_scope is not None):
            raise ApiError(
                422, "VALIDATION_FAILED", field=f"items.{index}.urgencyScope"
            )
    for item in data.items:
        db.merge(
            SettingRow(
                user_id=user.id,
                category=item.category.value,
                push_enabled=item.push_enabled,
                urgency_scope=item.urgency_scope and item.urgency_scope.value,
            )
        )
    db.flush()
    return get_settings(db, user)


def register_push_token(db: Session, session: UserSession, token: str) -> None:
    """Store the push token of the session, replacing any earlier one. Flushes."""
    session.push_token = token
    db.flush()
