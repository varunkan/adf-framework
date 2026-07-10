from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .deps import get_store
from .deps import get_control_plane
from .routes import auth, health, submissions, tenant, validation


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = get_store()
    store.init_schema()
    cp = get_control_plane()
    cp.init_schema()
    yield
    cp.close()
    store.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ANDS Submission Portal API",
        version="1.0.0",
        description="Production API — Postgres, S3, worker queue; domain logic from portal modules.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=(
            r"https://.*\.vercel\.app" if settings.cors_allow_vercel_previews else None
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(tenant.router)
    app.include_router(submissions.router)
    app.include_router(validation.router)

    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi_json():
        return app.openapi()

    return app


app = create_app()
