"""Creating invitations and revealing or addressing their tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Invitation

INVITATION_LIFETIME = timedelta(days=7)


def _fernet() -> Fernet:
    return Fernet(get_settings().invitation_encryption_key.encode())


def create_invitation(db: Session, tenant_id: UUID) -> tuple[Invitation, str]:
    """Create an invitation for a tenant and return it with its raw token.

    Only a hash and an encrypted copy of the token are stored. The tenant's
    earlier unused invitations are invalidated. Flushes without committing.
    """
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.execute(
        update(Invitation)
        .where(
            Invitation.tenant_id == tenant_id,
            Invitation.used_at.is_(None),
            Invitation.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    row = Invitation(
        tenant_id=tenant_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_encrypted=_fernet().encrypt(token.encode()).decode(),
        created_at=now,
        expires_at=now + INVITATION_LIFETIME,
    )
    db.add(row)
    db.flush()
    return row, token


def reveal_token(invitation: Invitation) -> str:
    """Return the raw token of an invitation.

    Raises cryptography.fernet.InvalidToken when the stored copy is not valid.
    """
    return _fernet().decrypt(invitation.token_encrypted.encode()).decode()


def invitation_url(token: str) -> str:
    """Return the link a tenant opens to activate their account."""
    base = get_settings().invitation_base_url.rstrip("/")
    return f"{base}/invitations/{token}"
