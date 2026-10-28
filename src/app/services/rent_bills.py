"""Listing and reading rent bills, and moving them through payment."""

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.access import accessible_properties
from app.errors import ApiError
from app.models import Lease as LeaseRow
from app.models import Property as PropertyRow
from app.models import RentBill as RentBillRow
from app.models import RentBillReceipt as ReceiptRow
from app.models import RentBillStatusChange as StatusChangeRow
from app.models import Room as RoomRow
from app.models import UserAccount
from app.schemas.auth import UserRole
from app.schemas.complaints import PropertyRef
from app.schemas.notifications import NotificationRentBill, NotificationType
from app.schemas.payments import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    PaymentStatusChange,
    PaymentStatusChangeInput,
    RentBill,
    RentBillList,
    RentBillSummary,
    TenantRef,
)
from app.schemas.properties import BankAccount
from app.schemas.tenants import BillingCycle, RoomRef
from app.services import leases, notifications

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Jakarta")
MAX_RECEIPT_BYTES = 5 * 1024 * 1024
RECEIPT_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
# A receipt can be sent for a bill in one of these statuses.
UPLOADABLE = (PaymentStatus.UNPAID, PaymentStatus.REJECTED)
# Seeded bills: every fourth is paid this many days after its due date.
SEED_LATE_EVERY = 4
SEED_LATE_DAYS = 10

type Row = tuple[RentBillRow, LeaseRow, RoomRow, PropertyRow, UserAccount]


def today_jakarta() -> date:
    """Return today's date in Asia/Jakarta, the zone every bill date is read in."""
    return datetime.now(TIMEZONE).date()


def notify_status_change(
    db: Session, bill: RentBillRow, change: StatusChangeRow
) -> None:
    """Tell the tenant or management about a payment status change.

    A receipt awaiting verification notifies the property's Owner and Managers.
    Any other status notifies the bill's tenant, and a cash payment recorded by
    a Manager (not a manual change) also notifies the Owner.
    """
    row = tuple(db.execute(_rows().where(RentBillRow.id == bill.id)).one())
    summary = _summary(row, today_jakarta(), False)
    status = PaymentStatus(change.status)
    facts = NotificationRentBill(
        rent_bill_id=bill.id,
        period_start=bill.period_start,
        period_end=bill.period_end,
        due_date=bill.due_date,
        amount=bill.amount,
        payment_status=status,
        payment_method=summary.payment.method,
        reason=change.reason,
        days_overdue=summary.days_overdue,
    )
    prop = summary.property
    if status == PaymentStatus.AWAITING_VERIFICATION:
        notifications.notify(
            db,
            notifications.management_of(db, prop.id),
            NotificationType.RECEIPT_UPLOADED,
            prop.id,
            rent_bill=facts,
            tenant=summary.tenant,
            room=summary.room,
            property_=prop,
        )
        return
    notifications.notify(
        db,
        [summary.tenant.id],
        NotificationType.PAYMENT_STATUS_CHANGED,
        prop.id,
        rent_bill=facts,
        room=summary.room,
        property_=prop,
    )
    actor = db.get(UserAccount, change.actor_id)
    if (
        status == PaymentStatus.PAID
        and summary.payment.method == PaymentMethod.CASH
        and not change.manual
        and actor.role == UserRole.MANAGER
    ):
        notifications.notify(
            db,
            [row[3].owner_id],
            NotificationType.CASH_PAYMENT_RECORDED,
            prop.id,
            rent_bill=facts,
            tenant=summary.tenant,
            room=summary.room,
            property_=prop,
            actor_name=actor.name,
        )


def regenerate_payment_pattern(lease_id: UUID) -> None:
    """Refresh the payment pattern of the lease's tenant after a payment change."""


def _rows() -> Select[Row]:
    return (
        select(RentBillRow, LeaseRow, RoomRow, PropertyRow, UserAccount)
        .join(LeaseRow, LeaseRow.id == RentBillRow.lease_id)
        .join(RoomRow, RoomRow.id == LeaseRow.room_id)
        .join(PropertyRow, PropertyRow.id == RoomRow.property_id)
        .join(UserAccount, UserAccount.id == LeaseRow.tenant_id)
    )


