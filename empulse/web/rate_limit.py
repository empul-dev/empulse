import time
from collections import defaultdict

from empulse.config import settings

WINDOW_SECONDS = 60
MAX_TRACKED_KEYS = 10_000


class ApiRateLimiter:
    """Sliding-window rate limiter for authenticated API usage, keyed per user.

    Same shape as LoginRateLimiter's window counter in `web/auth.py`, just
    keyed by user_id instead of IP/username.
    """

    def __init__(self, requests_per_minute: int = 120):
        self.limit = max(1, requests_per_minute)
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str) -> bool:
        now = time.time()
        if len(self._requests) > MAX_TRACKED_KEYS:
            self._cleanup(now)
        self._requests[key] = [t for t in self._requests[key] if now - t < WINDOW_SECONDS]
        return len(self._requests[key]) >= self.limit

    def record(self, key: str):
        self._requests[key].append(time.time())

    def _cleanup(self, now: float):
        expired = [k for k, ts in self._requests.items() if not ts or now - ts[-1] > WINDOW_SECONDS]
        for k in expired:
            del self._requests[k]


api_limiter = ApiRateLimiter(settings.api_rate_limit_per_minute)
