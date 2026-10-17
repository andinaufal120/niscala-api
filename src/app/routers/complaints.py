"""Endpoints under /complaints and /complaint-categories. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, status

from app.schemas.complaints import (
    Complaint,
    ComplaintCategoryList,
    ComplaintClassificationInput,
    ComplaintInput,
    ComplaintList,
    ComplaintStatusChangeInput,
)

router = APIRouter(prefix="/complaints", tags=["complaints"])
categories_router = APIRouter(prefix="/complaint-categories", tags=["complaints"])

ComplaintId = Annotated[UUID, Path(alias="complaintId")]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_complaint(body: ComplaintInput) -> Complaint:
    """Submit a complaint as the calling tenant."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("")
def list_complaints() -> ComplaintList:
    """List the caller's complaints: a tenant's own, or those on accessible properties."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/{complaintId}")
def get_complaint(complaint_id: ComplaintId) -> Complaint:
    """Return a complaint's detail with its status history."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.post("/{complaintId}/status-changes", status_code=status.HTTP_201_CREATED)
def change_complaint_status(
    complaint_id: ComplaintId, body: ComplaintStatusChangeInput
) -> Complaint:
    """Move a complaint to its next status, optionally with a handling note."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/{complaintId}/classification")
def classify_complaint(
    complaint_id: ComplaintId, body: ComplaintClassificationInput
) -> Complaint:
    """Set a complaint's category and urgency manually."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@categories_router.get("")
def list_complaint_categories() -> ComplaintCategoryList:
    """Return the categories a complaint can be classified into."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