def _readable_by(user: UserAccount) -> Select[Row]:
    """Select the bills the user may read: a tenant's own active lease, or accessible properties."""
    if user.role == UserRole.TENANT:
        return _rows().where(LeaseRow.tenant_id == user.id, LeaseRow.ended_at.is_(None))
    properties = accessible_properties(user).subquery()
    return _rows().where(PropertyRow.id.in_(select(properties.c.id)))


def _find(
    db: Session, user: UserAccount, rent_bill_id: UUID, lock: bool = False
) -> Row:
    query = _readable_by(user).where(RentBillRow.id == rent_bill_id)
    if lock:
        query = query.with_for_update(of=RentBillRow)
    row = db.execute(query).first()
    if row is None:
        raise ApiError(404, "RENT_BILL_NOT_FOUND")
    return tuple(row)


def _bank_account(prop: PropertyRow) -> BankAccount | None:
    if prop.bank_name is None:
        return None
    return BankAccount(
        bank_name=prop.bank_name,
        account_number=prop.bank_account_number or "",
        account_holder_name=prop.bank_account_holder_name or "",
    )


def _is_current(bill: RentBillRow, today: date) -> bool:
    return bill.period_start <= today <= bill.period_end


def _summary(row: Row, today: date, has_receipt: bool) -> RentBillSummary:
    bill, _, room, prop, tenant = row
    status = PaymentStatus(bill.payment_status)
    unsettled = status in UPLOADABLE
    current = _is_current(bill, today)
    return RentBillSummary(
        id=bill.id,
        tenant=TenantRef(id=tenant.id, name=tenant.name),
        room=RoomRef(id=room.id, number=room.number),
        property=PropertyRef(id=prop.id, name=prop.name),
        period_start=bill.period_start,
        period_end=bill.period_end,
        due_date=bill.due_date,
        amount=bill.amount,
        payment=Payment(
            status=status,
            method=bill.payment_method and PaymentMethod(bill.payment_method),
            paid_on=bill.paid_on,
            has_receipt=has_receipt,
            rejection_reason=bill.rejection_reason,
        ),
        days_overdue=max(0, (today - bill.due_date).days) if unsettled else 0,
        is_current=current,
        can_upload_receipt=unsettled and prop.bank_name is not None,
    )


def _with_receipt(db: Session, bill_ids: Sequence[UUID]) -> set[UUID]:
    return set(
        db.scalars(
            select(ReceiptRow.rent_bill_id).where(ReceiptRow.rent_bill_id.in_(bill_ids))
        )
    )


def _detail(db: Session, row: Row) -> RentBill:
    bill = row[0]
    summary = _summary(row, today_jakarta(), bool(_with_receipt(db, [bill.id])))
    changes = db.execute(
        select(StatusChangeRow, UserAccount.name)
        .outerjoin(UserAccount, UserAccount.id == StatusChangeRow.actor_id)
        .where(StatusChangeRow.rent_bill_id == bill.id)
        .order_by(StatusChangeRow.changed_at, StatusChangeRow.id)
    )
    return RentBill(
        **summary.__dict__,
        bank_account=_bank_account(row[3]),
        status_changes=[
            PaymentStatusChange(
                status=PaymentStatus(change.status),
                method=change.method and PaymentMethod(change.method),
                reason=change.reason,
                manual=change.manual,
                actor_name=actor_name,
                changed_at=change.changed_at,
            )
            for change, actor_name in changes
        ],
    )


