"""Helpers for the tests of account deletion and the erasure of personal data."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from user_account_support import get_row, rows_of, set_columns

ERASED_NAME = "Deleted account"
BANK = {
    "bank_name": "Bank Mandiri",
    "bank_account_number": "1234567890",
    "bank_account_holder_name": "Rina Owner",
}
ME_URL = "/me"

KINDS = (
    "email_changes",
    "password_resets",
    "verification_codes",
    "login_failures",
    "notifications",
)


@dataclass(frozen=True)
class Person:
    """An account about to be deleted, with the records that belong to it.

    `record` is the Tenant or Manager record of a Tenant or Manager account;
    `prop` and `room` belong to an Owner (a Tenant's or Manager's landlord has
    its own). `second` is a second record of the same account.
    """

    user: Any
    email: str
    signed_in: Any
    record: Any = None
    second: Any = None
    prop: Any = None
    room: Any = None
    landlord: Any = None
    landlord_prop: Any = None
    landlord_room: Any = None

    @property
    def headers(self) -> dict[str, str]:
        return self.signed_in.headers


def build_person(
    role: str,
    *,
    database,
    make_user,
    make_property,
    make_room,
    make_verified_tenant,
    make_manager,
    sign_in,
    email: str = "rina@example.com",
    reauthenticated: bool = True,
    with_second_record: bool = False,
) -> Person:
    """Create a signed-in account of a role with a password and personal data.

    A Tenant has an ended lease, a phone, an occupation and two emergency
    contacts; a Manager has a nickname, a phone and one assigned property; an
    Owner has a property with a bank account and a room. A second record, when
    asked for, is at another landlord. The session has re-authenticated
    unless `reauthenticated` is false.
    """
    from user_account_support import set_password

    from app.schemas.auth import UserRole

    landlord = prop = room = record = second = None
    landlord_prop = landlord_room = None
    if role == "owner":
        user = make_user(name="Rina Owner", email=email)
        prop = make_property(user, name="Kos Melati")
        set_bank_account(database, prop)
        room = make_room(prop)
    elif role == "admin":
        user = make_user(name="Ade Admin", email=email, role=UserRole.ADMIN)
    else:
        landlord = make_user(name="Landlord", email=f"landlord.{email}")
        landlord_prop = make_property(landlord, name="Kos Landlord")
        landlord_room = make_room(landlord_prop, number="1")
        if role == "tenant":
            record = make_verified_tenant(
                landlord_room,
                name="Budi Tenant",
                email=email,
                phone="081234567890",
                occupation="Guru",
                contacts=[
                    ("Siti", "Ibu", "081111111111"),
                    ("Agus", "Ayah", "082222222222"),
                ],
                lease_ended=True,
            )
            user = record.user
            if with_second_record:
                other_room = make_room(landlord_prop, number="2")
                second = make_verified_tenant(
                    other_room,
                    user=user,
                    phone="083333333333",
                    occupation="Dosen",
                    contacts=[("Rini", "Kakak", "084444444444")],
                    lease_ended=True,
                )
        else:
            record = make_manager(
                landlord,
                [landlord_prop],
                activated=True,
                email=email,
                nickname="Mimi",
                phone="081234567890",
            )
            user = record.user
            if with_second_record:
                other_landlord = make_user(name="Other Landlord")
                other_prop = make_property(other_landlord, name="Kos Other")
                second = make_manager(
                    other_landlord,
                    [other_prop],
                    activated=True,
                    user=user,
                    nickname="Mira",
                    phone="085555555555",
                )
    set_password(database, user)
    session = sign_in(user)
    if reauthenticated:
        mark_reauthenticated(database, session)
    return Person(
        user=user,
        email=email,
        signed_in=session,
        record=record,
        second=second,
        prop=prop,
        room=room,
        landlord=landlord,
        landlord_prop=landlord_prop,
        landlord_room=landlord_room,
    )


def delete_me(client, headers):
    return client.delete(ME_URL, headers=headers)


def mark_reauthenticated(database, signed_in, at: datetime | None = None) -> None:
    """Record a re-authentication of a session, now unless `at` is given."""
    from app.models import UserSession

    set_columns(
        database,
        UserSession,
        signed_in.session_id,
        reauthenticated_at=at or datetime.now(UTC),
    )


def ago(**kwargs) -> datetime:
    return datetime.now(UTC) - timedelta(**kwargs)


def set_bank_account(database, property_) -> None:
    from app.models import Property

    set_columns(database, Property, property_.id, **BANK)


def seed_personal_rows(database, user, email: str) -> None:
    """Store one row of every kind that erasing an account deletes."""
    from app.models import (
        EmailChangeRequest,
        EmailVerificationCode,
        LoginFailure,
        Notification,
        PasswordResetToken,
    )

    now = datetime.now(UTC)
    later = now + timedelta(days=1)
    with Session(database) as db:
        db.add_all(
            [
                EmailChangeRequest(
                    user_id=user.id,
                    new_email=f"new.{uuid4().hex[:8]}@example.com",
                    token_hash=uuid4().hex,
                    expires_at=later,
                ),
                PasswordResetToken(
                    user_id=user.id, token_hash=uuid4().hex, expires_at=later
                ),
                EmailVerificationCode(
                    user_id=user.id, code_hash=uuid4().hex, expires_at=later
                ),
                LoginFailure(email=email.strip().lower(), failed_attempts=2),
                Notification(
                    recipient_id=user.id, type="billIssued", payload={}, created_at=now
                ),
                Notification(
                    recipient_id=user.id,
                    type="complaintSubmitted",
                    payload={},
                    created_at=now,
                    read_at=now,
                ),
            ]
        )
        db.commit()


def personal_row_counts(database, user, email: str) -> dict[str, int]:
    """How many rows of each erasable kind the account has."""
    from app.models import (
        EmailChangeRequest,
        EmailVerificationCode,
        LoginFailure,
        Notification,
        PasswordResetToken,
    )

    return {
        "email_changes": len(
            rows_of(database, EmailChangeRequest, EmailChangeRequest.user_id == user.id)
        ),
        "password_resets": len(
            rows_of(database, PasswordResetToken, PasswordResetToken.user_id == user.id)
        ),
        "verification_codes": len(
            rows_of(
                database,
                EmailVerificationCode,
                EmailVerificationCode.user_id == user.id,
            )
        ),
        "login_failures": len(
            rows_of(database, LoginFailure, LoginFailure.email == email.strip().lower())
        ),
        "notifications": len(
            rows_of(database, Notification, Notification.recipient_id == user.id)
        ),
    }


def seed_session_details(database, user_id) -> None:
    """Give every session of an account a push token."""
    from app.models import UserSession

    for row in rows_of(database, UserSession, UserSession.user_id == user_id):
        set_columns(database, UserSession, row.id, push_token=f"push-{row.id}")


def add_payment_summary(database, lease) -> None:
    from app.models import PaymentPatternSummary

    with Session(database) as db:
        db.add(
            PaymentPatternSummary(
                lease_id=lease.id,
                summary="Pays late every month.",
                generated_at=datetime.now(UTC),
            )
        )
        db.commit()


def add_complaint_photo(database, file_store, complaint) -> str:
    """Store a photo of a complaint and its bytes; return the storage key."""
    from app.models import ComplaintPhoto

    key = f"complaints/{complaint.id}/{uuid4()}"
    file_store.put(key, b"photo-bytes", "image/jpeg")
    with Session(database) as db:
        db.add(
            ComplaintPhoto(
                complaint_id=complaint.id,
                storage_key=key,
                content_type="image/jpeg",
                uploaded_at=datetime.now(UTC),
            )
        )
        db.commit()
    return key


def _user_model():
    from app.models import UserAccount

    return UserAccount


def assert_erased(database, user_id) -> None:
    """The account is deleted and holds no name, email, password or Google identity."""
    row = get_row(database, _user_model(), user_id)
    assert row.deleted_at is not None
    assert row.name == ERASED_NAME
    assert row.email is None
    assert row.password_hash is None
    assert row.google_subject is None
    assert row.google_email is None


def assert_untouched(database, user_id, name: str, email: str) -> None:
    row = get_row(database, _user_model(), user_id)
    assert row.deleted_at is None
    assert row.name == name
    assert row.email == email


def session_state(database, user_id) -> list[tuple]:
    """What deletion changes on the sessions of an account."""
    from app.models import UserSession

    return [
        (row.id, row.revoked_at, row.device_name, row.push_token)
        for row in sorted(
            rows_of(database, UserSession, UserSession.user_id == user_id),
            key=lambda row: str(row.id),
        )
    ]


def seed_tenant_data(database, person) -> None:
    """Give every record of a Tenant person a payment-pattern summary."""
    for stored in (person.record, person.second):
        if stored is not None:
            add_payment_summary(database, stored.lease)


def assert_tenant_erased(database, person) -> None:
    """Every record of the Tenant is deleted and holds no personal data."""
    from app.models import EmergencyContact, PaymentPatternSummary, Tenant

    for stored in (person.record, person.second):
        if stored is None:
            continue
        row = get_row(database, Tenant, stored.id)
        assert row.deleted_at is not None
        assert row.phone == ""
        assert row.occupation in ("", None)
        assert (
            rows_of(database, EmergencyContact, EmergencyContact.tenant_id == stored.id)
            == []
        )
        assert (
            rows_of(
                database,
                PaymentPatternSummary,
                PaymentPatternSummary.lease_id == stored.lease.id,
            )
            == []
        )


def assert_manager_erased(database, person) -> None:
    """Every record of the Manager is deleted without phone and nickname."""
    from app.models import Manager, ManagerAssignment

    for stored in (person.record, person.second):
        if stored is None:
            continue
        row = get_row(database, Manager, stored.id)
        assert row.deleted_at is not None
        assert row.phone == ""
        assert row.nickname in ("", None)
    assert (
        rows_of(
            database,
            ManagerAssignment,
            ManagerAssignment.manager_id == person.user.id,
        )
        == []
    )


def assert_owner_erased(database, properties) -> None:
    """The Owner's properties are deleted and keep no bank account."""
    from app.models import Property

    for prop in properties:
        row = get_row(database, Property, prop.id)
        assert row.deleted_at is not None
        assert row.bank_name is None
        assert row.bank_account_number is None
        assert row.bank_account_holder_name is None


