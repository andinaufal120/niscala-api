"""Schema for the health check."""

from app.schemas.base import ApiModel


class Health(ApiModel):
    """Whether the service can reach its database."""

    status: str
