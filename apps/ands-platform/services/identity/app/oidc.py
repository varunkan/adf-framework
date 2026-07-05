"""OIDC identity-provider port + adapters (hexagonal).

The #1 enterprise unlock: sign-in via the customer's own IdP over standard
OpenID Connect Authorization-Code + PKCE, so the signer is an IdP-VERIFIED
principal — not a typed email. Ports & adapters, mirroring the mesh's
SQLite/in-memory pattern:

  * ``OidcProvider``            — the port (discovery → authorize → token +
                                  id_token validation), pure interface.
  * ``StandardOidcProvider``   — the PRODUCTION adapter. Speaks real OIDC:
                                  .well-known discovery, /authorize redirect
                                  with PKCE S256, /token code exchange, and
                                  JWKS RS256 validation of the id_token.
                                  issuer / client_id / client_secret /
                                  redirect_uri are configured from the env.
  * ``InProcessOidcProvider``  — an IN-PROCESS deterministic fake OIDC issuer
                                  (its own signing key + JWKS + token mint),
                                  so the whole flow is TESTED here without any
                                  external IdP — the SQLite/in-memory analogue.

Honesty: this implements OIDC Authorization-Code + PKCE with RS256 id_token
validation. It is NOT a certified IdP, and SCIM provisioning / SAML / SIEM
streaming remain honest roadmap — not claimed here.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

from . import jwt_rs256


@dataclass
class VerifiedIdentity:
    """An IdP-verified principal produced by a successful OIDC exchange."""
    subject: str          # the stable IdP 'sub' — the authoritative identity
    email: str
    name: str
    issuer: str
    email_verified: bool = False

    def as_dict(self) -> dict:
        return {"subject": self.subject, "email": self.email, "name": self.name,
                "issuer": self.issuer, "email_verified": self.email_verified}


@dataclass
class OidcClientConfig:
    """Per-workspace OIDC client configuration (from admin config / env)."""
    issuer: str
    client_id: str
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: str = "openid email profile"


@dataclass
class AuthorizationRequest:
    """What the caller must persist to complete the round-trip: the redirect the
    browser is sent to, plus the state/nonce/verifier bound to this login."""
    authorization_url: str
    state: str
    nonce: str
    code_verifier: str


def make_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256 (RFC 7636)."""
    verifier = jwt_rs256.b64url(secrets.token_bytes(32))
    challenge = jwt_rs256.b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class OidcProvider(Protocol):
    def discover(self, issuer: str) -> dict: ...

    def build_authorization_request(
        self, cfg: OidcClientConfig) -> AuthorizationRequest: ...

    def exchange_code(self, cfg: OidcClientConfig, *, code: str,
                      code_verifier: str,
                      nonce: str | None = None) -> VerifiedIdentity: ...


def _identity_from_claims(claims: dict, issuer: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        subject=str(claims.get("sub") or ""),
        email=str(claims.get("email") or "").strip().lower(),
        name=str(claims.get("name") or "").strip(),
        issuer=str(claims.get("iss") or issuer),
        email_verified=bool(claims.get("email_verified")))


# -- production adapter --------------------------------------------------------
class StandardOidcProvider:
    """Real OIDC over HTTP. Discovers endpoints, builds the /authorize redirect
    with PKCE, exchanges the code at /token and validates the id_token against
    the issuer's JWKS. Network I/O via httpx (already a dependency)."""

    def __init__(self, *, http=None, timeout: float = 10.0) -> None:
        self._http = http
        self._timeout = timeout
        self._disco_cache: dict[str, dict] = {}
        self._jwks_cache: dict[str, dict] = {}

    def _client(self):
        if self._http is not None:
            return self._http
        import httpx
        return httpx.Client(timeout=self._timeout)

    def discover(self, issuer: str) -> dict:
        issuer = issuer.rstrip("/")
        if issuer in self._disco_cache:
            return self._disco_cache[issuer]
        url = f"{issuer}/.well-known/openid-configuration"
        r = self._client().get(url)
        r.raise_for_status()
        doc = r.json()
        self._disco_cache[issuer] = doc
        return doc

    def _jwks(self, jwks_uri: str) -> dict:
        if jwks_uri in self._jwks_cache:
            return self._jwks_cache[jwks_uri]
        r = self._client().get(jwks_uri)
        r.raise_for_status()
        doc = r.json()
        self._jwks_cache[jwks_uri] = doc
        return doc

    def build_authorization_request(
            self, cfg: OidcClientConfig) -> AuthorizationRequest:
        disco = self.discover(cfg.issuer)
        verifier, challenge = make_pkce()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        params = {
            "response_type": "code", "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri, "scope": cfg.scopes,
            "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256"}
        url = disco["authorization_endpoint"] + "?" + urlencode(params)
        return AuthorizationRequest(authorization_url=url, state=state,
                                    nonce=nonce, code_verifier=verifier)

    def exchange_code(self, cfg: OidcClientConfig, *, code: str,
                      code_verifier: str,
                      nonce: str | None = None) -> VerifiedIdentity:
        disco = self.discover(cfg.issuer)
        data = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": cfg.redirect_uri, "client_id": cfg.client_id,
            "code_verifier": code_verifier}
        if cfg.client_secret:
            data["client_secret"] = cfg.client_secret
        r = self._client().post(disco["token_endpoint"], data=data)
        r.raise_for_status()
        tok = r.json()
        id_token = tok.get("id_token")
        if not id_token:
            raise jwt_rs256.JwtError("token response has no id_token")
        jwks = self._jwks(disco["jwks_uri"])
        claims = jwt_rs256.verify_id_token(
            id_token, jwks, issuer=disco.get("issuer", cfg.issuer),
            audience=cfg.client_id, nonce=nonce)
        return _identity_from_claims(claims, cfg.issuer)


