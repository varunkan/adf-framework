"""Password hashing + session tokens — pure stdlib (ported from monolith auth).

PBKDF2-HMAC-SHA256 salted hashing (never store clear passwords); opaque
``secrets`` session tokens. No framework, no DB.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PBKDF2_ITERS = 120_000


def hash_password(password: str, salt: str = "") -> tuple[str, str]:
    """Return ``(salt_hex, hash_hex)`` (a fresh salt if none supplied)."""
    if not isinstance(password, str) or password == "":
        raise ValueError("password is required")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERS)
    return salt, digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    if not password or not salt_hex or not hash_hex:
        return False
    try:
        _, candidate = hash_password(password, salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, hash_hex)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
