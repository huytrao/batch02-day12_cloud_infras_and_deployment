"""
Production AI Agent — Final Project
Tích hợp Lab 4 (Security, Rate Limit, Cost Guard) và Lab 5 (Stateless, Health Checks, Graceful Shutdown)

Dự án này sử dụng mock_llm làm agent cơ sở (có thể thay thế bằng LLM thật sau).
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

import uvicorn
import redis as redis_module
from fastapi import FastAPI, Depends, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dotenv import load_dotenv
load_dotenv()

from app.config import settings
from app.auth import verify_api_key, create_token, authenticate_user, verify_token
from app.rate_limiter import rate_limiter_user, rate_limiter_admin
from app.cost_guard import cost_guard
from utils.mock_llm import ask

# ─── Structured JSON Logging ────────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
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

handler_stream = logging.StreamHandler()
handler_stream.setFormatter(JSONFormatter())
logging.root.handlers = [handler_stream]
logging.root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

# ─── Constants & Globals ────────────────────────────────────────────────────
START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"instance-{uuid.uuid4().hex[:6]}")
_shutting_down = False
_in_flight_requests = 0

# ─── Redis Connection (Stateless) ───────────────────────────────────────────
try:
    _redis = redis_module.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
    logger.info("✅ Connected to Redis at %s", settings.REDIS_URL)
except Exception as exc:
    USE_REDIS = False
    _memory_store: dict = {}
    logger.warning("⚠️ Redis not available (%s) — using in-memory store (not scalable!)", exc)

# ─── Session Helpers (Stateless) ────────────────────────────────────────────
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
    session = load_session(session_id)
    history = session.get("history", [])
    history.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if len(history) > 20:
        history = history[-20:]
    session["history"] = history
    save_session(session_id, session)
    return history

# ─── Graceful Shutdown (Lab 5) ──────────────────────────────────────────────
def shutdown_handler(signum, frame):
    global _shutting_down
    _shutting_down = True
    logger.info(json.dumps({
        "event": "graceful_shutdown",
        "instance": INSTANCE_ID,
        "signal": signum,
    }))
    # Wait for in-flight requests to complete
    timeout = 30
    elapsed = 0
    while _in_flight_requests > 0 and elapsed < timeout:
        logger.info(f"Waiting for {_in_flight_requests} in-flight requests...")
        time.sleep(1)
        elapsed += 1
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(json.dumps({"event": "startup", "instance": INSTANCE_ID, "redis": USE_REDIS}))
    yield
    logger.info(json.dumps({"event": "shutdown", "instance": INSTANCE_ID}))

# ─── FastAPI App ────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-ready AI Agent with security, rate limiting, and cost guard.",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_and_tracking_middleware(request: Request, call_next):
    global _in_flight_requests
    if _shutting_down:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service is shutting down. Please retry later."},
        )
    
    _in_flight_requests += 1
    start = time.time()
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if "server" in response.headers:
            del response.headers["server"]
        
        duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "instance": INSTANCE_ID,
        }))
        return response
    finally:
        _in_flight_requests -= 1

# ─── Models ─────────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    user_id: str = Field(default="anonymous")
    session_id: str | None = None

class LoginRequest(BaseModel):
    username: str
    password: str

# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Ops"])
def health():
    """Liveness probe (Lab 5)"""
    redis_ok = False
    if USE_REDIS:
        try:
            _redis.ping()
            redis_ok = True
        except:
            pass
    return {
        "status": "ok" if (not USE_REDIS or redis_ok) else "degraded",
        "instance_id": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.ENVIRONMENT,
    }

@app.get("/ready", tags=["Ops"])
def ready():
    """Readiness probe (Lab 5)"""
    if USE_REDIS:
        try:
            _redis.ping()
        except:
            raise HTTPException(503, "Redis not reachable")
    return {"ready": True, "instance": INSTANCE_ID}

@app.post("/auth/token", tags=["Auth"])
def login(body: LoginRequest):
    """Get JWT token (Lab 4)"""
    user = authenticate_user(body.username, body.password)
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": 60,
    }

@app.post("/ask", tags=["Agent"])
async def ask_agent(body: AskRequest, request: Request, user_id_from_key: str = Depends(verify_api_key)):
    """Protected Agent Endpoint — Combines Lab 4 & 5"""
    effective_user_id = body.user_id if body.user_id != "anonymous" else user_id_from_key

    # Lab 4: Rate Limiting
    rate_info = rate_limiter_user.check(effective_user_id)

    # Lab 4: Cost Guard
    cost_guard.check_budget(effective_user_id)

    # Agent Logic
    response_text = ask(body.question)

    # Lab 4: Record Cost
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(response_text.split()) * 2
    monthly_spent = cost_guard.record_usage(effective_user_id, input_tokens, output_tokens)

    # Lab 5: Stateless Session
    session_id = body.session_id or str(uuid.uuid4())
    append_to_history(session_id, "user", body.question)
    history = append_to_history(session_id, "assistant", response_text)

    return {
        "session_id": session_id,
        "question": body.question,
        "answer": response_text,
        "turn": len([m for m in history if m["role"] == "user"]),
        "usage": {
            "requests_remaining": rate_info["remaining"],
            "monthly_budget_spent_usd": round(monthly_spent, 6),
        },
        "served_by": INSTANCE_ID,
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, timeout_graceful_shutdown=30)
