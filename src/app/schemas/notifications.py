"""Schemas for notifications, notification settings and the device push token."""

import datetime as dt
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import ApiModel
from app.schemas.complaints import ComplaintStatus, ComplaintUrgency, PropertyRef
from app.schemas.payments import PaymentMethod, PaymentStatus, TenantRef
from app.schemas.tenants import RoomRef


class NotificationType(StrEnum):
    """The event a notification announces."""

    BILL_ISSUED = "billIssued"
    DUE_DATE_REMINDER = "dueDateReminder"
    BILL_OVERDUE = "billOverdue"
    PAYMENT_STATUS_CHANGED = "paymentStatusChanged"
    COMPLAINT_STATUS_CHANGED = "complaintStatusChanged"
    COMPLAINT_SUBMITTED = "complaintSubmitted"
    RECEIPT_UPLOADED = "receiptUploaded"
    CASH_PAYMENT_RECORDED = "cashPaymentRecorded"
    TENANT_ACTIVATED = "tenantActivated"
    MANAGER_ACTIVATED = "managerActivated"


class NotificationCategory(StrEnum):
    """A group of notification types with one push switch."""

    BILLING = "billing"
    PAYMENT_STATUS = "paymentStatus"
    COMPLAINT_PROGRESS = "complaintProgress"
    NEW_COMPLAINT = "newComplaint"
    RECEIPT_UPLOAD = "receiptUpload"
    OVERDUE_BILL = "overdueBill"
    ACCOUNT_ACTIVITY = "accountActivity"


class NotificationUrgencyScope(StrEnum):
    """Which complaint urgencies are pushed for the newComplaint category."""

    ALL_URGENCIES = "allUrgencies"
    HIGH_ONLY = "highOnly"


class NotificationRentBill(ApiModel):
    """The rent bill a notification is about, as it was when the event happened."""

    rent_bill_id: UUID
    period_start: dt.date
    period_end: dt.date
    due_date: dt.date
    amount: int = Field(description="In rupiah.")
    payment_status: PaymentStatus = Field(
        description="The status the notification announces, or the bill had at that time."
    )
    payment_method: PaymentMethod | None = Field(description="Set for a paid bill.")
    reason: str | None = Field(description="Rejection reason or manual-change reason.")
    days_overdue: int = Field(
        ge=0, description="Days past the due date; 0 unless billOverdue."
    )


class NotificationComplaint(ApiModel):
    """The complaint a notification is about, as it was when the event happened."""

    complaint_id: UUID
    description: str
    status: ComplaintStatus
    category: str | None
    urgency: ComplaintUrgency | None
    handling_note: str | None


class Notification(ApiModel):
    """An in-app notification and the facts of the event it announces."""

    id: UUID
    type: NotificationType
    created_at: dt.datetime
    read: bool
    rent_bill: NotificationRentBill | None
    complaint: NotificationComplaint | None
    tenant: TenantRef | None
    room: RoomRef | None
    property: PropertyRef | None
    actor_name: str | None = Field(
        description="The Manager who recorded the cash payment or activated their account; otherwise null."
    )


class NotificationList(ApiModel):
    """The caller's notifications."""

    items: list[Notification] = Field(description="Newest first.")
    unread_count: int = Field(ge=0)


class NotificationSettingItem(ApiModel):
    """The push switch of one notification category."""

    category: NotificationCategory
    push_enabled: bool
    urgency_scope: NotificationUrgencyScope | None = Field(
        description="Set only for newComplaint; null for every other category."
    )


class NotificationSettings(ApiModel):
    """The caller's push settings."""

    items: list[NotificationSettingItem] = Field(
        description="One entry per category of the caller's role."
    )


class NotificationSettingsInput(ApiModel):
    """A replacement of the caller's push settings."""

    items: list[NotificationSettingItem] = Field(
        description="Exactly the categories of the caller's role, each once."
    )


class PushTokenInput(ApiModel):
    """The device push token of the current session."""

    token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)
    ]
