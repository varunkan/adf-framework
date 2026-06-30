"""Pure webhook domain — validation, matching, signing."""

from app import webhooks


def test_validate_requires_http_url_and_generates_secret():
    bad = webhooks.validate_subscription({"url": "ftp://x"})
    assert not bad["valid"]
    ok = webhooks.validate_subscription({"url": "https://hooks.acme.io/ands"})
    assert ok["valid"]
    assert ok["subscription"]["secret"]                 # auto-generated
    assert ok["subscription"]["event_types"] == ["*"]   # default


def test_matches_by_type_and_tenant():
    sub = {"event_types": ["validation.failed"], "tenant_id": "t1"}
    assert webhooks.matches(sub, "validation.failed", "t1")
    assert not webhooks.matches(sub, "transmission.sent", "t1")   # wrong type
    assert not webhooks.matches(sub, "validation.failed", "t2")   # wrong tenant
    wild = {"event_types": ["*"], "tenant_id": None}
    assert webhooks.matches(wild, "anything.at.all", "tX")


def test_signature_is_verifiable_hmac():
    body = '{"a":1}'
    sig = webhooks.sign_payload("topsecret", body)
    assert sig == webhooks.sign_payload("topsecret", body)        # deterministic
    assert sig != webhooks.sign_payload("other", body)            # key-bound
    assert webhooks.sign_payload("", body) == ""                  # no secret


def test_build_delivery_signs_the_payload():
    sub = {"url": "https://x/h", "secret": "s", "event_types": ["*"]}
    d = webhooks.build_delivery(sub, "validation.failed", {"dossier": "e1"})
    assert d["url"] == "https://x/h" and d["event_type"] == "validation.failed"
    assert d["signature"] == webhooks.sign_payload("s", d["payload"])
