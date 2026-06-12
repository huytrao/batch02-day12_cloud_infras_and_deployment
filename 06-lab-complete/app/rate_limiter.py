"""
Rate Limiter — Sliding window algorithm using Redis.

Each user is limited to RATE_LIMIT_PER_MINUTE requests per minute.
State stored in Redis so it works across multiple instances (stateless design).
Falls back to in-memory if Redis is not available.
"""
import time
from fastapi import HTTPException
import redis as redis_module

from app.config import settings

# ─── Redis connection ───────────────────────────────────────────────────────
try:
    _redis = redis_module.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    _memory_store: dict = {}


class RateLimiter:
    """
    Fixed-window rate limiter.
    Algorithm: count requests per [window_seconds] window per user.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def check(self, user_id: str) -> dict:
        """
        Check if user is within rate limit.
        Raises HTTP 429 if limit exceeded.
        Returns dict with remaining requests.
        """
        now = int(time.time())
        window = now // self.window_seconds
        key = f"rate_limit:{user_id}:{window}"

        if USE_REDIS:
            current = _redis.get(key)
            count = int(current) if current else 0
            if count >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {self.max_requests} requests/minute.",
                    headers={"Retry-After": str(self.window_seconds - (now % self.window_seconds))},
                )
            pipe = _redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.window_seconds * 2)
            pipe.execute()
            remaining = self.max_requests - count - 1
        else:
            count = _memory_store.get(key, 0)
            if count >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {self.max_requests} requests/minute.",
                    headers={"Retry-After": str(self.window_seconds - (now % self.window_seconds))},
                )
            _memory_store[key] = count + 1
            remaining = self.max_requests - count - 1

        return {
            "limit": self.max_requests,
            "remaining": max(remaining, 0),
            "window_seconds": self.window_seconds,
        }


# Two rate limiters: stricter for regular users, relaxed for admins
rate_limiter_user = RateLimiter(
    max_requests=settings.RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)
rate_limiter_admin = RateLimiter(max_requests=100, window_seconds=60)
