"""Application settings read from environment variables and an optional .env file."""

from functools import cache
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

COMPLAINT_CATEGORIES = (
    "Listrik",
    "Air",
    "Bangunan",
    "Perabot",
    "Kebersihan",
    "Keamanan",
    "Internet",
    "Lainnya",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env")

    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: str | None = None
    firebase_credentials: str | None = None
    invitation_base_url: str = "https://niscala.app"
    database_url: str = "postgresql+psycopg://niscala:niscala@localhost:5432/niscala"
    jwt_secret: str
    invitation_encryption_key: str
    google_client_ids: Annotated[list[str], NoDecode] = []

    @field_validator("google_client_ids", mode="before")
    @classmethod
    def _split_client_ids(cls, value: Any) -> Any:
        """Read a comma-separated list, dropping blanks and surrounding spaces."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
