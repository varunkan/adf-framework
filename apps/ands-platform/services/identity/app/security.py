"""Password hashing + session tokens — pure stdlib (ported from monolith auth).

PBKDF2-HMAC-SHA256 salted hashing (never store clear passwords); opaque
``secrets`` session tokens. No framework, no DB.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PBKDF2_ITERS = 120_000
TOTP_STEP = 30
TOTP_DIGITS = 6


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


# -- TOTP MFA (RFC 6238, stdlib only) ----------------------------------------
def new_totp_secret() -> str:
    """A base32 TOTP shared secret (no padding, for authenticator apps)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % (10 ** TOTP_DIGITS):0{TOTP_DIGITS}d}"


def totp_code(secret: str, at: float | None = None) -> str:
    t = int(at if at is not None else time.time())
    return _hotp(secret, t // TOTP_STEP)


def verify_totp(secret: str, code: str, at: float | None = None,
                window: int = 1) -> bool:
    """Verify a TOTP code, tolerating +/- ``window`` steps of clock skew."""
    if not secret or not str(code or "").strip():
        return False
    t = int(at if at is not None else time.time())
    code = str(code).strip()
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, (t // TOTP_STEP) + w), code):
            return True
    return False


def provisioning_uri(secret: str, account: str,
                     issuer: str = "ANDS Platform") -> str:
    """otpauth:// URI an authenticator app can enrol (QR)."""
    label = quote(f"{issuer}:{account}")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            f"&digits={TOTP_DIGITS}&period={TOTP_STEP}")
