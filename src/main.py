import os
from pathlib import Path
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from infrastructure.database.mongo import init_db
from shared.exceptions import AppError
from infrastructure.config import settings

import logging
import structlog
from integrations.logcenter.log_sender import sender
from domains.machine.routes import router as machine_router

if settings.USE_FORM:
    from domains.pages.routes import router as pages_router
    from domains.users.routes import router as users_router, session_router
    from domains.auth.routes import router as auth_router
    from domains.admin.routes import router as admin_router



BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = os.path.join(BASE_DIR, "static")

logging.basicConfig(level=logging.INFO, format="%(message)s")

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

log = structlog.get_logger(__name__)

try:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
    SENTRY_AVAILABLE = True
except Exception:
    SENTRY_AVAILABLE = False



@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.log_sender = sender
    sender.start_background_flush()

    if settings.USE_FORM:
        await init_db()

    async def _delayed_startup_log():
        await asyncio.sleep(0.3)
        await sender.send(
            level="DEBUG",
            message="sample_machine_startup",
            status="SUCCESS",
            tags=["startup", "server"],
            data={"env": settings.ENV, "version": "0.1.0-dev"},
            spool_on_fail=False,
        )

    asyncio.create_task(_delayed_startup_log())

    yield

    # === SHUTDOWN ===
    try:
        await sender.send(
            level="DEBUG",
            message="Sample Machine shutdown",
            status="SUCCESS",
            tags=["shutdown", "server"],
            data={"env": settings.ENV, "version": "0.1.0-dev"},
            spool_on_fail=False
        )
    finally:
        await sender.stop_background_flush()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version="0.1.0-dev", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.SENTRY_DSN and SENTRY_AVAILABLE:
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.2)
        app.add_middleware(SentryAsgiMiddleware)

    app.mount("/src/static", StaticFiles(directory="src/static"), name="src-static")
    app.mount("/static", StaticFiles(directory="src/static"), name="static")
    app.mount("/templates", StaticFiles(directory="src/static"), name="templates")


    if settings.USE_FORM:
        app.include_router(pages_router)
        app.include_router(users_router)
        app.include_router(session_router)
        app.include_router(auth_router)
        app.include_router(admin_router)
    app.include_router(machine_router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                },
            )


    return app
