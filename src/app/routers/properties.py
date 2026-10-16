"""Property endpoints. Declared in the contract; not implemented yet."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.schemas.properties import Property, PropertyInput, PropertyList

router = APIRouter(tags=["properties"])

PropertyId = Annotated[UUID, Path(alias="propertyId")]


@router.post("/properties", status_code=status.HTTP_201_CREATED)
def create_property(body: PropertyInput) -> Property:
    """Add a property to the Owner's account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/properties")
def list_properties() -> PropertyList:
    """List the properties the caller may access."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.get("/properties/{propertyId}")
def get_property(property_id: PropertyId) -> Property:
    """Return a property's detail."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.put("/properties/{propertyId}")
def update_property(property_id: PropertyId, body: PropertyInput) -> Property:
    """Replace a property's name, address and bank account."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@router.delete(
    "/properties/{propertyId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_property(property_id: PropertyId) -> None:
    """Delete a property together with its rooms and manager assignments."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
