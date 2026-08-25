"""Tenant registration and login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.core.deps import DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import Tenant

router = APIRouter(prefix="/api/auth")


class Credentials(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(credentials: Credentials, session: DbSession):
    existing = session.scalar(select(Tenant).where(Tenant.email == credentials.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    if len(credentials.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    tenant = Tenant(
        name=credentials.email.split("@")[0],
        email=credentials.email.lower(),
        password_hash=hash_password(credentials.password),
    )
    session.add(tenant)
    session.commit()
    return TokenResponse(access_token=create_access_token(tenant.id))


@router.post("/login", response_model=TokenResponse)
def login(credentials: Credentials, session: DbSession):
    tenant = session.scalar(select(Tenant).where(Tenant.email == credentials.email.lower()))
    if tenant is None or not verify_password(credentials.password, tenant.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(tenant.id))