# -- in-process test double (deterministic fake issuer) ------------------------
# A module-level RSA key so the (slow) pure-Python keygen runs at most once per
# process — mirroring a real IdP holding one long-lived signing key.
_TEST_KEY: jwt_rs256.RsaKeyPair | None = None


def _test_key() -> jwt_rs256.RsaKeyPair:
    global _TEST_KEY
    if _TEST_KEY is None:
        _TEST_KEY = jwt_rs256.generate_rsa_keypair(bits=2048, kid="ands-test-idp")
    return _TEST_KEY


@dataclass
class _FakeUser:
    subject: str
    email: str
    name: str
    email_verified: bool = True


class InProcessOidcProvider:
    """A fully in-process OIDC issuer: its own signing key + JWKS, and an
    authorize→code→token→id_token round-trip held in memory. No sockets, no
    external IdP — the deterministic analogue of the in-memory/SQLite repos, so
    the real adapter's exact validation path (RS256 + issuer/aud/nonce) is
    exercised end to end in tests and local dev.

    ``authorize(request, subject=...)`` simulates the user consenting at the IdP
    and returns the ``code`` the callback would receive."""

    def __init__(self, issuer: str = "https://idp.test/ands",
                 key: jwt_rs256.RsaKeyPair | None = None) -> None:
        self.issuer = issuer.rstrip("/")
        self.key = key or _test_key()
        self._users: dict[str, _FakeUser] = {}
        # code -> pending exchange context
        self._codes: dict[str, dict] = {}

    # -- test-seam: register the identities the fake IdP knows about ----------
    def register_user(self, subject: str, email: str, name: str = "",
                      email_verified: bool = True) -> None:
        self._users[subject] = _FakeUser(subject, email.strip().lower(),
                                         name.strip(), email_verified)

    def discover(self, issuer: str | None = None) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "response_types_supported": ["code"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"]}

    def jwks(self) -> dict:
        return self.key.jwks()

    def build_authorization_request(
            self, cfg: OidcClientConfig) -> AuthorizationRequest:
        verifier, challenge = make_pkce()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        params = {
            "response_type": "code", "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri, "scope": cfg.scopes,
            "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256"}
        url = f"{self.issuer}/authorize?" + urlencode(params)
        return AuthorizationRequest(authorization_url=url, state=state,
                                    nonce=nonce, code_verifier=verifier)

    def authorize(self, request: AuthorizationRequest, *, subject: str,
                  cfg: OidcClientConfig, nonce: str | None = None) -> str:
        """Simulate the user authenticating + consenting at the IdP. Binds the
        issued code to the PKCE challenge, the client and the nonce, exactly as
        a real authorization server would."""
        if subject not in self._users:
            raise ValueError(f"unknown IdP subject: {subject}")
        code = secrets.token_urlsafe(24)
        challenge = jwt_rs256.b64url(
            hashlib.sha256(request.code_verifier.encode("ascii")).digest())
        self._codes[code] = {
            "subject": subject, "challenge": challenge,
            "client_id": cfg.client_id, "redirect_uri": cfg.redirect_uri,
            "nonce": nonce if nonce is not None else request.nonce}
        return code

    def exchange_code(self, cfg: OidcClientConfig, *, code: str,
                      code_verifier: str,
                      nonce: str | None = None) -> VerifiedIdentity:
        ctx = self._codes.pop(code, None)  # one-time use
        if not ctx:
            raise jwt_rs256.JwtError("invalid or already-used authorization code")
        if ctx["client_id"] != cfg.client_id:
            raise jwt_rs256.JwtError("client_id mismatch on token exchange")
        if ctx["redirect_uri"] != cfg.redirect_uri:
            raise jwt_rs256.JwtError("redirect_uri mismatch on token exchange")
        # verify PKCE: SHA256(verifier) must equal the bound challenge
        got = jwt_rs256.b64url(
            hashlib.sha256(code_verifier.encode("ascii")).digest())
        if not secrets.compare_digest(got, ctx["challenge"]):
            raise jwt_rs256.JwtError("PKCE verification failed")
        user = self._users[ctx["subject"]]
        now = int(time.time())
        claims = {
            "iss": self.issuer, "sub": user.subject, "aud": cfg.client_id,
            "email": user.email, "email_verified": user.email_verified,
            "name": user.name, "nonce": ctx["nonce"],
            "iat": now, "nbf": now, "exp": now + 300}
        id_token = jwt_rs256.encode_id_token(claims, self.key)
        # validate through the SAME path the production adapter uses
        verified = jwt_rs256.verify_id_token(
            id_token, self.jwks(), issuer=self.issuer, audience=cfg.client_id,
            nonce=nonce if nonce is not None else ctx["nonce"])
        return _identity_from_claims(verified, self.issuer)
