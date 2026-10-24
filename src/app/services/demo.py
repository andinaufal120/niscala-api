"""Creating the demo owner, property, room and active tenant for development."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Invitation, Tenant, UserAccount
from app.schemas.auth import DeviceInfo, RegisterOwnerInput, UserRole
from app.schemas.properties import PropertyInput
from app.schemas.rooms import RoomInput
from app.schemas.tenants import EmergencyContact, LeaseInput, NewTenantInput
from app.services import properties, rooms, tenants
from app.services.accounts import create_owner
from app.services.passwords import hash_password

OWNER_EMAIL = "owner@example.com"
TENANT_EMAIL = "tenant@example.com"
PASSWORD = "Demo-Kost-2026!"
PROPERTY_NAME = "Kost Melati"
ROOM_NUMBER = "101"
RENT = 1500000


class DemoConflict(Exception):
    """An email the demo data needs belongs to an account that cannot be reused."""

    def __init__(self, email: str):
        super().__init__(f"The email {email} is already used by another account")


def _find(db: Session, email: str) -> UserAccount | None:
    return db.scalars(
        select(UserAccount).where(func.lower(UserAccount.email) == email)
    ).one_or_none()


def _lease_dates(today: date) -> tuple[date, date]:
    index = today.year * 12 + today.month - 1 - 2
    start = date(index // 12, index % 12 + 1, 1)
    return start, start.replace(year=start.year + 1)


def seed_demo(db: Session) -> bool:
    """Create the demo data unless the demo owner already exists.

    Flushes without committing. Returns whether anything was created. Raises
    DemoConflict when the owner email belongs to a non-owner account, or when
    the tenant email belongs to an account that is not the demo tenant. An
    existing owner is left untouched, passwords included.
    """
    owner = _find(db, OWNER_EMAIL)
    tenant_user = _find(db, TENANT_EMAIL)
    if owner is not None and owner.role != UserRole.OWNER:
        raise DemoConflict(OWNER_EMAIL)
    if tenant_user is not None and (
        owner is None or tenant_user.role != UserRole.TENANT
    ):
        raise DemoConflict(TENANT_EMAIL)
    if owner is not None:
        return False

    owner = create_owner(
        db,
        RegisterOwnerInput(
            name="Demo Owner",
            email=OWNER_EMAIL,
            password=PASSWORD,
            device=DeviceInfo(name="seed-demo", platform="cli"),
        ),
    )
    owner.email_verified = True
    parent = properties.create_property(
        db,
        owner,
        PropertyInput(name=PROPERTY_NAME, address="Jl. Melati No. 1, Jakarta"),
    )
    room = rooms.create_room(
        db,
        owner,
        parent.id,
        RoomInput(
            number=ROOM_NUMBER,
            base_rate=RENT,
            length_m=3,
            width_m=4,
            facilities=["AC", "Wi-Fi"],
        ),
    )
    start, end = _lease_dates(datetime.now(ZoneInfo("Asia/Jakarta")).date())
    created = tenants.create_tenant(
        db,
        owner,
        parent.id,
        NewTenantInput(
            room_id=room.id,
            name="Budi Santoso",
            phone="081234567890",
            emergency_contacts=[
                EmergencyContact(
                    name="Siti Santoso", relationship="Mother", phone="081234567891"
                ),
                EmergencyContact(
                    name="Agus Santoso", relationship="Brother", phone="081234567892"
                ),
            ],
            lease=LeaseInput(start_date=start, end_date=end, rent=RENT),
        ),
    )

    now = datetime.now(UTC)
    account = db.get_one(UserAccount, created.id)
    account.email = TENANT_EMAIL
    account.password_hash = hash_password(PASSWORD)
    account.email_verified = True
    db.get_one(Tenant, created.id).activated_at = now
    db.execute(
        update(Invitation)
        .where(Invitation.tenant_id == created.id, Invitation.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )
    db.flush()
    return True
