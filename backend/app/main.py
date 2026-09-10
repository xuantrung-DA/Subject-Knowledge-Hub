import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from .config import settings
from .db import engine
from .errors import AppError


class JsonFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in (
            "request_id",
            "job_id",
            "method",
            "path",
            "status",
            "latency_ms",
            "error_type",
            "error_code",
            "model",
            "retries",
            "cache_hit",
            "usage_unknown",
            "input_tokens",
            "output_tokens",
            "elapsed_seconds",
        ):
            if hasattr(record, key):
                value[key] = getattr(record, key)
        if record.exc_info:
            value["exception_type"] = record.exc_info[0].__name__
        return json.dumps(value, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    from .worker import reconcile_loop

    stop = threading.Event()
    thread = threading.Thread(target=reconcile_loop, args=(stop,), name="job-reconciler", daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=3)
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)


@app.get("/docs", include_in_schema=False)
def docs_alias():
    return RedirectResponse("/api/docs", status_code=307)


def error_response(request, code, message, status):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "request_id": getattr(request.state, "request_id", None)},
    )


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return error_response(request, exc.code, exc.message, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
    return error_response(request, "VALIDATION_ERROR", details, 422)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.detail == "__HUB_BODY_LIMIT__":
        return error_response(request, "UPLOAD_TOO_LARGE", f"File vượt giới hạn {settings.max_upload_mb} MB.", 413)
    return error_response(request, "HTTP_ERROR", str(exc.detail), exc.status_code)


@app.exception_handler(SQLAlchemyError)
async def db_error(request: Request, exc: SQLAlchemyError):
    logger.error(
        "database_error",
        extra={"request_id": getattr(request.state, "request_id", None), "error_type": type(exc).__name__},
    )
    return error_response(request, "DATABASE_UNAVAILABLE", "Không thể truy cập cơ sở dữ liệu. Vui lòng thử lại.", 503)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error(
        "unhandled_error",
        extra={"request_id": getattr(request.state, "request_id", None), "error_type": type(exc).__name__},
    )
    return error_response(request, "INTERNAL_ERROR", "Có lỗi nội bộ. Hãy dùng request ID để kiểm tra log.", 500)


class BodyLimitMiddleware:
    """Bound chunked multipart bodies before Starlette spools them to disk."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = settings.max_upload_mb * 1024 * 1024 + 1024 * 1024
        headers = dict(scope.get("headers", []))
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = 0
        if content_length > limit:
            response = JSONResponse(
                {
                    "error": {
                        "code": "UPLOAD_TOO_LARGE",
                        "message": f"File vượt giới hạn {settings.max_upload_mb} MB.",
                    },
                    "request_id": scope.get("state", {}).get("request_id"),
                },
                status_code=413,
            )
            return await response(scope, receive, send)
        consumed = 0

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    if headers.get(b"content-type", b"").startswith(b"multipart/form-data"):
                        # Starlette closes all temporary files for MultiPartException.
                        # Its Request adapter maps this to HTTP400; our handler
                        # restores413 using this private marker.
                        raise MultiPartException("__HUB_BODY_LIMIT__")
                    raise HTTPException(status_code=413, detail="__HUB_BODY_LIMIT__")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(BodyLimitMiddleware)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uuid4().hex
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if not request.url.path.endswith("/pdf"):
        response.headers["Cache-Control"] = "no-store"
    logger.info(
        "http_request",
        extra={
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        },
    )
    return response


@app.get("/api/health/live")
def liveness():
    return {"status": "live"}


@app.get("/api/health/ready")
def readiness():
    checks = {"database": False, "redis": False, "embedding_schema": False}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database"] = True
            vector_type = conn.execute(
                text(
                    "SELECT format_type(a.atttypid,a.atttypmod) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relname='chunks' AND n.nspname=current_schema() AND a.attname='embedding'"
                )
            ).scalar()
            checks["embedding_schema"] = vector_type == f"vector({settings.openai_embedding_dimensions})"
    except Exception:
        pass
    try:
        import redis

        checks["redis"] = bool(
            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
        )
    except Exception:
        pass
    ready = all(checks.values())
    return JSONResponse(
        {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
            "openai_configured": bool(settings.openai_api_key.strip()),
            "embedding_dimensions": settings.openai_embedding_dimensions,
            "note": None
            if checks["embedding_schema"]
            else "Run migrations. Changing embedding dimensions requires explicit reindex/migration.",
        },
        status_code=200 if ready else 503,
    )


from .api import router as core_router  # noqa: E402 - initialize logging and middleware before route modules
from .chat_api import router as chat_router  # noqa: E402 - initialize logging and middleware before route modules
from .evaluation_api import router as evaluation_router  # noqa: E402 - initialize logging and middleware before route modules

app.include_router(core_router)
app.include_router(chat_router)
app.include_router(evaluation_router)
