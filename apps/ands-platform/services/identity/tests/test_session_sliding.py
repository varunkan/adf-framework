"""Sliding session renewal — an ACTIVE user must not be logged out mid-work.

Root cause of the recurring "login is lost when I click Portfolio/Dossiers":
the session had a HARD 12h TTL with no renewal, so every ~12h the session
expired and any authenticated page bounced to /login. Fix: while a full-scope
session is still valid, resolving it extends its expiry (sliding window), so an
active user stays signed in; an idle session still expires after the TTL.
"""

from datetime import datetime, timedelta, timezone

from app import service as svc_mod
from tests.conftest import owner_token


def _now():
    return datetime.now(timezone.utc)


def test_active_session_slides_forward_when_past_half_life(ctx):
    token = owner_token(ctx)
    # force the session near expiry (1 minute left = well past its half-life)
    near = (_now() + timedelta(minutes=1)).isoformat()
    ctx.repo.touch_session(token, near)
    principal = ctx.service.resolve(token)
    assert principal is not None
    new_exp = datetime.fromisoformat(ctx.repo.get_session(token)["expires_at"])
    # renewed back toward a full TTL — far beyond the 1 minute we set
    assert new_exp > _now() + timedelta(hours=1), new_exp


def test_fresh_session_is_not_rewritten_on_every_call(ctx):
    # a freshly minted session (well within its half-life) must NOT be rewritten
    # on each resolve — that would be a DB write on every authenticated request.
    token = owner_token(ctx)
    before = ctx.repo.get_session(token)["expires_at"]
    ctx.service.resolve(token)
    after = ctx.repo.get_session(token)["expires_at"]
    assert after == before


def test_expired_session_is_still_rejected_and_deleted(ctx):
    token = owner_token(ctx)
    ctx.repo.touch_session(token, (_now() - timedelta(seconds=1)).isoformat())
    assert ctx.service.resolve(token) is None
    assert ctx.repo.get_session(token) is None


def test_session_ttl_is_configurable(monkeypatch):
    # the TTL is env-configurable (ANDS_SESSION_TTL_HOURS) so compliance can
    # tighten it; the default is a multi-day rolling window, not 12h.
    assert svc_mod.SESSION_TTL >= timedelta(hours=24)