def list_rent_bills(
    db: Session,
    user: UserAccount,
    tenant_id: UUID | None,
    property_id: UUID | None,
    payment_statuses: list[PaymentStatus] | None,
) -> RentBillList:
    """List the bills the user may read, newest period first, then by id.

    Tenants get the bills of their active lease. Owners and managers get the
    bills of their accessible properties. Filters narrow the list and never
    widen access, so one that matches nothing readable gives an empty list.
    """
    query = _readable_by(user)
    if tenant_id is not None:
        query = query.where(LeaseRow.tenant_id == tenant_id)
    if property_id is not None:
        query = query.where(PropertyRow.id == property_id)
    if payment_statuses:
        query = query.where(
            RentBillRow.payment_status.in_([s.value for s in payment_statuses])
        )
    rows = [
        tuple(row)
        for row in db.execute(
            query.order_by(RentBillRow.period_start.desc(), RentBillRow.id)
        )
    ]
    with_receipt = _with_receipt(db, [row[0].id for row in rows])
    today = today_jakarta()
    return RentBillList(
        items=[_summary(row, today, row[0].id in with_receipt) for row in rows]
    )


def get_rent_bill(db: Session, user: UserAccount, rent_bill_id: UUID) -> RentBill:
    """Return a bill the user may read, with its bank account and status history.

    Raises 404 RENT_BILL_NOT_FOUND for an unknown or unreadable bill.
    """
    return _detail(db, _find(db, user, rent_bill_id))


def get_receipt(db: Session, user: UserAccount, rent_bill_id: UUID) -> ReceiptRow:
    """Return the receipt of a bill the user may read.

    Raises 404 RENT_BILL_NOT_FOUND for an unknown or unreadable bill and 404
    RECEIPT_NOT_FOUND for a bill without a receipt.
    """
    bill = _find(db, user, rent_bill_id)[0]
    receipt = db.get(ReceiptRow, bill.id)
    if receipt is None:
        raise ApiError(404, "RECEIPT_NOT_FOUND")
    return receipt


def _record(
    db: Session,
    bill: RentBillRow,
    actor: UserAccount,
    status: PaymentStatus,
    *,
    method: PaymentMethod | None = None,
    paid_on: date | None = None,
    rejection_reason: str | None = None,
    reason: str | None = None,
    manual: bool = False,
) -> None:
    """Set the payment state of a bill and append the matching history entry.

    Fields not given are cleared, so the state never keeps a method, payment
    date or rejection reason from an earlier status.
    """
    bill.payment_status = status.value
    bill.payment_method = method and method.value
    bill.paid_on = paid_on
    bill.rejection_reason = rejection_reason
    change = StatusChangeRow(
        rent_bill_id=bill.id,
        status=status.value,
        method=method and method.value,
        reason=reason,
        manual=manual,
        actor_id=actor.id,
        changed_at=datetime.now(UTC),
    )
    db.add(change)
    db.flush()
    try:
        notify_status_change(db, bill, change)
    except Exception:
        logger.exception("Notifying about the status change of %s failed", bill.id)
    regenerate_payment_pattern(bill.lease_id)


def _receipt_type(content: bytes) -> str:
    """Return the image type of the bytes, decided from their signature."""
    if len(content) > MAX_RECEIPT_BYTES:
        raise ApiError(422, "RECEIPT_TOO_LARGE", field="file")
    for signature, content_type in RECEIPT_SIGNATURES.items():
        if content.startswith(signature):
            return content_type
    raise ApiError(422, "RECEIPT_TYPE_INVALID", field="file")


