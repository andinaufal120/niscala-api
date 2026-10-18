"""Password hashing and verification with argon2id."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return a salted argon2id hash of the password."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether the password matches the hash; never raises for a mismatch."""
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError, InvalidHashError:
        return False
