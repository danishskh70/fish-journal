import datetime as dt

import jwt
import pytest

from app import models as m
from app import security as sec
from app.config import settings, validate_settings

PW = "correct-horse-battery"


@pytest.fixture()
def auth(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "jwt_secret", "s" * 48)
    with raw_client.session_factory() as db:
        db.add(m.OwnerAccount(username="owner", password_hash=sec.hash_password(PW)))
        db.commit()
    return raw_client


def login(c, pw=PW, user="owner"):
    return c.post("/api/v1/auth/login", json={"username": user, "password": pw})


def hdr(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_every_business_endpoint_requires_login(auth):
    for path in ("/fish", "/hotels", "/suppliers", "/journals/1", "/history", "/dashboard", "/purchases",
                 "/hotel-sales", "/accounts/hotels", "/accounts/suppliers", "/supplier-payments", "/hotel-payments"):
        r = auth.get("/api/v1" + path)
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"] == "Bearer"
    assert auth.post("/api/v1/journals", json={}).status_code == 401
    assert auth.get("/health").status_code == 200


def test_login_and_access(auth):
    t = login(auth).json()
    assert t["token_type"] == "bearer" and t["expires_in"] == settings.access_token_minutes * 60
    assert auth.get("/api/v1/fish", headers=hdr(t)).status_code == 200
    assert auth.get("/api/v1/auth/me", headers=hdr(t)).json() == {"username": "owner"}


def test_wrong_password_and_unknown_user_look_the_same(auth):
    a, b = login(auth, "wrong-password-1"), login(auth, PW, "nobody")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_lockout_after_repeated_failures(auth):
    for _ in range(settings.login_max_attempts):
        assert login(auth, "bad-password-xx").status_code == 401
    assert login(auth).status_code == 429  # even the right password is refused while locked


def test_tokens_must_be_correct_type_and_signature(auth):
    t = login(auth).json()
    assert auth.get("/api/v1/fish", headers={"Authorization": f"Bearer {t['refresh_token']}"}).status_code == 401
    forged = jwt.encode({"sub": "1", "typ": "access", "ver": 1, "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)}, "x" * 48, algorithm="HS256")
    assert auth.get("/api/v1/fish", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"sub": "1", "typ": "access", "ver": 1}, None, algorithm="none")
    assert auth.get("/api/v1/fish", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401


def test_expired_access_token_rejected(auth, monkeypatch):
    monkeypatch.setattr(settings, "access_token_minutes", -1)
    t = login(auth).json()
    assert auth.get("/api/v1/fish", headers=hdr(t)).status_code == 401


def test_refresh_rotates_and_reuse_kills_all_sessions(auth):
    t1 = login(auth).json()
    t2 = auth.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    assert t2["refresh_token"] != t1["refresh_token"]
    assert auth.get("/api/v1/fish", headers=hdr(t2)).status_code == 200
    # replaying the old refresh token = theft signal
    assert auth.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert auth.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(auth):
    t = login(auth).json()
    assert auth.post("/api/v1/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert auth.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_change_password_invalidates_old_tokens(auth):
    t = login(auth).json()
    r = auth.post("/api/v1/auth/change-password", headers=hdr(t),
                  json={"current_password": "nope-nope-nope", "new_password": "a-brand-new-password"})
    assert r.status_code == 401
    r = auth.post("/api/v1/auth/change-password", headers=hdr(t),
                  json={"current_password": PW, "new_password": "a-brand-new-password"})
    assert r.status_code == 204
    assert auth.get("/api/v1/fish", headers=hdr(t)).status_code == 401
    assert auth.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert login(auth).status_code == 401
    assert login(auth, "a-brand-new-password").status_code == 200
    short = login(auth, "a-brand-new-password").json()
    assert auth.post("/api/v1/auth/change-password", headers=hdr(short),
                     json={"current_password": "a-brand-new-password", "new_password": "short"}).status_code == 422


def test_password_hashing():
    h = sec.hash_password("some-long-password")
    assert h.startswith("scrypt$") and "some-long-password" not in h
    assert sec.verify_password("some-long-password", h)
    assert not sec.verify_password("other-long-password", h)
    assert h != sec.hash_password("some-long-password")  # unique salt
    assert not sec.verify_password("x", "garbage")


def test_server_refuses_to_start_without_strong_secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "jwt_secret", "short")
    with pytest.raises(RuntimeError):
        validate_settings()
    monkeypatch.setattr(settings, "jwt_secret", "k" * 32)
    validate_settings()
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "auth_disabled", True)
    validate_settings()  # explicit local-dev opt-out
