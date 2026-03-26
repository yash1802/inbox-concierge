from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.routes import auth, categories, jobs, sync, threads, users
from app.config import get_settings

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    for _name in ("sqlalchemy.engine", "sqlalchemy.pool"):
        logging.getLogger(_name).setLevel(logging.WARNING)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Inbox Concierge API", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.resolved_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = FastAPI()
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(sync.router)
    api.include_router(jobs.router)
    api.include_router(categories.router)
    api.include_router(threads.router)

    app.mount("/api", api)

    @app.get("/docs", include_in_schema=False)
    async def api_docs_redirect() -> RedirectResponse:
        return RedirectResponse(url="/api/docs")

    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()