def upload_receipt(
    db: Session, user: UserAccount, rent_bill_id: UUID, content: bytes
) -> RentBill:
    """Store a transfer receipt image and mark the bill as awaiting verification.

    Only the bill's tenant gets this far; checks in order: bill (404
    RENT_BILL_NOT_FOUND), unpaid or rejected (409
    RENT_BILL_NOT_UPLOADABLE), property bank account (409
    PROPERTY_BANK_ACCOUNT_MISSING), file size (422 RECEIPT_TOO_LARGE) and a PNG
    or JPEG signature (422 RECEIPT_TYPE_INVALID). A new receipt replaces the old
    one and clears a previous rejection reason.
    """
    bill, _, _, prop, _ = _find(db, user, rent_bill_id, lock=True)
    if PaymentStatus(bill.payment_status) not in UPLOADABLE:
        raise ApiError(409, "RENT_BILL_NOT_UPLOADABLE")
    if prop.bank_name is None:
        raise ApiError(409, "PROPERTY_BANK_ACCOUNT_MISSING")
    content_type = _receipt_type(content)
    now = datetime.now(UTC)
    receipt = db.get(ReceiptRow, bill.id)
    if receipt is None:
        db.add(
            ReceiptRow(
                rent_bill_id=bill.id,
                content=content,
                content_type=content_type,
                uploaded_at=now,
            )
        )
    else:
        receipt.content = content
        receipt.content_type = content_type
        receipt.uploaded_at = now
    _record(db, bill, user, PaymentStatus.AWAITING_VERIFICATION)
    return get_rent_bill(db, user, rent_bill_id)


def _require_awaiting(bill: RentBillRow) -> None:
    if bill.payment_status != PaymentStatus.AWAITING_VERIFICATION:
        raise ApiError(409, "RENT_BILL_NOT_AWAITING_VERIFICATION")


def _require_reason(reason: str) -> None:
    if not reason:
        raise ApiError(422, "REASON_REQUIRED", field="reason")


def _require_not_future(received_on: date) -> None:
    if received_on > today_jakarta():
        raise ApiError(422, "RECEIVED_ON_IN_FUTURE", field="receivedOn")


def verify_receipt(db: Session, user: UserAccount, rent_bill_id: UUID) -> RentBill:
    """Accept the receipt of a bill and mark it paid by transfer.

    The payment date is the Asia/Jakarta date of the upload. Raises 404
    RENT_BILL_NOT_FOUND, or 409 RENT_BILL_NOT_AWAITING_VERIFICATION.
    """
    bill = _find(db, user, rent_bill_id, lock=True)[0]
    _require_awaiting(bill)
    receipt = db.scalars(
        select(ReceiptRow).where(ReceiptRow.rent_bill_id == bill.id)
    ).one()
    _record(
        db,
        bill,
        user,
        PaymentStatus.PAID,
        method=PaymentMethod.TRANSFER,
        paid_on=receipt.uploaded_at.astimezone(TIMEZONE).date(),
    )
    return get_rent_bill(db, user, rent_bill_id)


def reject_receipt(
    db: Session, user: UserAccount, rent_bill_id: UUID, reason: str
) -> RentBill:
    """Reject the receipt of a bill and keep the reason for the tenant.

    Raises 404 RENT_BILL_NOT_FOUND, 422 REASON_REQUIRED for a blank reason, or
    409 RENT_BILL_NOT_AWAITING_VERIFICATION.
    """
    bill = _find(db, user, rent_bill_id, lock=True)[0]
    _require_reason(reason)
    _require_awaiting(bill)
    _record(
        db,
        bill,
        user,
        PaymentStatus.REJECTED,
        rejection_reason=reason,
        reason=reason,
    )
    return get_rent_bill(db, user, rent_bill_id)


def record_cash_payment(
    db: Session, user: UserAccount, rent_bill_id: UUID, received_on: date
) -> RentBill:
    """Mark an unpaid or rejected bill as paid in cash on the given date.

    Raises 404 RENT_BILL_NOT_FOUND, 422 RECEIVED_ON_IN_FUTURE for a date after
    today in Asia/Jakarta, or 409 RENT_BILL_NOT_PAYABLE.
    """
    bill = _find(db, user, rent_bill_id, lock=True)[0]
    _require_not_future(received_on)
    if PaymentStatus(bill.payment_status) not in UPLOADABLE:
        raise ApiError(409, "RENT_BILL_NOT_PAYABLE")
    _record(
        db,
        bill,
        user,
        PaymentStatus.PAID,
        method=PaymentMethod.CASH,
        paid_on=received_on,
    )
    return get_rent_bill(db, user, rent_bill_id)


