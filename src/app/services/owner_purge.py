"""Removing the data of an Owner whose account was deleted long ago."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.models import (
    Complaint,
    ComplaintPhoto,
    ComplaintStatusChange,
    EmergencyContact,
    Invitation,
    Lease,
    Manager,
    ManagerAssignment,
    Notification,
    NotificationSetting,
    PaymentPatternSummary,
    Property,
    RentBill,
    RentBillReceipt,
    RentBillStatusChange,
    Room,
    ScheduledDowngrade,
    Subscription,
    Tenant,
    UserAccount,
)
from app.schemas.auth import UserRole
from app.storage import DELETE_AFTER_COMMIT, get_file_store

OWNER_RETENTION = timedelta(days=90)


def purge_deleted_owners(db: Session) -> None:
    """Delete the data of every Owner deleted longer ago than the retention period.

    Removes the properties, rooms, leases, Tenant and Manager records, bills,
    complaints, notifications about the properties, subscription and
    notification settings of the Owner, and queues their stored files for
    deletion after the commit. The Owner's account row, subscription orders and
    sessions stay, and so do the Tenant and Manager accounts. Flushes only;
    the caller commits.
    """
    cutoff = datetime.now(UTC) - OWNER_RETENTION
    owns_something = (
        exists().where(Property.owner_id == UserAccount.id)
        | exists().where(Manager.owner_id == UserAccount.id)
        | exists().where(Subscription.owner_id == UserAccount.id)
    )
    owner_ids = db.scalars(
        select(UserAccount.id).where(
            UserAccount.role == UserRole.OWNER,
            UserAccount.deleted_at < cutoff,
            owns_something,
        )
    ).all()
    for owner_id in owner_ids:
        _purge_owner(db, owner_id)


def _purge_owner(db: Session, owner_id: UUID) -> None:
    property_ids = db.scalars(
        select(Property.id).where(Property.owner_id == owner_id)
    ).all()
    room_ids = db.scalars(select(Room.id).where(Room.property_id.in_(property_ids)))
    room_ids = list(room_ids)
    lease_ids = list(db.scalars(select(Lease.id).where(Lease.room_id.in_(room_ids))))
    complaint_ids = list(
        db.scalars(select(Complaint.id).where(Complaint.room_id.in_(room_ids)))
    )
    tenant_ids = set(
        db.scalars(select(Lease.tenant_id).where(Lease.room_id.in_(room_ids)))
    ) | set(
        db.scalars(select(Complaint.tenant_id).where(Complaint.room_id.in_(room_ids)))
    )
    manager_ids = list(
        db.scalars(select(Manager.id).where(Manager.owner_id == owner_id))
    )
    bill_ids = list(
        db.scalars(select(RentBill.id).where(RentBill.lease_id.in_(lease_ids)))
    )

    keys = list(
        db.scalars(
            select(RentBillReceipt.storage_key).where(
                RentBillReceipt.rent_bill_id.in_(bill_ids)
            )
        )
    ) + list(
        db.scalars(
            select(ComplaintPhoto.storage_key).where(
                ComplaintPhoto.complaint_id.in_(complaint_ids)
            )
        )
    )
    if keys:
        store = get_file_store()
        db.info.setdefault(DELETE_AFTER_COMMIT, []).extend((store, key) for key in keys)

    statements = [
        delete(RentBillReceipt).where(RentBillReceipt.rent_bill_id.in_(bill_ids)),
        delete(RentBillStatusChange).where(
            RentBillStatusChange.rent_bill_id.in_(bill_ids)
        ),
        delete(ComplaintPhoto).where(ComplaintPhoto.complaint_id.in_(complaint_ids)),
        delete(ComplaintStatusChange).where(
            ComplaintStatusChange.complaint_id.in_(complaint_ids)
        ),
        delete(Complaint).where(Complaint.id.in_(complaint_ids)),
        delete(RentBill).where(RentBill.id.in_(bill_ids)),
        delete(PaymentPatternSummary).where(
            PaymentPatternSummary.lease_id.in_(lease_ids)
        ),
        delete(Invitation).where(
            Invitation.tenant_id.in_(tenant_ids)
            | Invitation.manager_id.in_(manager_ids)
        ),
        delete(Lease).where(Lease.id.in_(lease_ids)),
        delete(EmergencyContact).where(EmergencyContact.tenant_id.in_(tenant_ids)),
        delete(Notification).where(Notification.property_id.in_(property_ids)),
        delete(ManagerAssignment).where(
            ManagerAssignment.property_id.in_(property_ids)
        ),
        delete(Room).where(Room.id.in_(room_ids)),
        delete(Property).where(Property.id.in_(property_ids)),
        delete(Tenant).where(Tenant.id.in_(tenant_ids)),
        delete(Manager).where(Manager.id.in_(manager_ids)),
        delete(Subscription).where(Subscription.owner_id == owner_id),
        delete(ScheduledDowngrade).where(ScheduledDowngrade.owner_id == owner_id),
        delete(NotificationSetting).where(NotificationSetting.user_id == owner_id),
    ]
    for statement in statements:
        db.execute(statement)
    db.flush()
