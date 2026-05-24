"""Password hashing + minimum-strength checks.

Argon2id with parameters tuned to ~250 ms on a 2023-class laptop. `verify`
returns a constant-time bool regardless of which path fails so a caller's
control-flow timing doesn't leak whether the user exists.
"""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
)


MIN_PASSWORD_LENGTH = 12

# Top-100 most common passwords (truncated). We refuse anything in this list
# regardless of length so "Password1234" can't sneak past the length rule.
_BANNED_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "password1234",
        "passw0rd",
        "qwerty",
        "qwerty123",
        "letmein",
        "welcome",
        "welcome1",
        "iloveyou",
        "admin",
        "administrator",
        "changeme",
        "123456",
        "12345678",
        "123456789",
        "1234567890",
        "abc123",
        "monkey",
        "dragon",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "starwars",
    }
)


class WeakPasswordError(ValueError):
    """Raised when a candidate password fails the minimum-strength check."""


def assert_strong(password: str) -> None:
    """Raise WeakPasswordError if the password is too short, banned, or
    obviously low-entropy (single character class, common dictionary form)."""
    if not isinstance(password, str):
        raise WeakPasswordError("password must be a string")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if password.lower() in _BANNED_PASSWORDS:
        raise WeakPasswordError("password is too common")
    # Require at least two distinct character classes — letters, digits,
    # symbols — to avoid all-lowercase or all-digit passwords slipping past
    # length alone.
    classes = sum(
        bool(re.search(p, password))
        for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]")
    )
    if classes < 2:
        raise WeakPasswordError(
            "password must mix at least two character classes (letters, digits, symbols)"
        )


def hash_password(password: str) -> str:
    assert_strong(password)
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time-ish verify. Always exercises the hasher when a stored
    hash exists so the timing profile of "valid user, wrong password" matches
    "valid user, right password"."""
    if password_hash is None:
        # Still spend Argon2 time on a sentinel hash so unknown-user calls
        # don't return faster than known-user calls.
        try:
            _HASHER.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            pass
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# Pre-computed Argon2id hash of the string "unused-dummy-password" so that
# verify_password() against a missing user still performs one full hash check.
_DUMMY_HASH = _HASHER.hash("unused-dummy-password")


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)
