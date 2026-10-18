"""Application settings read from environment variables and an optional .env file."""

from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env")

    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: str | None = None
    invitation_base_url: str = "https://niscala.app"
    database_url: str = "postgresql+psycopg://niscala:niscala@localhost:5432/niscala"
    jwt_secret: str
    invitation_encryption_key: str


@cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
