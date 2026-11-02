"""Helpers shared by the payment pattern summary tests."""

import time
from datetime import UTC, datetime, timedelta

from rent_bill_support import days_ago
from sqlalchemy import select
from sqlalchemy.orm import Session

SUMMARY_TEXT = "Penyewa membayar tepat waktu."


class FakeSummarizer:
    """A payment pattern summarizer that records calls and can return, raise or stall.

    `on_call` runs at the start of every call, before any delay or error.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.result = SUMMARY_TEXT
        self.error: BaseException | None = None
        self.delay: float = 0.0
        self.on_call = None

    def summarize(self, facts, bills) -> str:
        self.calls.append((facts, list(bills)))
        if self.on_call is not None:
            self.on_call()
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


def store_summary(database, lease, text: str = "Stored summary.") -> None:
    """Commit a stored summary for a lease."""
    from app.models import PaymentPatternSummary

    with Session(database) as db:
        db.add(
            PaymentPatternSummary(
                lease_id=lease.id, summary=text, generated_at=datetime.now(UTC)
            )
        )
        db.commit()


def stored_summary(database, lease):
    """The stored summary row of a lease, or None."""
    from app.models import PaymentPatternSummary

    with Session(database, expire_on_commit=False) as db:
        return db.get(PaymentPatternSummary, lease.id)


def all_summaries(database) -> list[tuple]:
    """Every stored summary as (lease id, text, generation time), ordered by lease."""
    from app.models import PaymentPatternSummary

    with Session(database) as db:
        rows = db.scalars(
            select(PaymentPatternSummary).order_by(PaymentPatternSummary.lease_id)
        )
        return [(r.lease_id, r.summary, r.generated_at) for r in rows]


def add_bill(
    make_rent_bill, lease, slot, due_ago, status="unpaid", *, late=0, amount=1000000
):
    """Add a bill due `due_ago` days ago; periods of different slots never overlap.

    Slot 0 is the latest period. A paid bill is paid `late` days after its due
    date.
    """
    start = days_ago(30 * (slot + 1))
    due = days_ago(due_ago)
    extra = {}
    if status == "paid":
        extra = {"method": "transfer", "paid_on": due + timedelta(days=late)}
    if status == "rejected":
        extra = {"rejection_reason": "Blurry photo."}
    return make_rent_bill(
        lease,
        period_start=start,
        period_end=start + timedelta(days=29),
        due_date=due,
        amount=amount,
        status=status,
        **extra,
    )
