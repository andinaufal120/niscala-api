"""Steps shared by the tenancy, bill and payment scenarios.

Everything goes through the public HTTP API. The site built here is smaller than
the seeded world and starts without any tenant, so each scenario sets up exactly
the leases it needs.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from e2e.e2e_people import (
    BANK_ACCOUNT,
    EMERGENCY_CONTACTS,
    Manager,
    Owner,
    Person,
    Tenant,
)

MIB = 1024 * 1024
JAKARTA = ZoneInfo("Asia/Jakarta")


@dataclass
class Site:
    """An Owner on the Basic plan with two properties and a Manager.

    `melati` has a bank account and `anggrek` has none. The Manager is assigned
    to `melati` only. `rooms` maps a room number to the room as the API returned
    it; numbers are unique across both properties.
    """

    owner: Owner
    manager: Manager
    melati: dict
    anggrek: dict
    rooms: dict[str, dict]


def build_site(
    world,
    melati_rooms: tuple[str, ...] = ("A1", "A2", "A3"),
    anggrek_rooms: tuple[str, ...] = ("B1", "B2"),
    base_rate: int = 1_000_000,
) -> Site:
    """Sign up an Owner, subscribe, add both properties, their rooms and a Manager."""
    owner = world.owner_signs_up(email="rina@example.com", name="Rina Owner")
    owner.subscribe("basic")
    melati = owner.add_property(
        "Kos Melati", address="Jl. Melati 5", bank_account=BANK_ACCOUNT
    )
    anggrek = owner.add_property("Kos Anggrek", address="Jl. Anggrek 7")
    rooms = {n: owner.add_room(melati, n, base_rate=base_rate) for n in melati_rooms}
    rooms |= {n: owner.add_room(anggrek, n, base_rate=base_rate) for n in anggrek_rooms}
    manager = world.manager_activates(
        owner.add_manager([melati], name="Mira Manager", phone="081200000001"),
        email="mira@example.com",
    )
    return Site(owner, manager, melati, anggrek, rooms)


def join(
    world,
    owner: Owner,
    room: dict,
    name: str,
    *,
    lease: dict | None = None,
    phone: str = "081211111111",
) -> Tenant:
    """Add a tenant to a room and activate the account with a confirmed email."""
    token = owner.add_tenant(room, name, phone, lease=lease)
    email = f"{name.lower().replace(' ', '.')}@example.com"
    return world.tenant_activates(token, email=email)


def accept_another_tenancy(
    owner: Owner, room: dict, tenant: Tenant, *, lease: dict | None = None
) -> str:
    """Give an existing Tenant account a second tenancy and return its record id."""
    token = owner.add_tenant(room, tenant.name, "081211111111", lease=lease)
    tenant.post(
        "/invitations/acceptances",
        json={"token": str(token), "emergencyContacts": EMERGENCY_CONTACTS},
        expect=204,
    )
    return token.id


def real_today() -> date:
    """The current date in Asia/Jakarta by the wall clock, which the test clock does not move.

    A receipt is dated by the real time it was uploaded, so scenarios about
    the date of an upload start the test clock here.
    """
    return datetime.now(JAKARTA).date()


def run_jobs_on(world, database, day: date) -> None:
    """Make `day` today, run the daily jobs and date the new bills to that day.

    A bill records the real time it was saved, which the clock does not move,
    and the reminder rule reads it as the day the bill was issued. The bills
    this run created are therefore dated 07:00 on `day`, as the scheduled job
    would have saved them, and the jobs run once more so that the rules that
    read the issue date see it (a repeated run changes nothing else). This is
    the one place the scenarios write to the database, because no endpoint
    dates a bill.
    """
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from app.models import RentBill

    world.clock.set(day)
    world.clock.run_daily_jobs()
    issued_at = datetime.combine(day, time(7, 0), tzinfo=JAKARTA)
    with Session(database) as db:
        db.execute(
            update(RentBill)
            .where(RentBill.created_at > issued_at)
            .values(created_at=issued_at)
        )
        db.commit()
    world.clock.run_daily_jobs()


def types_of(person: Person) -> list[str]:
    """The notification types of a person, newest first."""
    return [n["type"] for n in person.notifications()]


def notifications_of(person: Person, type_: str) -> list[dict]:
    """The notifications of one type, newest first."""
    return [n for n in person.notifications() if n["type"] == type_]


def bill_of(person: Person, name: str, **params) -> dict:
    """The only bill of the tenant called `name` in the person's bill list."""
    found = [b for b in person.rent_bills(**params) if b["tenant"]["name"] == name]
    assert len(found) == 1, f"expected one bill of {name}, saw {len(found)}"
    return found[0]


def assert_field_error(response, status: int, code: str, field: str | None) -> dict:
    """Require an error answer with status, code and field; return its body."""
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code, body
    assert body["field"] == field, body
    assert body["message"]
    return body


def edit_body(detail: dict, **changes) -> dict:
    """The full edit request of a tenant, as read from its detail, with changes.

    `lease` changes are merged into the lease; other keys replace the field.
    """
    lease = detail["lease"]
    body = {
        "name": detail["name"],
        "phone": detail["phone"],
        "occupation": detail["occupation"],
        "emergencyContacts": detail["emergencyContacts"],
        "lease": {
            "startDate": lease["startDate"],
            "endDate": lease["endDate"],
            "billingCycle": lease["billingCycle"],
            "rent": lease["rent"],
            "gracePeriodDays": lease["gracePeriodDays"],
        },
    }
    body["lease"].update(changes.pop("lease", {}))
    body.update(changes)
    return body


def days(start: date, count: int) -> date:
    """The date `count` days after `start`."""
    return start + timedelta(days=count)
