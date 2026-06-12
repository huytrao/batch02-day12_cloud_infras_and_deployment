import time
from fastapi import HTTPException
import redis
from app.config import settings

# Stateless Rate Limiting with Redis
try:
    _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    _memory_store = {}

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def check(self, user_id: str) -> dict:
        now = int(time.time())
        key = f"rate_limit:{user_id}:{now // self.window_seconds}"
        
        if USE_REDIS:
            current = _redis.get(key)
            if current and int(current) >= self.max_requests:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            _redis.incr(key)
            _redis.expire(key, self.window_seconds * 2)
            remaining = self.max_requests - (int(current) + 1 if current else 1)
        else:
            current = _memory_store.get(key, 0)
            if current >= self.max_requests:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            _memory_store[key] = current + 1
            remaining = self.max_requests - (current + 1)
            
        return {"limit": self.max_requests, "remaining": remaining}

rate_limiter_user = RateLimiter(max_requests=10, window_seconds=60)
rate_limiter_admin = RateLimiter(max_requests=100, window_seconds=60)
