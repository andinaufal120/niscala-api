"""Password hashing, verification with argon2id, and weak password checks."""

from functools import cache
from itertools import pairwise
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.errors import ApiError

_hasher = PasswordHasher()
_COMMON_PASSWORDS_FILE = Path(__file__).parents[3] / "data" / "common-passwords.txt"
_MIN_PERSONAL_PART_LENGTH = 4
_APP_NAME = "niscala"


@cache
def common_passwords() -> frozenset[str]:
    """Return the lower-cased blocklist of commonly used passwords."""
    lines = _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def _is_run(password: str) -> bool:
    steps = {ord(b) - ord(a) for a, b in pairwise(password)}
    return steps in ({1}, {-1})


def check_password_allowed(
    password: str, *, name: str, email: str, field: str = "password"
) -> None:
    """Raise 422 PASSWORD_TOO_COMMON for a guessable password.

    Blocked: listed common passwords, one repeated character, a whole-string
    ascending or descending run, and passwords containing the app name, the
    email local part or the name (the last two only when at least 4 characters).
    """
    lowered = password.lower()
    personal_parts = [
        email.split("@")[0].lower(),
        name.strip().lower(),
    ]
    if (
        lowered in common_passwords()
        or len(set(password)) == 1
        or _is_run(password)
        or _APP_NAME in lowered
        or any(
            len(part) >= _MIN_PERSONAL_PART_LENGTH and part in lowered
            for part in personal_parts
        )
    ):
        raise ApiError(422, "PASSWORD_TOO_COMMON", field=field)


def hash_password(password: str) -> str:
    """Return a salted argon2id hash of the password."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether the password matches the hash; never raises for a mismatch."""
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError, InvalidHashError:
        return False
