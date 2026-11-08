"""Internal endpoint that triggers the daily jobs."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, Response

from app.config import get_settings
from app.errors import ApiError
from app.services.jobs import run_daily_jobs

router = APIRouter(prefix="/internal/jobs", include_in_schema=False)


@router.post("/daily", status_code=204)
def post_daily_jobs(authorization: Annotated[str | None, Header()] = None):
    """Run the daily jobs for a caller holding the jobs secret.

    Answers 404 when no secret is configured, 401 UNAUTHORIZED for a missing or
    wrong bearer token, and 500 JOBS_FAILED when any job failed.
    """
    secret = (get_settings().jobs_secret or "").strip()
    if not secret:
        raise ApiError(404, "NOT_FOUND")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme != "Bearer" or not hmac.compare_digest(token.encode(), secret.encode()):
        raise ApiError(401, "UNAUTHORIZED")
    if run_daily_jobs():
        raise ApiError(500, "JOBS_FAILED")
    return Response(status_code=204)
