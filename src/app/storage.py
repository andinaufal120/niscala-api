"""Storing uploaded files in object storage, or in a local directory."""

import logging
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)

# Keys in `Session.info` of the keys to delete after the outermost commit or rollback.
DELETE_AFTER_COMMIT = "files_to_delete_after_commit"
DELETE_AFTER_ROLLBACK = "files_to_delete_after_rollback"


class FileStore(Protocol):
    """Keeps files by key."""

    def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store the content under the key, replacing any earlier content."""
        ...

    def get(self, key: str) -> bytes:
        """Return the content; raises FileNotFoundError when the key is missing."""
        ...

    def delete(self, key: str) -> None:
        """Remove the key; a missing key is not an error."""
        ...


class LocalFileStore:
    """Keeps files in a directory; for development without object storage."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError(f"Key {key!r} is outside the storage root")
        return path

    def put(self, key: str, content: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class R2FileStore:
    """Keeps files in a Cloudflare R2 bucket through its S3 API."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            region_name="auto",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content, ContentType=content_type
        )

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(key) from error
            raise
        return response["Body"].read()

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("NoSuchKey", "404"):
                raise


def get_file_store() -> FileStore:
    """Return the R2 store when all its settings are given, else a local directory."""
    settings = get_settings()
    values = (
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket,
    )
    if all(value is not None and value.strip() for value in values):
        return R2FileStore(*values)
    logger.warning("R2 is not configured; files go to %s", settings.file_storage_dir)
    return LocalFileStore(settings.file_storage_dir)


def save_file(
    db: Session,
    store: FileStore,
    key: str,
    content: bytes,
    content_type: str,
    *,
    replaces: str | None = None,
) -> None:
    """Put the file now and tie its fate to the session's transaction.

    After the outermost commit the replaced object is deleted; after a rollback
    the new one is. Raises what the store raises, leaving nothing pending.
    """
    store.put(key, content, content_type)
    if replaces is not None:
        db.info.setdefault(DELETE_AFTER_COMMIT, []).append((store, replaces))
    db.info.setdefault(DELETE_AFTER_ROLLBACK, []).append((store, key))


def _delete_all(pending: list[tuple[FileStore, str]]) -> None:
    for store, key in pending:
        try:
            store.delete(key)
        except Exception:
            logger.warning("Deleting the stored file %s failed", key, exc_info=True)


@event.listens_for(Session, "after_commit")
def _delete_replaced_files(db: Session) -> None:
    if db.in_nested_transaction():
        # A savepoint was released; the outer transaction may still roll back.
        return
    db.info.pop(DELETE_AFTER_ROLLBACK, None)
    _delete_all(db.info.pop(DELETE_AFTER_COMMIT, []))


@event.listens_for(Session, "after_rollback")
def _delete_new_files(db: Session) -> None:
    db.info.pop(DELETE_AFTER_COMMIT, None)
    _delete_all(db.info.pop(DELETE_AFTER_ROLLBACK, []))
