"""Schemas for rent bills, their payment state and history, the payment overview and payment patterns."""

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import ApiModel
from app.schemas.complaints import PropertyRef
from app.schemas.properties import BankAccount
from app.schemas.tenants import RoomRef

# A blank reason passes the type and is refused by the service with its own code.
Reason = Annotated[str, StringConstraints(strip_whitespace=True)]


class PaymentStatus(StrEnum):
    """Where a rent bill is in its payment."""

    UNPAID = "unpaid"
    AWAITING_VERIFICATION = "awaitingVerification"
    PAID = "paid"
    REJECTED = "rejected"


class PaymentMethod(StrEnum):
    """How a rent bill was paid."""

    TRANSFER = "transfer"
    CASH = "cash"


class TenantRef(ApiModel):
    """The tenant a rent bill is for."""

    id: UUID
    name: str


class Payment(ApiModel):
    """The payment state of a rent bill."""

    status: PaymentStatus
    method: PaymentMethod | None
    paid_on: dt.date | None
    has_receipt: bool
    rejection_reason: str | None


class RentBillSummary(ApiModel):
    """A rent bill as shown in lists."""

    id: UUID
    tenant: TenantRef
    room: RoomRef
    property: PropertyRef
    period_start: dt.date
    period_end: dt.date
    due_date: dt.date
    amount: int = Field(description="In rupiah.")
    payment: Payment
    days_overdue: int = Field(
        ge=0,
        description="Days past the due date while unpaid or rejected, else 0.",
    )
    is_current: bool = Field(
        description="True when the billing period contains today in Asia/Jakarta."
    )
    can_upload_receipt: bool = Field(
        description="True when the bill is current, unpaid or rejected, and its "
        "property has a bank account. Describes the bill, not the caller's role."
    )


class PaymentStatusChange(ApiModel):
    """One change of a rent bill's payment status."""

    status: PaymentStatus
    method: PaymentMethod | None
    reason: str | None
    manual: bool
    actor_name: str | None = Field(description="Null when the system made the change.")
    changed_at: dt.datetime


class RentBill(RentBillSummary):
    """A rent bill with the bank account to pay into and its history."""

    bank_account: BankAccount | None
    status_changes: list[PaymentStatusChange] = Field(description="Oldest first.")


class RentBillList(ApiModel):
    """Rent bills visible to the caller."""

    items: list[RentBillSummary]


class ReceiptRejectionInput(ApiModel):
    """The reason a transfer receipt is rejected."""

    reason: Reason = Field(
        description="Not blank after trimming.", json_schema_extra={"minLength": 1}
    )


class CashPaymentInput(ApiModel):
    """A cash payment received for a rent bill."""

    received_on: dt.date = Field(description="Not after today.")


class PaymentStatusChangeInput(ApiModel):
    """A manual correction of a rent bill's payment status."""

    status: Literal["unpaid", "paid", "rejected"]
    reason: Reason = Field(
        description="Not blank after trimming.", json_schema_extra={"minLength": 1}
    )
    method: PaymentMethod | None = Field(
        default=None,
        description="Required when status is paid; not allowed otherwise.",
    )
    received_on: dt.date | None = Field(
        default=None,
        description="Required when status is paid; not allowed otherwise. "
        "Not after today.",
    )


class PaymentOverviewItem(ApiModel):
    """A tenant's room and their bill for the overview date."""

    tenant: TenantRef
    room: RoomRef
    bill: RentBillSummary | None = Field(
        description="Null when no bill covers the date."
    )


class PaymentOverview(ApiModel):
    """Payment state of a property's tenants on a date."""

    date: dt.date
    items: list[PaymentOverviewItem]


class PaymentPattern(ApiModel):
    """A tenant's payment pattern over their most recent bills."""

    tenant: TenantRef
    room: RoomRef
    on_time_count: int = Field(ge=0)
    counted_bill_count: int = Field(ge=0, le=6)
    average_days_late: int = Field(ge=0)
    arrears: int = Field(ge=0, description="In rupiah.")
    at_risk: bool
    summary: str | None
    summary_withheld: bool = Field(
        description="True when a summary exists but is withheld for lack of a subscription."
    )


class PaymentPatternList(ApiModel):
    """Payment patterns of a property's tenants."""

    items: list[PaymentPattern]
