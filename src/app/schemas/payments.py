"""Schemas for rent bills, their payment state and the payment overview."""

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import ApiModel
from app.schemas.complaints import PropertyRef
from app.schemas.properties import BankAccount
from app.schemas.tenants import RoomRef

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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
    period_start: dt.date
    period_end: dt.date
    due_date: dt.date
    amount: int = Field(description="In rupiah.")
    payment: Payment


class RentBill(RentBillSummary):
    """A rent bill with its property and the bank account to pay into."""

    property: PropertyRef
    bank_account: BankAccount | None


class RentBillList(ApiModel):
    """Rent bills visible to the caller."""

    items: list[RentBillSummary]


class ReceiptRejectionInput(ApiModel):
    """The reason a transfer receipt is rejected."""

    reason: Reason = Field(description="Not blank after trimming.")


class CashPaymentInput(ApiModel):
    """A cash payment received for a rent bill."""

    received_on: dt.date


class PaymentStatusChangeInput(ApiModel):
    """A manual correction of a rent bill's payment status."""

    status: Literal["unpaid", "paid", "rejected"]
    reason: Reason = Field(description="Not blank after trimming.")


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
