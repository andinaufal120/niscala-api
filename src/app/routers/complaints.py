"""Endpoints under /complaints and /complaint-categories.

Submitting, listing, reading, classifying and changing the status of complaints
and the category list are implemented; the others answer 501.
"""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Path,
    Response,
    UploadFile,
    status,
)

from app.access import require_roles
from app.ai.classifier import ComplaintClassifier, get_complaint_classifier
from app.config import COMPLAINT_CATEGORIES
from app.db import SessionDep
from app.schemas.auth import UserRole
from app.schemas.complaints import (
    Complaint,
    ComplaintCategoryList,
    ComplaintClassificationInput,
    ComplaintClassificationState,
    ComplaintInput,
    ComplaintList,
    ComplaintStatusChangeInput,
)
from app.security import CurrentUser, get_verified_user
from app.services import complaints

router = APIRouter(prefix="/complaints", tags=["complaints"])
categories_router = APIRouter(prefix="/complaint-categories", tags=["complaints"])

ComplaintId = Annotated[UUID, Path(alias="complaintId")]
Db = SessionDep
Tenant = Annotated[CurrentUser, Depends(require_roles(UserRole.TENANT))]
Reader = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.TENANT, UserRole.OWNER, UserRole.MANAGER)),
]
Management = Annotated[
    CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
]
Classifier = Annotated[ComplaintClassifier, Depends(get_complaint_classifier)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_complaint(
    body: ComplaintInput,
    caller: Tenant,
    db: Db,
    classifier: Classifier,
    background_tasks: BackgroundTasks,
) -> Complaint:
    """Submit a complaint as the calling tenant.

    The complaint is saved before it is classified in the background.
    """
    created = complaints.create_complaint(db, caller.user, body.description)
    # Commit now so the background task sees the row.
    db.commit()
    if created.classification_state == ComplaintClassificationState.CLASSIFYING:
        background_tasks.add_task(
            complaints.classify_complaint, created.id, created.description, classifier
        )
    return created


@router.get("")
def list_complaints(caller: Reader, db: Db) -> ComplaintList:
    """List the caller's complaints: a tenant's own, or those on accessible properties."""
    return complaints.list_complaints(db, caller.user)


@router.get("/{complaintId}")
def get_complaint(complaint_id: ComplaintId, caller: Reader, db: Db) -> Complaint:
    """Return a complaint's detail with its status history."""
    return complaints.get_complaint(db, caller.user, complaint_id)


@router.post("/{complaintId}/status-changes", status_code=status.HTTP_201_CREATED)
def change_complaint_status(
    complaint_id: ComplaintId,
    body: ComplaintStatusChangeInput,
    caller: Management,
    db: Db,
) -> Complaint:
    """Move a complaint to its next status, optionally with a handling note."""
    return complaints.change_complaint_status(db, caller.user, complaint_id, body)


@router.put("/{complaintId}/classification")
def classify_complaint(
    complaint_id: ComplaintId,
    body: ComplaintClassificationInput,
    caller: Management,
    db: Db,
) -> Complaint:
    """Set a complaint's category and urgency manually."""
    return complaints.classify_complaint_manually(db, caller.user, complaint_id, body)


@router.put("/{complaintId}/photo")
def upload_complaint_photo(
    complaint_id: ComplaintId,
    file: Annotated[UploadFile, File(json_schema_extra={"format": "binary"})],
) -> Complaint:
    """Attach or replace the complaint photo."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get(
    "/{complaintId}/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
def get_complaint_photo(complaint_id: ComplaintId) -> Response:
    """Return the complaint photo."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@categories_router.get("")
def list_complaint_categories(
    caller: Annotated[CurrentUser, Depends(get_verified_user)],
) -> ComplaintCategoryList:
    """Return the categories a complaint can be classified into."""
    return ComplaintCategoryList(items=list(COMPLAINT_CATEGORIES))
