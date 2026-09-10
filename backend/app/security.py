import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .errors import AppError
from .models import SessionRecord, Subject, User, utcnow

logger = logging.getLogger(__name__)
_local_limits: dict[str, deque] = defaultdict(deque)
_limit_lock = threading.Lock()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_session(db: Session, user_id: str):
    token = secrets.token_urlsafe(32)
    session = SessionRecord(
        user_id=user_id,
        token_hash=token_hash(token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(days=settings.session_days),
    )
    db.add(session)
    return token, session


def validate_origin(request: Request):
    origin = request.headers.get("origin")
    if origin:
        allowed = {entry.strip().rstrip("/") for entry in settings.allowed_origins.split(",")}
        if origin.rstrip("/") not in allowed:
            raise AppError("CSRF_ORIGIN", "Nguồn yêu cầu không được phép.", 403)


def check_rate(key: str, limit: int, window: int = 60):
    """Redis atomic fixed-window counter with a bounded process-local fallback."""
    bucket = int(time.time()) // window
    redis_key = f"hub:rate:{key}:{bucket}"
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        # One Lua command prevents a process crash between INCR and EXPIRE.
        count = int(
            client.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]); end; return n",
                1,
                redis_key,
                window + 1,
            )
        )
    except Exception:
        # Readiness reports Redis failure. Authentication still works locally;
        # the fallback is process-local and intentionally does not claim global limits.
        with _limit_lock:
            now = time.monotonic()
            queue = _local_limits[key]
            while queue and queue[0] < now - window:
                queue.popleft()
            queue.append(now)
            count = len(queue)
            if len(_local_limits) > 10000:
                stale = [k for k, q in _local_limits.items() if not q or q[-1] < now - window]
                for old in stale:
                    _local_limits.pop(old, None)
    if count > limit:
        raise AppError("RATE_LIMIT", "Quá nhiều yêu cầu. Vui lòng thử lại sau một phút.", 429)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token or len(token) > 200:
        raise AppError("AUTH_REQUIRED", "Vui lòng đăng nhập.", 401)
    session = db.scalar(
        select(SessionRecord).where(SessionRecord.token_hash == token_hash(token), SessionRecord.expires_at > utcnow())
    )
    if session is None:
        raise AppError("AUTH_REQUIRED", "Phiên đăng nhập đã hết hạn.", 401)
    user = db.get(User, session.user_id)
    if user is None:
        raise AppError("AUTH_REQUIRED", "Phiên đăng nhập không hợp lệ.", 401)
    request.state.session = session
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        validate_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(csrf, session.csrf_token):
            raise AppError("CSRF_INVALID", "Phiên bảo mật không hợp lệ. Vui lòng tải lại trang.", 403)
        if request.url.path.endswith("/chat"):
            check_rate(f"chat:{user.id}", settings.chat_rate_limit_per_minute)
    return user


def require_subject(db: Session, user_id: str, subject_id: str, *, lock: bool = False) -> Subject:
    query = select(Subject).where(Subject.id == subject_id, Subject.user_id == user_id, Subject.deleted_at.is_(None))
    if lock:
        query = query.with_for_update(key_share=True)
    subject = db.scalar(query)
    if subject is None:
        raise AppError("SUBJECT_NOT_FOUND", "Không tìm thấy môn học.", 404)
    return subject
