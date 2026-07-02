"""Password policy + self-serve reset flow (usability-panel fix F2)."""


def _signup(client, email="reset@acme.example", password="Reset-2026-ok1"):
    r = client.post("/api/identity/auth/signup", json={
        "email": email, "password": password, "company_name": "Acme RA"})
    assert r.status_code == 201, r.text
    return r.json()


def test_signup_enforces_password_policy(client):
    r = client.post("/api/identity/auth/signup", json={
        "email": "weak@acme.example", "password": "short1", "company_name": "A"})
    assert r.status_code == 422
    assert r.json()["rule"] == "password_policy"
    # letters-only also fails
    r = client.post("/api/identity/auth/signup", json={
        "email": "weak@acme.example", "password": "lettersonlypw",
        "company_name": "A"})
    assert r.status_code == 422


def test_reset_request_never_reveals_accounts(client):
    r = client.post("/api/identity/auth/reset/request",
                    json={"email": "ghost@nowhere.example"})
    assert r.status_code == 200
    assert "reset_code" not in r.json()


def test_full_reset_flow(client):
    _signup(client)
    r = client.post("/api/identity/auth/reset/request",
                    json={"email": "reset@acme.example"})
    assert r.status_code == 200
    code = r.json()["reset_code"]          # on-screen delivery (no SMTP here)
    assert len(code) == 8

    # wrong code rejected
    bad = client.post("/api/identity/auth/reset/complete", json={
        "email": "reset@acme.example", "code": "00000000",
        "new_password": "Fresh-2026-pw9"})
    assert bad.status_code == 422

    # weak new password rejected even with the right code
    weak = client.post("/api/identity/auth/reset/complete", json={
        "email": "reset@acme.example", "code": code, "new_password": "tiny1"})
    assert weak.status_code == 422
    assert weak.json()["rule"] == "password_policy"

    ok = client.post("/api/identity/auth/reset/complete", json={
        "email": "reset@acme.example", "code": code,
        "new_password": "Fresh-2026-pw9"})
    assert ok.status_code == 200
    assert ok.json()["accounts_updated"] == 1

    # code is single-use
    again = client.post("/api/identity/auth/reset/complete", json={
        "email": "reset@acme.example", "code": code,
        "new_password": "Fresh-2026-pw9"})
    assert again.status_code == 422

    # old password dead, new one works
    old = client.post("/api/identity/auth/login", json={
        "email": "reset@acme.example", "password": "Reset-2026-ok1"})
    assert old.status_code == 401
    new = client.post("/api/identity/auth/login", json={
        "email": "reset@acme.example", "password": "Fresh-2026-pw9"})
    assert new.status_code == 200


def test_reset_invalidates_existing_sessions(client):
    token = _signup(client, "live@acme.example")["token"]
    me = client.get("/api/identity/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    code = client.post("/api/identity/auth/reset/request",
                       json={"email": "live@acme.example"}).json()["reset_code"]
    client.post("/api/identity/auth/reset/complete", json={
        "email": "live@acme.example", "code": code,
        "new_password": "Fresh-2026-pw9"})
    stale = client.get("/api/identity/auth/me",
                       headers={"Authorization": f"Bearer {token}"})
    assert stale.status_code == 401
