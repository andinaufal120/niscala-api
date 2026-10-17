"""Endpoints under /rent-bills. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)

from app.schemas.payments import (
    CashPaymentInput,
    PaymentStatus,
    PaymentStatusChangeInput,
    ReceiptRejectionInput,
    RentBill,
    RentBillList,
)

router = APIRouter(prefix="/rent-bills", tags=["rent-bills"])

RentBillId = Annotated[UUID, Path(alias="rentBillId")]


@router.get("")
def list_rent_bills(
    tenant_id: Annotated[UUID | None, Query(alias="tenantId")] = None,
    payment_status: Annotated[
        PaymentStatus | None, Query(alias="paymentStatus")
    ] = None,
) -> RentBillList:
    """List the caller's rent bills: a tenant's own, or those on accessible properties."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{rentBillId}")
def get_rent_bill(rent_bill_id: RentBillId) -> RentBill:
    """Return a rent bill's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{rentBillId}/receipt")
def upload_receipt(
    rent_bill_id: RentBillId,
    file: Annotated[UploadFile, File(json_schema_extra={"format": "binary"})],
) -> RentBill:
    """Attach a transfer receipt image and mark the bill as awaiting verification."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get(
    "/{rentBillId}/receipt",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def get_receipt(rent_bill_id: RentBillId) -> Response:
    """Return the receipt image of a rent bill."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{rentBillId}/verification")
def verify_receipt(rent_bill_id: RentBillId) -> RentBill:
    """Accept a transfer receipt and mark the bill as paid."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{rentBillId}/rejection")
def reject_receipt(rent_bill_id: RentBillId, body: ReceiptRejectionInput) -> RentBill:
    """Reject a transfer receipt with a reason."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{rentBillId}/cash-payment")
def record_cash_payment(rent_bill_id: RentBillId, body: CashPaymentInput) -> RentBill:
    """Record a cash payment and mark the bill as paid."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{rentBillId}/status-changes", status_code=status.HTTP_201_CREATED)
def change_payment_status(
    rent_bill_id: RentBillId, body: PaymentStatusChangeInput
) -> RentBill:
    """Manually set a bill's payment status, with a reason."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
