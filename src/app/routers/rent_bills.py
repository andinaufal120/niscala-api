"""Endpoints under /rent-bills."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status

from app.access import require_roles
from app.db import SessionDep
from app.errors import ErrorBody
from app.schemas.auth import UserRole
from app.schemas.payments import (
    CashPaymentInput,
    PaymentStatus,
    PaymentStatusChangeInput,
    ReceiptRejectionInput,
    RentBill,
    RentBillList,
)
from app.security import CurrentUser
from app.services import rent_bills

router = APIRouter(prefix="/rent-bills", tags=["rent-bills"])

RentBillId = Annotated[UUID, Path(alias="rentBillId")]
Db = SessionDep
Tenant = Annotated[CurrentUser, Depends(require_roles(UserRole.TENANT))]
Management = Annotated[
    CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
]
Reader = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.TENANT, UserRole.OWNER, UserRole.MANAGER)),
]


def _errors(*statuses: int) -> dict[int | str, dict]:
    """Declare error responses with the uniform error body."""
    return {code: {"model": ErrorBody} for code in statuses}


@router.get("", responses=_errors(403))
def list_rent_bills(
    caller: Reader,
    db: Db,
    tenant_id: Annotated[UUID | None, Query(alias="tenantId")] = None,
    property_id: Annotated[UUID | None, Query(alias="propertyId")] = None,
    payment_status: Annotated[
        list[PaymentStatus] | None, Query(alias="paymentStatus")
    ] = None,
) -> RentBillList:
    """List the caller's rent bills: a tenant's own, or those on accessible properties."""
    return rent_bills.list_rent_bills(
        db, caller.user, tenant_id, property_id, payment_status
    )


@router.get("/{rentBillId}", responses=_errors(403, 404))
def get_rent_bill(rent_bill_id: RentBillId, caller: Reader, db: Db) -> RentBill:
    """Return a rent bill's detail."""
    return rent_bills.get_rent_bill(db, caller.user, rent_bill_id)


@router.put("/{rentBillId}/receipt", responses=_errors(403, 404, 409))
def upload_receipt(
    rent_bill_id: RentBillId,
    file: Annotated[UploadFile, File(json_schema_extra={"format": "binary"})],
    caller: Tenant,
    db: Db,
) -> RentBill:
    """Attach a transfer receipt image and mark the bill as awaiting verification."""
    content = file.file.read(rent_bills.MAX_RECEIPT_BYTES + 1)
    return rent_bills.upload_receipt(db, caller.user, rent_bill_id, content)


@router.get(
    "/{rentBillId}/receipt",
    response_class=Response,
    responses={
        200: {"content": {"image/jpeg": {}, "image/png": {}}},
        **_errors(403, 404),
    },
)
def get_receipt(rent_bill_id: RentBillId, caller: Reader, db: Db) -> Response:
    """Return the receipt image of a rent bill."""
    receipt = rent_bills.get_receipt(db, caller.user, rent_bill_id)
    return Response(content=receipt.content, media_type=receipt.content_type)


@router.post("/{rentBillId}/verification", responses=_errors(403, 404, 409))
def verify_receipt(rent_bill_id: RentBillId, caller: Management, db: Db) -> RentBill:
    """Accept a transfer receipt and mark the bill as paid."""
    return rent_bills.verify_receipt(db, caller.user, rent_bill_id)


@router.post("/{rentBillId}/rejection", responses=_errors(403, 404, 409))
def reject_receipt(
    rent_bill_id: RentBillId,
    body: ReceiptRejectionInput,
    caller: Management,
    db: Db,
) -> RentBill:
    """Reject a transfer receipt with a reason."""
    return rent_bills.reject_receipt(db, caller.user, rent_bill_id, body.reason)


@router.post("/{rentBillId}/cash-payment", responses=_errors(403, 404, 409))
def record_cash_payment(
    rent_bill_id: RentBillId,
    body: CashPaymentInput,
    caller: Management,
    db: Db,
) -> RentBill:
    """Record a cash payment and mark the bill as paid."""
    return rent_bills.record_cash_payment(
        db, caller.user, rent_bill_id, body.received_on
    )


@router.post(
    "/{rentBillId}/status-changes",
    status_code=status.HTTP_201_CREATED,
    responses=_errors(403, 404),
)
def change_payment_status(
    rent_bill_id: RentBillId,
    body: PaymentStatusChangeInput,
    caller: Management,
    db: Db,
) -> RentBill:
    """Manually set a bill's payment status, with a reason."""
    return rent_bills.change_payment_status(db, caller.user, rent_bill_id, body)
