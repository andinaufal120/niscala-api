"""Helpers shared by the rent bill generation tests."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session


def generate(database) -> int:
    """Run the generator in its own session and commit, as the daily job does."""
    from app.services import rent_bills

    with Session(database) as db:
        count = rent_bills.generate_rent_bills(db)
        db.commit()
    return count


def stored_bills(database, lease=None) -> list:
    """Stored rent bills, oldest period first, of one lease or of all leases."""
    from app.models import RentBill

    query = select(RentBill).order_by(RentBill.period_start, RentBill.id)
    if lease is not None:
        query = query.where(RentBill.lease_id == lease.id)
    with Session(database, expire_on_commit=False) as db:
        return list(db.scalars(query))


def periods(database, lease) -> list[tuple[date, date]]:
    """`(period_start, period_end)` of every stored bill of a lease."""
    return [(b.period_start, b.period_end) for b in stored_bills(database, lease)]


def only_bill(database, lease):
    """The one stored bill of a lease."""
    (bill,) = stored_bills(database, lease)
    return bill


def edit_lease(database, lease, **columns) -> None:
    from app.models import Lease

    with Session(database) as db:
        row = db.get(Lease, lease.id)
        for name, value in columns.items():
            setattr(row, name, value)
        db.commit()


def freeze_date(monkeypatch, day: date) -> None:
    """Make the date the generator treats as today in Jakarta `day`."""
    monkeypatch.setattr("app.services.rent_bills.today_jakarta", lambda: day)


def freeze_instant(monkeypatch, instant: datetime) -> None:
    """Make the clock of the rent bill module read `instant` (a UTC moment).

    `today_jakarta` is left alone, so the date is derived from the instant in
    the Asia/Jakarta calendar.
    """
    assert instant.tzinfo is not None

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant

    monkeypatch.setattr("app.services.rent_bills.datetime", FrozenDatetime)


def utc(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def build_site(make_user, make_property, make_room, assign_manager, sign_in):
    """An owner, an assigned manager and a property with one room, all signed in."""
    from app.schemas.auth import UserRole

    owner = make_user(name="Rina Owner")
    manager = make_user(name="Mira Manager", role=UserRole.MANAGER)
    prop = make_property(owner, name="Kos Melati")
    assign_manager(manager, prop)
    room = make_room(prop, number="A1")
    return SimpleNamespace(
        owner=owner,
        manager=manager,
        prop=prop,
        room=room,
        owner_in=sign_in(owner),
        manager_in=sign_in(manager),
    )
