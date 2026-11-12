"""Application settings read from environment variables and an optional .env file."""

import re
from functools import cache
from pathlib import Path
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

FINGERPRINT = re.compile(r"([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}", re.ASCII)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env")

    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: str | None = None
    firebase_credentials: str | None = None
    invitation_base_url: str = "https://niscala.app"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    file_storage_dir: Path = Path("var/files")
    database_url: str = "postgresql+psycopg://niscala:niscala@localhost:5432/niscala"
    jwt_secret: str
    jobs_secret: str | None = None
    invitation_encryption_key: str
    google_client_ids: Annotated[list[str], NoDecode] = []
    google_play_package_name: str | None = None
    google_play_credentials: str | None = None
    google_play_rtdn_audience: str | None = None
    google_play_rtdn_service_account: str | None = None

    android_cert_sha256: Annotated[list[str], NoDecode] = []

    @field_validator("google_client_ids", "android_cert_sha256", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        """Read a comma-separated list, dropping blanks and surrounding spaces."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("android_cert_sha256")
    @classmethod
    def _check_fingerprints(cls, values: list[str]) -> list[str]:
        """Require 32 colon-separated hex bytes per entry; store them upper-cased."""
        for value in values:
            if not FINGERPRINT.fullmatch(value):
                raise ValueError("expected 32 hexadecimal bytes separated by colons")
        return [value.upper() for value in values]


@cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
