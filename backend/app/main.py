"""Appointment Reminder Agent — FastAPI application entrypoint."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.llm_client import LLMClient
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.google_oauth import router as google_oauth_router
from app.api.health import router as health_router
from app.api.webhooks import router as webhooks_router
from app.core.db import make_engine, make_session_factory
from app.core.logging_config import log_requests, setup_logging
from app.models.entities import Base


def create_app(
    database_url: str | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    setup_logging(os.environ.get("APP_LOG_LEVEL", "INFO"))
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(database_url)
        Base.metadata.create_all(engine)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        app.state.llm_client = llm_client
        yield
        engine.dispose()

    allowed_origins = os.environ.get("APP_CORS_ORIGINS", "http://localhost:5173").split(",")
    app = FastAPI(title="Appointment Reminder Agent", version="0.4.0", lifespan=lifespan)
    app.middleware("http")(log_requests)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in allowed_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(google_oauth_router)
    app.include_router(webhooks_router)
    app.include_router(admin_router)
    return app


app = create_app()
