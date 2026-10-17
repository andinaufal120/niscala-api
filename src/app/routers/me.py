"""Endpoints under /me. Declared in the contract; not implemented yet."""

from fastapi import APIRouter, HTTPException, status

from app.schemas.tenants import CurrentLeaseResult

router = APIRouter(prefix="/me", tags=["tenants"])


@router.get("/lease")
def get_my_lease() -> CurrentLeaseResult:
    """Return the calling tenant's active lease, or null when it has ended."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
