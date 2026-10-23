"""Helpers shared by the rent bill endpoint tests."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

RENT_BILLS = "/rent-bills"
JAKARTA = ZoneInfo("Asia/Jakarta")

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
GIF_BYTES = b"GIF89a" + b"\x00" * 32
MEGABYTE = 1024 * 1024

SUMMARY_FIELDS = {
    "id",
    "tenant",
    "room",
    "property",
    "periodStart",
    "periodEnd",
    "dueDate",
    "amount",
    "payment",
    "daysOverdue",
    "isCurrent",
    "canUploadReceipt",
}
DETAIL_FIELDS = SUMMARY_FIELDS | {"bankAccount", "statusChanges"}
# The date the service treats as today in Jakarta, fixed by the `frozen_today` fixture.
TODAY = date(2026, 10, 23)
PAYMENT_FIELDS = {"status", "method", "paidOn", "hasReceipt", "rejectionReason"}
CHANGE_FIELDS = {"status", "method", "reason", "manual", "actorName", "changedAt"}


def today() -> date:
    return TODAY


def png(size: int | None = None) -> bytes:
    """PNG-looking bytes, padded to `size` bytes when given."""
    data = PNG_HEADER + b"\x00" * 24
    return data if size is None else data.ljust(size, b"\x00")


def jpeg(size: int | None = None) -> bytes:
    """JPEG-looking bytes, padded to `size` bytes when given."""
    data = JPEG_HEADER + b"\x00" * 24
    return data if size is None else data.ljust(size, b"\x00")


def at_noon_jakarta(day: date) -> datetime:
    """A moment around midday in Jakarta, so its UTC and Jakarta dates agree."""
    return datetime(day.year, day.month, day.day, 12, tzinfo=JAKARTA).astimezone(UTC)


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    assert value.tzinfo is not None
    return value


def assert_error(response, status: int, code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["field"] == field
    assert body["message"]


def assert_not_found(response) -> None:
    assert_error(response, 404, "RENT_BILL_NOT_FOUND")


def assert_receipt_not_found(response) -> None:
    assert_error(response, 404, "RECEIPT_NOT_FOUND")


def assert_field_error(response, code: str, field: str) -> None:
    assert_error(response, 422, code, field)


def assert_validation_error(response, field: str) -> None:
    assert_error(response, 422, "VALIDATION_FAILED", field)


def assert_refused(response, code: str) -> None:
    """A request refused because of the state of the bill or its property."""
    assert_error(response, 409, code)


def bill_url(bill, suffix: str = "") -> str:
    return f"{RENT_BILLS}/{bill.id}{suffix}"


def stored_bill(database, bill):
    from app.models import RentBill

    with Session(database, expire_on_commit=False) as db:
        return db.get(RentBill, bill.id)


def stored_changes(database, bill=None) -> list:
    """Status change rows, oldest first, of one bill or of all bills."""
    from app.models import RentBillStatusChange

    query = select(RentBillStatusChange).order_by(RentBillStatusChange.changed_at)
    if bill is not None:
        query = query.where(RentBillStatusChange.rent_bill_id == bill.id)
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(query))


def stored_receipts(database) -> list:
    from app.models import RentBillReceipt

    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(select(RentBillReceipt)))


def snapshot(database, bill) -> tuple:
    """Everything stored about a bill, to compare before and after a request."""
    row = stored_bill(database, bill)
    return (
        row.payment_status,
        row.payment_method,
        row.paid_on,
        row.rejection_reason,
        [
            (c.id, c.status, c.method, c.reason, c.manual, c.actor_id)
            for c in stored_changes(database, bill)
        ],
        [(r.content, r.content_type, r.uploaded_at) for r in stored_receipts(database)],
    )


def clear_bank_account(database, prop) -> None:
    from app.models import Property

    with Session(database) as db:
        row = db.get(Property, prop.id)
        row.bank_name = None
        row.bank_account_number = None
        row.bank_account_holder_name = None
        db.commit()


def make_property_view_only(database, prop) -> None:
    from app.models import Property

    with Session(database) as db:
        db.get(Property, prop.id).view_only = True
        db.commit()


def delete_property(database, prop) -> None:
    from app.models import Property

    with Session(database) as db:
        db.get(Property, prop.id).deleted_at = datetime.now(UTC)
        db.commit()


def days_ago(days: int) -> date:
    return today() - timedelta(days=days)


def days_ahead(days: int) -> date:
    return today() + timedelta(days=days)
