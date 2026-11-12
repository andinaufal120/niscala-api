"""Endpoints under /rent-bills."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)

from app.access import require_roles
from app.ai.summarizer import PaymentPatternSummarizer, get_payment_pattern_summarizer
from app.db import SessionDep
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
from app.services import payment_patterns, rent_bills
from app.storage import FileStore, get_file_store

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
Summarizer = Annotated[
    PaymentPatternSummarizer, Depends(get_payment_pattern_summarizer)
]
Store = Annotated[FileStore, Depends(get_file_store)]


def _commit_and_summarize(
    db: Db,
    background_tasks: BackgroundTasks,
    summarizer: PaymentPatternSummarizer,
    changed: RentBill,
) -> RentBill:
    """Commit a status change, then regenerate the lease's summary in the background."""
    lease_id = rent_bills.lease_id_of(db, changed.id)
    # Commit now so the background task sees the change.
    db.commit()
    background_tasks.add_task(payment_patterns.regenerate_summary, lease_id, summarizer)
    return changed


@router.get("")
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


@router.get("/{rentBillId}")
def get_rent_bill(rent_bill_id: RentBillId, caller: Reader, db: Db) -> RentBill:
    """Return a rent bill's detail."""
    return rent_bills.get_rent_bill(db, caller.user, rent_bill_id)


@router.put("/{rentBillId}/receipt")
def upload_receipt(
    rent_bill_id: RentBillId,
    file: Annotated[UploadFile, File(json_schema_extra={"format": "binary"})],
    caller: Tenant,
    db: Db,
    summarizer: Summarizer,
    background_tasks: BackgroundTasks,
    store: Store,
) -> RentBill:
    """Attach a transfer receipt image and mark the bill as awaiting verification."""
    content = file.file.read(rent_bills.MAX_RECEIPT_BYTES + 1)
    changed = rent_bills.upload_receipt(db, store, caller.user, rent_bill_id, content)
    return _commit_and_summarize(db, background_tasks, summarizer, changed)


@router.get(
    "/{rentBillId}/receipt",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def get_receipt(
    rent_bill_id: RentBillId, caller: Reader, db: Db, store: Store
) -> Response:
    """Return the receipt image of a rent bill."""
    content, content_type = rent_bills.get_receipt(db, store, caller.user, rent_bill_id)
    return Response(content=content, media_type=content_type)


@router.post("/{rentBillId}/verification")
def verify_receipt(
    rent_bill_id: RentBillId,
    caller: Management,
    db: Db,
    summarizer: Summarizer,
    background_tasks: BackgroundTasks,
) -> RentBill:
    """Accept a transfer receipt and mark the bill as paid."""
    changed = rent_bills.verify_receipt(db, caller.user, rent_bill_id)
    return _commit_and_summarize(db, background_tasks, summarizer, changed)


@router.post("/{rentBillId}/rejection")
def reject_receipt(
    rent_bill_id: RentBillId,
    body: ReceiptRejectionInput,
    caller: Management,
    db: Db,
    summarizer: Summarizer,
    background_tasks: BackgroundTasks,
) -> RentBill:
    """Reject a transfer receipt with a reason."""
    changed = rent_bills.reject_receipt(db, caller.user, rent_bill_id, body.reason)
    return _commit_and_summarize(db, background_tasks, summarizer, changed)


@router.post("/{rentBillId}/cash-payment")
def record_cash_payment(
    rent_bill_id: RentBillId,
    body: CashPaymentInput,
    caller: Management,
    db: Db,
    summarizer: Summarizer,
    background_tasks: BackgroundTasks,
) -> RentBill:
    """Record a cash payment and mark the bill as paid."""
    changed = rent_bills.record_cash_payment(
        db, caller.user, rent_bill_id, body.received_on
    )
    return _commit_and_summarize(db, background_tasks, summarizer, changed)


@router.post("/{rentBillId}/status-changes", status_code=status.HTTP_201_CREATED)
def change_payment_status(
    rent_bill_id: RentBillId,
    body: PaymentStatusChangeInput,
    caller: Management,
    db: Db,
    summarizer: Summarizer,
    background_tasks: BackgroundTasks,
) -> RentBill:
    """Manually set a bill's payment status, with a reason."""
    changed = rent_bills.change_payment_status(db, caller.user, rent_bill_id, body)
    return _commit_and_summarize(db, background_tasks, summarizer, changed)