@dataclass(frozen=True)
class History:
    """Ids and values of the records an erasure must keep."""

    bill: Any
    complaint: Any
    receipt_key: str
    photo_key: str
    bill_status: str
    amount: int
    description: str


def seed_history(
    database, file_store, make_rent_bill, make_complaint, tenant, room, actor_id=None
) -> History:
    """Store a bill with a receipt and status history, and a complaint with a photo."""
    from rent_bill_support import TODAY

    now = datetime.now(UTC)
    bill = make_rent_bill(
        tenant.lease,
        status="paid",
        method="transfer",
        amount=1250000,
        receipt=(b"receipt-bytes", "image/png", now),
        changes=[
            ("unpaid", None, None, False, None, now - timedelta(days=3)),
            ("paid", "transfer", None, True, actor_id, now),
        ],
        paid_on=TODAY,
    )
    complaint = make_complaint(tenant, room, description="The tap leaks.")
    photo_key = add_complaint_photo(database, file_store, complaint)
    receipt_key = next(key for key in file_store.keys if key.startswith("receipts/"))
    return History(
        bill=bill,
        complaint=complaint,
        receipt_key=receipt_key,
        photo_key=photo_key,
        bill_status="paid",
        amount=1250000,
        description="The tap leaks.",
    )


def assert_history_kept(database, file_store, history: History) -> None:
    """The bill, its status history, its receipt, the complaint and its photo remain."""
    from app.models import (
        Complaint,
        ComplaintPhoto,
        ComplaintStatusChange,
        RentBill,
        RentBillReceipt,
        RentBillStatusChange,
    )

    bill = get_row(database, RentBill, history.bill.id)
    assert bill is not None
    assert bill.payment_status == history.bill_status
    assert bill.amount == history.amount
    changes = rows_of(
        database,
        RentBillStatusChange,
        RentBillStatusChange.rent_bill_id == history.bill.id,
    )
    assert [c.status for c in sorted(changes, key=lambda c: c.changed_at)] == [
        "unpaid",
        "paid",
    ]
    receipt = get_row(database, RentBillReceipt, history.bill.id)
    assert receipt is not None
    assert receipt.storage_key == history.receipt_key
    complaint = get_row(database, Complaint, history.complaint.id)
    assert complaint is not None
    assert complaint.description == history.description
    assert (
        len(
            rows_of(
                database,
                ComplaintStatusChange,
                ComplaintStatusChange.complaint_id == history.complaint.id,
            )
        )
        == 1
    )
    photo = get_row(database, ComplaintPhoto, history.complaint.id)
    assert photo is not None
    assert photo.storage_key == history.photo_key
    assert {history.receipt_key, history.photo_key} <= file_store.keys
    assert file_store.deleted() == []


def table_snapshot(database) -> dict[str, list]:
    """Every table other than sessions that deletion or erasure can change."""
    from app import models

    names = (
        "UserAccount",
        "Property",
        "Room",
        "Tenant",
        "EmergencyContact",
        "Manager",
        "ManagerAssignment",
        "Lease",
        "PaymentPatternSummary",
        "EmailChangeRequest",
        "PasswordResetToken",
        "EmailVerificationCode",
        "LoginFailure",
        "Notification",
        "Invitation",
        "RentBill",
        "RentBillStatusChange",
        "RentBillReceipt",
        "Complaint",
        "ComplaintPhoto",
        "SubscriptionOrder",
        "Subscription",
    )
    snapshot: dict[str, list] = {}
    with Session(database) as db:
        for name in names:
            table = getattr(models, name).__table__
            rows = [tuple(row) for row in db.execute(select(table))]
            snapshot[name] = sorted(rows, key=repr)
    return snapshot
