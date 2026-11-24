"""Single-owner authentication: scrypt password hashing, short-lived JWT access tokens,
rotating refresh tokens stored server-side, login throttling."""
import datetime as dt
import hashlib
import hmac
import secrets
import time
import uuid

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models as m
from .config import settings
from .database import get_db

_N, _R, _P = 2**14, 8, 1
bearer = HTTPBearer(auto_error=False)


# ---------- passwords ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def check_password_strength(password: str):
    if len(password) < 10:
        raise HTTPException(422, "Password must be at least 10 characters")


# ---------- tokens ----------
def _unauthorized(msg="Invalid or expired token") -> HTTPException:
    return HTTPException(401, msg, headers={"WWW-Authenticate": "Bearer"})


def make_token(owner: m.OwnerAccount, typ: str, ttl: dt.timedelta, jti: str | None = None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": str(owner.id), "typ": typ, "ver": owner.token_version, "iat": now, "exp": now + ttl,
               "jti": jti or uuid.uuid4().hex}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, typ: str) -> dict:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError:
        raise _unauthorized()
    if claims.get("typ") != typ:
        raise _unauthorized()
    return claims


def issue_token_pair(db: Session, owner: m.OwnerAccount) -> dict:
    access = make_token(owner, "access", dt.timedelta(minutes=settings.access_token_minutes))
    jti = uuid.uuid4().hex
    refresh = make_token(owner, "refresh", dt.timedelta(days=settings.refresh_token_days), jti)
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.refresh_token_days)).replace(tzinfo=None)
    db.add(m.RefreshToken(owner_id=owner.id, jti=jti, expires_at=expires, revoked=False))
    db.flush()
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer",
            "expires_in": settings.access_token_minutes * 60}


def revoke_all_refresh_tokens(db: Session, owner_id: int):
    for t in db.query(m.RefreshToken).filter(m.RefreshToken.owner_id == owner_id, m.RefreshToken.revoked.is_(False)):
        t.revoked = True


def rotate_refresh_token(db: Session, token: str) -> dict:
    claims = decode_token(token, "refresh")
    owner = db.get(m.OwnerAccount, int(claims["sub"]))
    row = db.query(m.RefreshToken).filter(m.RefreshToken.jti == claims.get("jti")).one_or_none()
    if owner is None or row is None or claims.get("ver") != owner.token_version:
        raise _unauthorized()
    if row.revoked:
        # a used/revoked refresh token came back: assume theft, kill every session
        revoke_all_refresh_tokens(db, owner.id)
        db.commit()
        raise _unauthorized("Refresh token already used. Please log in again.")
    row.revoked = True
    return issue_token_pair(db, owner)


# ---------- login throttling (per process) ----------
class LoginLimiter:
    def __init__(self):
        self.fails: dict[str, tuple[int, float]] = {}

    def reset(self):
        self.fails.clear()

    def check(self, key: str):
        count, first = self.fails.get(key, (0, 0.0))
        if count >= settings.login_max_attempts:
            wait = first + settings.login_lock_minutes * 60 - time.time()
            if wait > 0:
                raise HTTPException(429, f"Too many failed logins. Try again in {int(wait // 60) + 1} minute(s).")
            self.fails.pop(key, None)

    def fail(self, key: str):
        count, first = self.fails.get(key, (0, time.time()))
        self.fails[key] = (count + 1, first if count else time.time())

    def ok(self, key: str):
        self.fails.pop(key, None)


limiter = LoginLimiter()


# ---------- request dependency ----------
def require_auth(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    if settings.auth_disabled:
        return None
    if creds is None:
        raise _unauthorized("Not authenticated")
    claims = decode_token(creds.credentials, "access")
    owner = db.get(m.OwnerAccount, int(claims["sub"]))
    if owner is None or claims.get("ver") != owner.token_version:
        raise _unauthorized()
    return owner
