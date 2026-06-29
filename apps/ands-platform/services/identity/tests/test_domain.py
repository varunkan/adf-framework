"""Pure domain — security, rbac, entitlements."""

import pytest

from app import entitlements, rbac, security


# -- security ----------------------------------------------------------------
def test_password_hash_roundtrip():
    salt, h = security.hash_password("hunter2")
    assert security.verify_password("hunter2", salt, h)
    assert not security.verify_password("wrong", salt, h)


def test_empty_password_raises():
    with pytest.raises(ValueError):
        security.hash_password("")


def test_session_tokens_unique():
    assert security.new_session_token() != security.new_session_token()


# -- rbac --------------------------------------------------------------------
def test_owner_allowed_anything_any_tenant():
    d = rbac.authorize({"role": "owner", "tenant_id": ""}, "transmit",
                       {"tenant_id": "t1"})
    assert d["allowed"] and d["rule"] == "owner_platform_scope"


def test_cross_tenant_denied_for_non_owner():
    d = rbac.authorize({"role": "tenant-admin", "tenant_id": "t1"},
                       "dossier.read", {"tenant_id": "t2"})
    assert not d["allowed"] and d["rule"] == "cross_tenant_denied"


def test_user_lacks_admin_capability():
    d = rbac.authorize({"role": "user", "tenant_id": "t1"}, "admin",
                       {"tenant_id": "t1"})
    assert not d["allowed"] and d["rule"] == "insufficient_capability"


def test_tenant_admin_has_transmit_and_admin():
    p = {"role": "tenant-admin", "tenant_id": "t1"}
    assert rbac.authorize(p, "transmit", {"tenant_id": "t1"})["allowed"]
    assert rbac.authorize(p, "admin", {"tenant_id": "t1"})["allowed"]


# -- entitlements ------------------------------------------------------------
def test_effective_override_wins_over_plan():
    eff = entitlements.effective(["dashboard", "dossiers"],
                                 {"dossiers": False, "fees": True})
    assert eff["dashboard"] == {"enabled": True, "source": "plan"}
    assert eff["dossiers"] == {"enabled": False, "source": "override"}
    assert eff["fees"] == {"enabled": True, "source": "override"}
    assert eff["esign"]["enabled"] is False


def test_entitled_features_and_normalize():
    feats = entitlements.entitled_features(["dashboard", "bogus"], {})
    assert feats == ["dashboard"]
    assert entitlements.normalize_features(["fees", "x", "dashboard"]) == \
        ["dashboard", "fees"]  # catalogue order
    assert entitlements.plan_id_from_name("Team Plan") == "team-plan"