def change_payment_status(
    db: Session, user: UserAccount, rent_bill_id: UUID, data: PaymentStatusChangeInput
) -> RentBill:
    """Set the payment status of a bill by hand and log it as a manual change.

    Paid needs a method and a payment date; the other statuses accept neither.
    Anything else clears the method and payment date. Raises 404
    RENT_BILL_NOT_FOUND, 422 REASON_REQUIRED, 422 VALIDATION_FAILED for the
    method or date given or missing, 422 STATUS_UNCHANGED, or 422
    RECEIVED_ON_IN_FUTURE.
    """
    bill = _find(db, user, rent_bill_id, lock=True)[0]
    status = PaymentStatus(data.status)
    _require_reason(data.reason)
    paid = status == PaymentStatus.PAID
    if paid != (data.method is not None):
        raise ApiError(422, "VALIDATION_FAILED", field="method")
    if paid != (data.received_on is not None):
        raise ApiError(422, "VALIDATION_FAILED", field="receivedOn")
    if bill.payment_status == status:
        raise ApiError(422, "STATUS_UNCHANGED", field="status")
    if data.received_on is not None:
        _require_not_future(data.received_on)
    _record(
        db,
        bill,
        user,
        status,
        method=data.method,
        paid_on=data.received_on,
        rejection_reason=data.reason if status == PaymentStatus.REJECTED else None,
        reason=data.reason,
        manual=True,
    )
    return get_rent_bill(db, user, rent_bill_id)


def seed_rent_bills(db: Session, lease: LeaseRow, months: int) -> int:
    """Create the missing bills of the latest `months` billing periods of a lease.

    Periods run from the lease start date through the one containing today.
    Past periods are paid by transfer on the due date, every fourth one
    `SEED_LATE_DAYS` days late (a payment date never passes today); the current
    period is unpaid. Periods that
    already have a bill are skipped. Flushes, never commits, and returns the
    number of bills created. The lease needs a start date.
    """
    today = today_jakarta()
    cycle = BillingCycle(lease.billing_cycle)
    starts = []
    while (start := leases.period_start(lease.start_date, cycle, len(starts))) <= today:
        starts.append(start)
    existing = set(
        db.scalars(
            select(RentBillRow.period_start).where(RentBillRow.lease_id == lease.id)
        )
    )
    created = 0
    for number in range(max(0, len(starts) - months), len(starts)):
        if starts[number] in existing:
            continue
        _seed_bill(db, lease, number, current=number == len(starts) - 1)
        created += 1
    db.flush()
    return created


def _seed_bill(db: Session, lease: LeaseRow, number: int, current: bool) -> None:
    cycle = BillingCycle(lease.billing_cycle)
    start = leases.period_start(lease.start_date, cycle, number)
    due_date = start + timedelta(days=lease.grace_period_days)
    created_at = datetime.combine(start, time(), TIMEZONE)
    paid_on = None
    if not current:
        late = (number + 1) % SEED_LATE_EVERY == 0
        paid_on = min(
            due_date + timedelta(days=SEED_LATE_DAYS if late else 0), today_jakarta()
        )
    bill = RentBillRow(
        lease_id=lease.id,
        period_start=start,
        period_end=leases.period_start(lease.start_date, cycle, number + 1)
        - timedelta(days=1),
        due_date=due_date,
        amount=lease.rent,
        payment_status=(PaymentStatus.UNPAID if current else PaymentStatus.PAID).value,
        payment_method=None if current else PaymentMethod.TRANSFER.value,
        paid_on=paid_on,
        created_at=created_at,
    )
    db.add(bill)
    db.flush()
    db.add(
        StatusChangeRow(
            rent_bill_id=bill.id,
            status=PaymentStatus.UNPAID.value,
            manual=False,
            changed_at=created_at,
        )
    )
    if paid_on is not None:
        db.add(
            StatusChangeRow(
                rent_bill_id=bill.id,
                status=PaymentStatus.PAID.value,
                method=PaymentMethod.TRANSFER.value,
                manual=False,
                changed_at=datetime.combine(paid_on, time(12), TIMEZONE),
            )
        )
