"""Payment pattern facts of the tenants of a property."""

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.access import get_accessible_property
from app.db import get_engine
from app.models import Lease as LeaseRow
from app.models import PaymentPatternSummary as SummaryRow
from app.models import Property as PropertyRow
from app.models import RentBill as RentBillRow
from app.models import Room as RoomRow
from app.models import UserAccount
from app.schemas.payments import (
    PaymentPattern,
    PaymentPatternList,
    PaymentStatus,
    TenantRef,
)
from app.schemas.tenants import RoomRef
from app.services import rent_bills, tenants
from app.services.rooms import natural_number_key
from app.services.subscriptions import has_active_subscription

if TYPE_CHECKING:
    from app.ai.summarizer import PaymentPatternSummarizer

logger = logging.getLogger(__name__)

# Looked up when a summary is generated, so tests can change it.
SUMMARY_TIMEOUT_SECONDS = 10.0
MAX_SUMMARY_LENGTH = 500
COUNTED_BILLS = 6
LATE_BILLS_AT_RISK = 2
DAYS_OVERDUE_AT_RISK = 7


@dataclass(frozen=True)
class PaymentFacts:
    """What a lease's bills say about how its tenant pays."""

    on_time_count: int
    counted_bill_count: int
    average_days_late: int
    arrears: int
    at_risk: bool


@dataclass(frozen=True)
class CountedBill:
    """A bill that counts towards the payment facts, with how late it was."""

    due_date: date
    status: PaymentStatus
    days_late: int


def _overdue(bills: Iterable, today: date) -> list:
    unsettled = (PaymentStatus.UNPAID, PaymentStatus.REJECTED)
    return [b for b in bills if b.payment_status in unsettled and today > b.due_date]


def _counted(bills: list, today: date, overdue: list) -> list[tuple]:
    """Pair the latest six paid or overdue bills, newest first, with days late."""
    paid = [b for b in bills if b.payment_status == PaymentStatus.PAID]
    latest = sorted(
        paid + overdue, key=lambda b: (b.due_date, b.period_start), reverse=True
    )[:COUNTED_BILLS]
    overdue_ids = {id(b) for b in overdue}
    result = []
    for b in latest:
        if id(b) in overdue_ids:
            late = (today - b.due_date).days
        elif b.paid_on is not None and b.paid_on > b.due_date:
            late = (b.paid_on - b.due_date).days
        else:
            late = 0
        result.append((b, late))
    return result


def counted_bills(bills: Iterable, today: date) -> list[CountedBill]:
    """List the counted bills of one lease as of a date, newest first.

    The counting and lateness rules are those of `compute_payment_facts`. A
    bill that is not late has zero days late.
    """
    bills = list(bills)
    return [
        CountedBill(b.due_date, PaymentStatus(b.payment_status), late)
        for b, late in _counted(bills, today, _overdue(bills, today))
    ]


def compute_payment_facts(bills: Iterable, today: date) -> PaymentFacts:
    """Derive payment facts from the bills of one lease, as of a date.

    A bill is overdue when it is unpaid or rejected and past its due date.
    The counted bills are the latest six paid or overdue ones by due date. A
    counted bill is late when paid after its due date or overdue. The average
    days late covers late bills only, rounded half up. Arrears sum all overdue
    bills. The tenant is at risk with two late counted bills or any bill more
    than seven days overdue.
    """
    bills = list(bills)
    overdue = _overdue(bills, today)
    counted = _counted(bills, today, overdue)
    days_late = [late for _, late in counted if late > 0]
    n = len(days_late)
    return PaymentFacts(
        on_time_count=len(counted) - n,
        counted_bill_count=len(counted),
        average_days_late=(2 * sum(days_late) + n) // (2 * n) if n else 0,
        arrears=sum(b.amount for b in overdue),
        at_risk=n >= LATE_BILLS_AT_RISK
        or any((today - b.due_date).days > DAYS_OVERDUE_AT_RISK for b in overdue),
    )


