from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from sqlalchemy import text

from app.api.routers import auth, catalog, me, trainee, trainer
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis_client
from app.db.session import engine
from app.schemas.common import HealthResponse, ReadyResponse

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger("tactech")


@asynccontextmanager
async def lifespan(_: FastAPI):
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


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


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
