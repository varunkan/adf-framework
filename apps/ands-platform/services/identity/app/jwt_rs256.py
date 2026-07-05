"""Minimal RS256 JWT + JWKS — pure stdlib (no cryptography/PyJWT dependency).

Real OIDC identity providers sign the ``id_token`` with RS256 and publish the
public key as a JWK at their JWKS endpoint. To validate that token honestly we
need real RSA signature verification; to run a faithful IN-PROCESS test double
(a deterministic fake issuer) we also need RSA *signing*. Both are implemented
here in pure Python so the whole OIDC flow is testable without external infra or
a native crypto dependency — mirroring the stdlib-only spirit of ``security.py``.

Scope, stated honestly:
  * RS256 (RSASSA-PKCS1-v1_5 over SHA-256) only — the near-universal OIDC
    id_token signing alg. HS256/ES256 are not implemented.
  * RSA verification is ``pow(sig, e, n)`` + a constant-structure PKCS#1 v1.5
    compare; signing is ``pow(m, d, n)``. Standard, but this is not a hardened,
    side-channel-resistant crypto library — for a production IdP integration a
    vetted library (``cryptography``/PyJWT) is the right dependency, and swapping
    this adapter for one is a one-file change (that is the point of the port).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

# DER prefix for an RFC 8017 SHA-256 DigestInfo (PKCS#1 v1.5 EMSA).
_SHA256_DER_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _int_to_b64url(n: int) -> str:
    return b64url(n.to_bytes((n.bit_length() + 7) // 8 or 1, "big"))


def _b64url_to_int(s: str) -> int:
    return int.from_bytes(b64url_decode(s), "big")


# -- RSA keygen (Miller-Rabin) — used only by the in-process test issuer -------
def _is_probable_prime(n: int, k: int = 24) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(k):
        a = 2 + secrets.randbelow(n - 3)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(c):
            return c


@dataclass
class RsaKeyPair:
    n: int
    e: int
    d: int
    kid: str

    def public_jwk(self) -> dict:
        return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
                "n": _int_to_b64url(self.n), "e": _int_to_b64url(self.e)}

    def jwks(self) -> dict:
        return {"keys": [self.public_jwk()]}


def generate_rsa_keypair(bits: int = 2048, kid: str | None = None) -> RsaKeyPair:
    e = 65537
    while True:
        p = _gen_prime(bits // 2)
        q = _gen_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        n = p * q
        d = pow(e, -1, phi)
        return RsaKeyPair(n=n, e=e, d=d, kid=kid or secrets.token_hex(8))


# -- RS256 PKCS#1 v1.5 sign / verify ------------------------------------------
def _emsa_pkcs1_v15(message: bytes, key_bytelen: int) -> int:
    digest = hashlib.sha256(message).digest()
    t = _SHA256_DER_PREFIX + digest
    ps_len = key_bytelen - len(t) - 3
    if ps_len < 8:
        raise ValueError("RSA modulus too small for RS256")
    em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
    return int.from_bytes(em, "big")


def rs256_sign(signing_input: bytes, key: RsaKeyPair) -> bytes:
    klen = (key.n.bit_length() + 7) // 8
    m = _emsa_pkcs1_v15(signing_input, klen)
    sig = pow(m, key.d, key.n)
    return sig.to_bytes(klen, "big")


def rs256_verify(signing_input: bytes, signature: bytes, n: int, e: int) -> bool:
    klen = (n.bit_length() + 7) // 8
    if len(signature) != klen:
        return False
    try:
        expected = _emsa_pkcs1_v15(signing_input, klen).to_bytes(klen, "big")
    except ValueError:
        return False
    recovered = pow(int.from_bytes(signature, "big"), e, n).to_bytes(klen, "big")
    return hmac.compare_digest(recovered, expected)


# -- id_token encode / decode --------------------------------------------------
def encode_id_token(claims: dict, key: RsaKeyPair) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": key.kid}
    seg = (b64url(json.dumps(header, separators=(",", ":")).encode())
           + "." + b64url(json.dumps(claims, separators=(",", ":")).encode()))
    sig = rs256_sign(seg.encode("ascii"), key)
    return seg + "." + b64url(sig)


def decode_header(token: str) -> dict:
    return json.loads(b64url_decode(token.split(".")[0]))


def decode_unverified_claims(token: str) -> dict:
    return json.loads(b64url_decode(token.split(".")[1]))


class JwtError(ValueError):
    """Raised when an id_token fails signature or claim validation."""


def verify_id_token(token: str, jwks: dict, *, issuer: str, audience: str,
                    nonce: str | None = None, now: int | None = None,
                    leeway: int = 120) -> dict:
    """Verify an OIDC id_token against a JWKS. Checks RS256 signature, issuer,
    audience, expiry/nbf and (when supplied) the nonce. Returns the claims."""
    now = int(time.time()) if now is None else now
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtError("malformed token")
    header = decode_header(token)
    if header.get("alg") != "RS256":
        raise JwtError(f"unsupported alg: {header.get('alg')}")
    kid = header.get("kid")
    key = None
    for jwk in (jwks or {}).get("keys", []):
        if jwk.get("kty") == "RSA" and (kid is None or jwk.get("kid") == kid):
            key = jwk
            break
    if not key:
        raise JwtError("no matching signing key in JWKS")
    n = _b64url_to_int(key["n"])
    e = _b64url_to_int(key["e"])
    signing_input = (parts[0] + "." + parts[1]).encode("ascii")
    if not rs256_verify(signing_input, b64url_decode(parts[2]), n, e):
        raise JwtError("signature verification failed")
    claims = json.loads(b64url_decode(parts[1]))
    if issuer and claims.get("iss") != issuer:
        raise JwtError("issuer mismatch")
    aud = claims.get("aud")
    aud_ok = audience in aud if isinstance(aud, list) else aud == audience
    if audience and not aud_ok:
        raise JwtError("audience mismatch")
    exp = claims.get("exp")
    if exp is not None and now > int(exp) + leeway:
        raise JwtError("token expired")
    nbf = claims.get("nbf")
    if nbf is not None and now + leeway < int(nbf):
        raise JwtError("token not yet valid")
    if nonce is not None and claims.get("nonce") != nonce:
        raise JwtError("nonce mismatch")
    return claims
