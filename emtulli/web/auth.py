import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

COOKIE_NAME = "emtulli_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


def create_session_token(secret: str) -> str:
    """Create an HMAC-signed token with timestamp and random nonce."""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    payload = f"{ts}.{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str, secret: str) -> bool:
    """Verify an HMAC-signed token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        ts, nonce, sig = parts
        payload = f"{ts}.{nonce}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        age = time.time() - int(ts)
        return 0 <= age <= SESSION_MAX_AGE
    except (ValueError, TypeError):
        return False


class LoginRateLimiter:
    """Simple in-memory rate limiter for login attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, ip: str) -> bool:
        now = time.time()
        self._attempts[ip] = [t for t in self._attempts[ip] if now - t < self.window]
        return len(self._attempts[ip]) >= self.max_attempts

    def record(self, ip: str):
        self._attempts[ip].append(time.time())

    def reset(self, ip: str):
        self._attempts.pop(ip, None)


login_limiter = LoginRateLimiter()


def check_origin(request: Request) -> bool:
    """Verify the request Origin/Referer matches the server host (CSRF protection)."""
    expected_host = request.headers.get("host", "")

    origin = request.headers.get("origin")
    if origin:
        return urlparse(origin).netloc == expected_host

    referer = request.headers.get("referer")
    if referer:
        return urlparse(referer).netloc == expected_host

    # No Origin or Referer — allow (same-origin or non-browser client)
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """Password-based auth middleware with CSRF origin checking."""

    EXCLUDED_PREFIXES = ("/login", "/static", "/ws")

    def __init__(self, app, password: str = "", secret: str = ""):
        super().__init__(app)
        self.password = password
        self.secret = secret

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.password:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in self.EXCLUDED_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if token and verify_session_token(token, self.secret):
            # CSRF origin check for state-changing methods
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                if not check_origin(request):
                    return Response(status_code=403)
            return await call_next(request)

        # Check if HTMX request
        if request.headers.get("hx-request"):
            return Response(status_code=401)

        return RedirectResponse("/login", status_code=302)
