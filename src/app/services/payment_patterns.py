"""Payment pattern facts of the tenants of a property."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import get_accessible_property
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


def compute_payment_facts(bills: Iterable, today: date) -> PaymentFacts:
    """Derive payment facts from the bills of one lease, as of a date.

    A bill is overdue when it is unpaid or rejected and past its due date.
    The counted bills are the latest six paid or overdue ones by due date. A
    counted bill is late when paid after its due date or overdue. The average
    days late covers late bills only, rounded half up. Arrears sum all overdue
    bills. The tenant is at risk with two late counted bills or any bill more
    than seven days overdue.
    """
    unsettled = (PaymentStatus.UNPAID, PaymentStatus.REJECTED)
    overdue = [b for b in bills if b.payment_status in unsettled and today > b.due_date]
    paid = [b for b in bills if b.payment_status == PaymentStatus.PAID]
    counted = sorted(
        paid + overdue, key=lambda b: (b.due_date, b.period_start), reverse=True
    )[:COUNTED_BILLS]
    days_late = []
    for b in counted:
        if b in overdue:
            days_late.append((today - b.due_date).days)
        elif b.paid_on is not None and b.paid_on > b.due_date:
            days_late.append((b.paid_on - b.due_date).days)
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
    today = rent_bills.today_jakarta()
    items = []
    for _, account, lease, room in found:
        facts = compute_payment_facts(bills[lease.id], today)
        items.append(
            PaymentPattern(
                tenant=TenantRef(id=account.id, name=account.name),
                room=RoomRef(id=room.id, number=room.number),
                on_time_count=facts.on_time_count,
                counted_bill_count=facts.counted_bill_count,
                average_days_late=facts.average_days_late,
                arrears=facts.arrears,
                at_risk=facts.at_risk,
                summary=None,
                summary_withheld=False,
            )
        )
    return PaymentPatternList(items=items)
