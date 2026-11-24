from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import security as sec
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}|{body.username.lower()}"
    sec.limiter.check(key)
    owner = db.scalar(select(m.OwnerAccount).where(m.OwnerAccount.username == body.username))
    ok = sec.verify_password(body.password, owner.password_hash if owner else sec._DUMMY_HASH)
    if owner is None or not ok:
        sec.limiter.fail(key)
        raise HTTPException(401, "Invalid username or password")
    sec.limiter.ok(key)
    out = sec.issue_token_pair(db, owner)
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    out = sec.rotate_refresh_token(db, body.refresh_token)
    db.commit()
    return out


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    claims = sec.decode_token(body.refresh_token, "refresh")
    row = db.scalar(select(m.RefreshToken).where(m.RefreshToken.jti == claims.get("jti")))
    if row:
        row.revoked = True
        db.commit()
    return Response(status_code=204)


@router.get("/me")
def me(owner: m.OwnerAccount | None = Depends(sec.require_auth)):
    return {"username": owner.username if owner else None}


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChangeIn, owner: m.OwnerAccount | None = Depends(sec.require_auth),
                    db: Session = Depends(get_db)):
    if owner is None:
        raise HTTPException(400, "Authentication is disabled")
    if not sec.verify_password(body.current_password, owner.password_hash):
        raise HTTPException(401, "Current password is wrong")
    owner.password_hash = sec.hash_password(body.new_password)
    owner.token_version += 1  # invalidates every access and refresh token
    sec.revoke_all_refresh_tokens(db, owner.id)
    db.commit()
    return Response(status_code=204)
