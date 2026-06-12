import os
import time
import json
import logging
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import redis

from app.config import settings
from app.auth import verify_token, authenticate_user, create_token
from app.rate_limiter import rate_limiter_user, rate_limiter_admin, USE_REDIS as RL_REDIS
from app.cost_guard import cost_guard, USE_REDIS as CG_REDIS
from utils.mock_llm import ask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"instance-{uuid.uuid4().hex[:6]}")

try:
    _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
    print("✅ Connected to Redis")
except Exception:
    USE_REDIS = False
    _memory_store = {}
    print("⚠️  Redis not available — using in-memory store (not scalable!)")

def save_session(session_id: str, data: dict, ttl_seconds: int = 3600):
    serialized = json.dumps(data)
    if USE_REDIS:
        _redis.setex(f"session:{session_id}", ttl_seconds, serialized)
    else:
        _memory_store[f"session:{session_id}"] = data

def load_session(session_id: str) -> dict:
    if USE_REDIS:
        data = _redis.get(f"session:{session_id}")
        return json.loads(data) if data else {}
    return _memory_store.get(f"session:{session_id}", {})

def append_to_history(session_id: str, role: str, content: str):
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting instance {INSTANCE_ID} - Security layer initialized")
    yield
    logger.info(f"Instance {INSTANCE_ID} shutting down")

app = FastAPI(
    title="Production Agent — Full Stack",
    version="4.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if "server" in response.headers:
        del response.headers["server"]
    return response

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = None

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/token")
def login(body: LoginRequest):
    user = authenticate_user(body.username, body.password)
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": 60,
        "hint": f"Include in header: Authorization: Bearer {token[:20]}...",
    }

@app.post("/ask")
async def ask_agent(body: AskRequest, request: Request, user: dict = Depends(verify_token)):
    username = user["username"]
    role = user["role"]

    limiter = rate_limiter_admin if role == "admin" else rate_limiter_user
    rate_info = limiter.check(username)
    cost_guard.check_budget(username)

    session_id = body.session_id or str(uuid.uuid4())
    append_to_history(session_id, "user", body.question)

    response_text = ask(body.question)

    input_tokens = len(body.question.split()) * 2
    output_tokens = len(response_text.split()) * 2
    usage_cost = cost_guard.record_usage(username, input_tokens, output_tokens)

    append_to_history(session_id, "assistant", response_text)

    return {
        "session_id": session_id,
        "question": body.question,
        "answer": response_text,
        "usage": {
            "requests_remaining": rate_info["remaining"],
            "budget_used_usd": usage_cost,
        },
        "served_by": INSTANCE_ID,
    }

@app.get("/health")
def health():
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
        "storage": "redis" if USE_REDIS else "in-memory",
        "security": "JWT + RateLimit + CostGuard",
    }

@app.get("/ready")
def ready():
    if USE_REDIS:
        try:
            _redis.ping()
        except Exception:
            raise HTTPException(503, "Redis not available")
    return {"ready": True, "instance": INSTANCE_ID}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
