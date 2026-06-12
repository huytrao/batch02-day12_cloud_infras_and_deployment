"""
Production AI Agent — Final Project (Part 6)

Features:
✅ FastAPI REST API
✅ API Key authentication (X-API-Key header) → HTTP 401 without key
✅ Rate limiting (10 req/min per user) → HTTP 429 when exceeded
✅ Cost guard ($10/month per user) → HTTP 402 when exceeded
✅ /health liveness endpoint
✅ /ready readiness endpoint (checks Redis)
✅ Graceful shutdown (SIGTERM handler)
✅ Stateless design — conversation history in Redis
✅ Structured JSON logging
✅ Security headers middleware
✅ CORS middleware
✅ No secrets in source code (all from env vars)
"""

import os
import sys
import time
import json
import uuid
import signal
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
import redis as redis_module
from fastapi import FastAPI, Depends, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.auth import verify_api_key, create_token, authenticate_user
from app.rate_limiter import rate_limiter_user, rate_limiter_admin
from app.cost_guard import cost_guard
from utils.mock_llm import ask

# ─── Structured JSON Logging ────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Emit logs as JSON for easy parsing in log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.root.handlers = [handler]
logging.root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────

START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"instance-{uuid.uuid4().hex[:6]}")
_shutting_down = False

# ─── Redis connection (stateless storage) ───────────────────────────────────

try:
    _redis = redis_module.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
    logger.info("Connected to Redis at %s", settings.REDIS_URL)
except Exception as exc:
    USE_REDIS = False
    _memory_store: dict = {}
    logger.warning("Redis not available (%s) — using in-memory store (not scalable!)", exc)


# ─── Session helpers (stateless: state in Redis, not in memory) ─────────────

def save_session(session_id: str, data: dict, ttl: int = 3600) -> None:
    serialized = json.dumps(data)
    if USE_REDIS:
        _redis.setex(f"session:{session_id}", ttl, serialized)
    else:
        _memory_store[f"session:{session_id}"] = data


def load_session(session_id: str) -> dict:
    if USE_REDIS:
        raw = _redis.get(f"session:{session_id}")
        return json.loads(raw) if raw else {}
    return _memory_store.get(f"session:{session_id}", {})


def append_to_history(session_id: str, role: str, content: str) -> list:
    """Append a message to the conversation history stored in Redis."""
    session = load_session(session_id)
    history = session.get("history", [])
    history.append(
        {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(history) > 20:          # Keep last 20 turns
        history = history[-20:]
    session["history"] = history
    save_session(session_id, session)
    return history


# ─── Graceful Shutdown (SIGTERM) ────────────────────────────────────────────

def shutdown_handler(signum, frame):
    """
    Handle SIGTERM from container orchestrator.
    1. Stop accepting new requests
    2. Log graceful shutdown message
    3. Exit cleanly
    """
    global _shutting_down
    _shutting_down = True
    logger.info(
        json.dumps({
            "event": "graceful_shutdown",
            "instance": INSTANCE_ID,
            "signal": signum,
        })
    )
    # Give in-flight requests a moment to complete
    time.sleep(2)
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown_handler)


# ─── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        json.dumps({
            "event": "startup",
            "instance": INSTANCE_ID,
            "environment": settings.ENVIRONMENT,
            "redis": USE_REDIS,
        })
    )
    yield
    logger.info(
        json.dumps({"event": "shutdown", "instance": INSTANCE_ID})
    )


# ─── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-ready AI Agent with security, rate limiting, and cost guard.",
    lifespan=lifespan,
    # Hide docs in production
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


# Security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    if _shutting_down:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service is shutting down. Please retry."},
        )
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers.pop("server", None)
    return response


# Request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 1)
    logger.info(
        json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "instance": INSTANCE_ID,
        })
    )
    return response


# ─── Pydantic Models ────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000,
                          description="The question to ask the AI agent")
    user_id: str = Field(default="anonymous", description="User identifier for history tracking")
    session_id: Optional[str] = Field(default=None,
                                       description="Session ID (auto-generated if not provided)")


class LoginRequest(BaseModel):
    username: str
    password: str


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Ops"])
def health():
    """
    Liveness probe — is the container alive?
    Returns 200 if the process is running correctly.
    """
    redis_ok = False
    if USE_REDIS:
        try:
            _redis.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    status = "ok" if (not USE_REDIS or redis_ok) else "degraded"
    return {
        "status": status,
        "instance_id": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "storage": "redis" if USE_REDIS else "in-memory (not scalable)",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/ready", tags=["Ops"])
def ready():
    """
    Readiness probe — is the service ready to receive traffic?
    Returns 200 if Redis is reachable, 503 otherwise.
    """
    if USE_REDIS:
        try:
            _redis.ping()
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Redis not reachable — service not ready.",
            )
    return {"ready": True, "instance": INSTANCE_ID}


@app.post("/auth/token", tags=["Auth"])
def login(body: LoginRequest):
    """
    Get JWT token using username/password.
    Demo users: student/demo123, teacher/teach456
    """
    user = authenticate_user(body.username, body.password)
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": 60,
    }


@app.post("/ask", tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    user_id_from_key: str = Depends(verify_api_key),
):
    """
    Ask the AI agent a question.

    Security:
    - Requires X-API-Key header (401 without it)
    - Rate limited to 10 requests/minute per user (429 when exceeded)
    - Monthly budget of $10/user enforced (402 when exceeded)

    Stateless: conversation history stored in Redis, not in memory.
    """
    # Determine effective user_id
    effective_user_id = body.user_id if body.user_id != "anonymous" else user_id_from_key

    # Rate limit check (10 req/min for regular users)
    rate_info = rate_limiter_user.check(effective_user_id)

    # Cost guard check
    cost_guard.check_budget(effective_user_id)

    # Session management (stateless: state in Redis)
    session_id = body.session_id or str(uuid.uuid4())
    append_to_history(session_id, "user", body.question)

    # Call LLM (mock — no API key needed)
    response_text = ask(body.question)

    # Record usage cost
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(response_text.split()) * 2
    monthly_spent = cost_guard.record_usage(effective_user_id, input_tokens, output_tokens)

    # Store assistant response in history
    append_to_history(session_id, "assistant", response_text)

    logger.info(
        json.dumps({
            "event": "ask",
            "user_id": effective_user_id,
            "session_id": session_id,
            "instance": INSTANCE_ID,
        })
    )

    return {
        "session_id": session_id,
        "question": body.question,
        "answer": response_text,
        "usage": {
            "requests_remaining": rate_info["remaining"],
            "monthly_budget_spent_usd": round(monthly_spent, 6),
        },
        "served_by": INSTANCE_ID,
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