def list_payment_patterns(
    db: Session, user: UserAccount, property_id: UUID
) -> PaymentPatternList:
    """Give the payment facts of each tenant with an active lease in a property.

    Tenants are ordered by room number, then name. Raises 404
    PROPERTY_NOT_FOUND for an unknown or inaccessible property.
    """
    parent = get_accessible_property(db, user, property_id)
    found = sorted(
        tenants._find(db, RoomRow.property_id == parent.id),
        key=lambda f: (natural_number_key(f[3].number), f[1].name, f[1].id),
    )
    bills: dict[UUID, list[RentBillRow]] = {f[2].id: [] for f in found}
    for bill in db.scalars(
        select(RentBillRow).where(RentBillRow.lease_id.in_(list(bills)))
    ):
        bills[bill.lease_id].append(bill)
    summaries = dict(
        db.execute(
            select(SummaryRow.lease_id, SummaryRow.summary).where(
                SummaryRow.lease_id.in_(list(bills))
            )
        ).all()
    )
    subscribed = has_active_subscription(db, parent.owner_id)
    today = rent_bills.today_jakarta()
    items = []
    for _, account, lease, room in found:
        facts = compute_payment_facts(bills[lease.id], today)
        stored = summaries.get(lease.id)
        items.append(
            PaymentPattern(
                tenant=TenantRef(id=account.id, name=account.name),
                room=RoomRef(id=room.id, number=room.number),
                on_time_count=facts.on_time_count,
                counted_bill_count=facts.counted_bill_count,
                average_days_late=facts.average_days_late,
                arrears=facts.arrears,
                at_risk=facts.at_risk,
                summary=stored if subscribed else None,
                summary_withheld=stored is not None and not subscribed,
            )
        )
    return PaymentPatternList(items=items)


def clear_summary(db: Session, lease_id: UUID) -> None:
    """Delete the stored summary of a lease. Flushes, never commits."""
    db.execute(delete(SummaryRow).where(SummaryRow.lease_id == lease_id))


def _snapshot(db: Session, lease_id: UUID) -> tuple[PaymentFacts, list[CountedBill]]:
    bills = db.scalars(
        select(RentBillRow).where(RentBillRow.lease_id == lease_id)
    ).all()
    today = rent_bills.today_jakarta()
    return compute_payment_facts(bills, today), counted_bills(bills, today)


def _summarize_within_timeout(
    summarizer: PaymentPatternSummarizer,
    facts: PaymentFacts,
    bills: list[CountedBill],
) -> str:
    """Run the blocking summarizer in a worker thread and wait for its result.

    A result arriving after the timeout is discarded.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(summarizer.summarize, facts, bills)
        return future.result(timeout=SUMMARY_TIMEOUT_SECONDS)
    finally:
        executor.shutdown(wait=False)


def regenerate_summary(lease_id: UUID, summarizer: PaymentPatternSummarizer) -> None:
    """Generate and store the summary of a lease with its own database session.

    Nothing happens for a missing or ended lease, or when the property's Owner
    has no active subscription. The result is stored only if it is non-empty,
    at most 500 characters, and the facts and counted bills are still those it
    was generated from. Never raises; failures are logged and store nothing.
    """
    try:
        with Session(get_engine()) as db:
            found = db.execute(
                select(LeaseRow, PropertyRow.owner_id)
                .join(RoomRow, RoomRow.id == LeaseRow.room_id)
                .join(PropertyRow, PropertyRow.id == RoomRow.property_id)
                .where(LeaseRow.id == lease_id)
            ).first()
            if (
                found is None
                or found[0].ended_at is not None
                or not has_active_subscription(db, found[1])
            ):
                return
            sent = _snapshot(db, lease_id)
        text = _summarize_within_timeout(summarizer, *sent).strip()
        if not text or len(text) > MAX_SUMMARY_LENGTH:
            logger.warning("The summary of lease %s is unusable", lease_id)
            return
        with Session(get_engine()) as db:
            db.execute(
                select(LeaseRow.id).where(LeaseRow.id == lease_id).with_for_update()
            )
            if _snapshot(db, lease_id) != sent:
                return
            db.merge(
                SummaryRow(
                    lease_id=lease_id, summary=text, generated_at=datetime.now(UTC)
                )
            )
            db.commit()
    except Exception:
        logger.exception("Summarizing the payment pattern of %s failed", lease_id)
