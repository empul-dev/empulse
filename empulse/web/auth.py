import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

COOKIE_NAME = "empulse_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


@dataclass
class SessionUser:
    user_id: str      # Emby UUID or "__admin__" for fallback
    username: str      # Display name (loaded from DB)
    role: str          # "admin" or "viewer"


def _encode_user_id(user_id: str) -> str:
    return base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")


def _decode_user_id(encoded: str) -> str:
    # Re-add padding
    padded = encoded + "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(padded).decode()


def create_session_token(secret: str, user_id: str, role: str) -> str:
    """Create an HMAC-signed token: {timestamp}.{nonce}.{user_id_b64}.{role}.{hmac_sig}"""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    uid_b64 = _encode_user_id(user_id)
    payload = f"{ts}.{nonce}.{uid_b64}.{role}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def hash_token(token: str) -> str:
    """SHA-256 hash of a token for DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_session_token(token: str, secret: str) -> SessionUser | None:
    """Verify an HMAC-signed 5-part token. Returns SessionUser or None."""
    try:
        parts = token.split(".")
        if len(parts) != 5:
            return None
        ts, nonce, uid_b64, role, sig = parts
        if role not in ("admin", "viewer"):
            return None
        payload = f"{ts}.{nonce}.{uid_b64}.{role}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        age = time.time() - int(ts)
        if not (0 <= age <= SESSION_MAX_AGE):
            return None
        user_id = _decode_user_id(uid_b64)
        return SessionUser(user_id=user_id, username="", role=role)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


class LoginRateLimiter:
    """In-memory rate limiter for login attempts (IP + account-level)."""

    MAX_TRACKED_KEYS = 10_000

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 300,
        max_account_attempts: int = 10,
        account_window_seconds: int = 600,
    ):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.max_account_attempts = max_account_attempts
        self.account_window = account_window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def _key_limited(self, key: str, max_att: int, window: int) -> bool:
        now = time.time()
        self._attempts[key] = [t for t in self._attempts[key] if now - t < window]
        return len(self._attempts[key]) >= max_att

    def is_limited(self, ip: str, username: str = "") -> bool:
        if len(self._attempts) > self.MAX_TRACKED_KEYS:
            self._cleanup(time.time())
        if self._key_limited(f"ip:{ip}", self.max_attempts, self.window):
            return True
        if username and self._key_limited(
            f"user:{username.lower()}", self.max_account_attempts, self.account_window
        ):
            return True
        return False

    def record(self, ip: str, username: str = ""):
        now = time.time()
        self._attempts[f"ip:{ip}"].append(now)
        if username:
            self._attempts[f"user:{username.lower()}"].append(now)

    def reset(self, ip: str):
        self._attempts.pop(f"ip:{ip}", None)

    def _cleanup(self, now: float):
        max_window = max(self.window, self.account_window)
        expired = [k for k, ts in self._attempts.items()
                   if not ts or now - ts[-1] > max_window]
        for k in expired:
            del self._attempts[k]


login_limiter = LoginRateLimiter()


def check_origin(request: Request) -> bool:
    """Verify the request Origin/Referer matches the server host (CSRF protection).

    Denies requests without Origin or Referer on state-changing methods,
    since browsers always send Origin on cross-origin form POSTs.
    """
    expected_host = request.headers.get("host", "")

    origin = request.headers.get("origin")
    if origin:
        return urlparse(origin).netloc == expected_host

    referer = request.headers.get("referer")
    if referer:
        return urlparse(referer).netloc == expected_host

    # No Origin or Referer — deny for state-changing methods (browsers
    # always send Origin on cross-origin POST/PUT/DELETE).
    return False


# Routes that require admin role
ADMIN_PREFIXES = (
    "/settings",
    "/api/notification-channels",
    "/api/newsletter/",
    "/api/backup",
    "/api/restore",
    "/api/test-connection",
)
ADMIN_METHODS_ROUTES = [
    # (method, prefix) — routes that require admin for specific methods
    ("DELETE", "/api/history/"),
    ("PUT", "/api/users/"),
]


class AuthMiddleware(BaseHTTPMiddleware):
    """Multi-user auth middleware with Emby-based RBAC and CSRF origin checking."""

    EXCLUDED_PREFIXES = ("/login", "/logout", "/static", "/ws", "/api/random-posters", "/api/img/")

    def __init__(self, app, secret: str = ""):
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self.EXCLUDED_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return self._redirect_login(request)

        session_user = verify_session_token(token, self.secret)
        if not session_user:
            return self._redirect_login(request)

        # Check DB for revoked session
        from empulse.database import get_db
        db = get_db()
        token_h = hash_token(token)
        cursor = await db.execute(
            "SELECT username, revoked FROM login_sessions WHERE token_hash = ?",
            [token_h],
        )
        row = await cursor.fetchone()
        if not row or row["revoked"]:
            return self._redirect_login(request)

        # Fill in username from DB
        session_user.username = row["username"] or session_user.user_id

        # CSRF origin check for state-changing methods
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not check_origin(request):
                return Response(status_code=403)

        # RBAC: admin-only routes
        if session_user.role != "admin":
            if any(path.startswith(p) for p in ADMIN_PREFIXES):
                return self._forbidden(request)
            for method, prefix in ADMIN_METHODS_ROUTES:
                if request.method == method and path.startswith(prefix):
                    return self._forbidden(request)

        request.state.user = session_user
        return await call_next(request)

    def _redirect_login(self, request: Request) -> Response:
        if request.headers.get("hx-request"):
            return Response(status_code=401)
        return RedirectResponse("/login", status_code=302)

    def _forbidden(self, request: Request) -> Response:
        if request.headers.get("hx-request"):
            return Response(status_code=403)
        from empulse.app import templates
        return templates.TemplateResponse(
            request, "403.html", status_code=403,
        )
