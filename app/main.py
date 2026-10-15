from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import socketio
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.routers import (
    admin_exercises,
    admin_verification,
    auth,
    billing,
    catalog,
    chat,
    coach,
    coaches,
    content,
    me,
    support,
    trainee,
    trainer,
)
from app.core.config import get_settings
from app.core.exceptions import AppError, RateLimitError
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis_client
from app.core.storage import ensure_upload_dir
from app.db.session import engine
from app.realtime.chat_hub import sio
from app.schemas.common import HealthResponse, ReadyResponse

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger("tactech")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_upload_dir(settings)
    logger.info("startup", env=settings.app_env)
    yield
    logger.info("shutdown")


app = FastAPI(
    title="TacTech API",
    description="Production backend for the TacTech trainer/trainee gym app.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=(
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
        r"|https://[a-z0-9-]+\.ngrok(-free)?\.(app|io|dev)"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(trainer.router)
app.include_router(trainee.router)
app.include_router(catalog.router)
app.include_router(support.router)
app.include_router(content.router)
app.include_router(coach.router)
app.include_router(coaches.router)
app.include_router(billing.router)
app.include_router(admin_verification.router)
app.include_router(admin_exercises.router)
app.include_router(chat.router)
ensure_upload_dir(settings)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    content: dict = {"detail": exc.message}
    if exc.code:
        content["code"] = exc.code
    if exc.fields:
        content["fields"] = exc.fields
    if getattr(exc, "extra", None):
        content.update(exc.extra)
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimitError):
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers or None)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path, method=request.method)
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_error")
        raise
    duration_ms = round((perf_counter() - started) * 1000, 2)
    logger.info("request", status_code=response.status_code, duration_ms=duration_ms)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name)


@app.get("/ready", response_model=ReadyResponse, tags=["system"])
def ready() -> ReadyResponse:
    postgres_ok = False
    redis_ok = False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        logger.exception("postgres_unready")
    try:
        redis_ok = create_redis_client().ping() is True
    except Exception:
        logger.exception("redis_unready")
    status = "ok" if postgres_ok and redis_ok else "degraded"
    return ReadyResponse(status=status, postgres=postgres_ok, redis=redis_ok)


# Socket.IO at `/socket.io` — connect with auth: { token: <accessJWT> }
# Events: chat.message, chat.thread.updated, chat.read, chat.typing,
#          chat.call.incoming, chat.call.ended
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)
