"""Schemas for complaints, their classification and status history."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import ApiModel
from app.schemas.tenants import RoomRef


class ComplaintStatus(StrEnum):
    """Where a complaint is in its handling."""

    NEW = "new"
    IN_PROGRESS = "inProgress"
    DONE = "done"


class ComplaintUrgency(StrEnum):
    """How urgent a complaint is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ComplaintClassificationState(StrEnum):
    """Why a complaint has no classification."""

    AWAITING_CLASSIFICATION = "awaitingClassification"
    NOT_CLASSIFIED = "notClassified"


class ComplaintInput(ApiModel):
    """Fields set when submitting a complaint."""

    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10)
    ] = Field(description="At least 10 characters, counted after trimming.")


class ComplaintClassificationInput(ApiModel):
    """A manual classification of a complaint."""

    category: str = Field(
        min_length=1,
        description="One of the categories from /complaint-categories.",
    )
    urgency: ComplaintUrgency


class ComplaintClassification(ApiModel):
    """The category and urgency of a complaint."""

    category: str
    urgency: ComplaintUrgency
    suggested_action: str | None = Field(
        description="Null for a manual classification."
    )


class ComplaintStatusChangeInput(ApiModel):
    """A move of a complaint to its next status."""

    status: ComplaintStatus = Field(description="Must be the next status.")
    handling_note: str | None = None


class ComplaintStatusChange(ApiModel):
    """A recorded move of a complaint to a status."""

    status: ComplaintStatus
    handling_note: str | None
    changed_at: datetime


class PropertyRef(ApiModel):
    """The property a complaint is about."""

    id: UUID
    name: str


class ComplaintSummary(ApiModel):
    """A complaint as shown in the complaint list."""

    id: UUID
    description: str
    status: ComplaintStatus
    property: PropertyRef
    room: RoomRef
    tenant_name: str
    created_at: datetime
    classification: ComplaintClassification | None
    classification_state: ComplaintClassificationState | None = Field(
        description="Null when the complaint is classified or its AI result is withheld."
    )
    classification_withheld: bool = Field(
        description="True when an AI result exists but is withheld."
    )


class Complaint(ComplaintSummary):
    """A complaint with its status history."""

    status_changes: list[ComplaintStatusChange]


class ComplaintList(ApiModel):
    """Complaints visible to the caller."""

    items: list[ComplaintSummary]


class ComplaintCategoryList(ApiModel):
    """Categories a complaint can be classified into."""

    items: list[str]
