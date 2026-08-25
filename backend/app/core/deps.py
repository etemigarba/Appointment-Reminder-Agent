"""Shared FastAPI dependencies: DB session + JWT tenant guard."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.security import decode_access_token
from app.models.entities import Tenant

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def get_current_tenant(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Tenant:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    tenant_id = decode_access_token(credentials.credentials)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Unknown tenant")
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
