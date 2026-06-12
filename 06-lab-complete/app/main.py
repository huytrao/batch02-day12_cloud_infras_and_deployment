"""
Production AI Agent — Final Project (Part 6)
Personal Diary Chatbot Backend (RAG Enabled)

Features:
✅ FastAPI REST API with RAG Chatbot Integration
✅ API Key authentication (X-API-Key header)
✅ JWT Token authentication (/auth/token)
✅ Rate limiting (10 req/min per user) via Redis
✅ Cost guard ($10/month per user) via Redis
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
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

import uvicorn
import redis as redis_module
from fastapi import FastAPI, Depends, HTTPException, Header, Request, Response, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ─── Load Environment Variables ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

from app.config import settings
from app.auth import verify_api_key, create_token, authenticate_user
from app.rate_limiter import rate_limiter_user, rate_limiter_admin
from app.cost_guard import cost_guard
from utils.mock_llm import ask

# Setup paths for RAG imports dynamically
app_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(app_dir, "src")
sys.path.append(src_dir)
sys.path.append(os.path.join(src_dir, "Indexingstep"))
sys.path.append(os.path.join(src_dir, "Retrivel_And_Generation"))

# Import RAG modules
try:
    from Indexingstep.pipeline import DiaryIndexingPipeline
    from Retrivel_And_Generation.Retrieval_And_Generator import create_rag_system, DiaryRAGSystem
    RAG_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: RAG modules not available: {e}")
    RAG_MODULES_AVAILABLE = False

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


# Configure logging to go to stream (console) and log file
log_dir = os.path.join(app_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "service.log")

handler_stream = logging.StreamHandler()
handler_stream.setFormatter(JSONFormatter())

handler_file = logging.FileHandler(log_file)
handler_file.setFormatter(JSONFormatter())

logging.root.handlers = [handler_stream, handler_file]
logging.root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────

START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"instance-{uuid.uuid4().hex[:6]}")
_shutting_down = False

# In-memory cache for RAG systems if Redis isn't used or as a fallback
rag_systems_cache: Dict[int, Any] = {}

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


# ─── RAG Helper functions ───────────────────────────────────────────────────

def format_error_message(errors) -> str:
    """Convert error list to string for API response."""
    if isinstance(errors, list):
        return '; '.join(str(e) for e in errors)
    return str(errors) if errors else 'Unknown error'


def get_user_paths(user_id: int) -> Dict[str, str]:
    """Get all paths for a user."""
    # Ensure paths are absolute and accessible
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return {
        "vector_db_path": os.path.join(base_dir, "VectorDB", f"user_{user_id}_vector_db"),
        "diary_db_path": os.path.join(base_dir, "app", "src", "streamlit_app", "backend", f"user_{user_id}_diary.db"),
        "base_vector_path": os.path.join(base_dir, "VectorDB")
    }


def get_pipeline_config(user_id: int) -> Dict[str, Any]:
    """Get configuration for DiaryIndexingPipeline."""
    paths = get_user_paths(user_id)
    return {
        "db_path": paths["diary_db_path"],
        "persist_directory": paths["vector_db_path"],
        "collection_name": f"user_{user_id}_diary_entries",
        "google_api_key": os.getenv("GOOGLE_API_KEY"),
        "chunk_size": 800,
        "chunk_overlap": 100,
        "batch_size": 50,
        "user_id": user_id
    }


def check_vector_db_exists(user_id: int) -> bool:
    """Check if vector database exists for user."""
    paths = get_user_paths(user_id)
    return os.path.exists(paths["vector_db_path"])


def get_document_count(user_id: int) -> int:
    """Get document count from vector database."""
    try:
        if user_id in rag_systems_cache:
            return rag_systems_cache[user_id].get_document_count()
        
        if not check_vector_db_exists(user_id):
            return 0
        
        paths = get_user_paths(user_id)
        temp_rag = create_rag_system(
            user_id=user_id,
            base_vector_path=paths["base_vector_path"],
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        if temp_rag:
            return temp_rag.get_document_count()
        return 0
    except Exception as e:
        logger.error(f"Error getting document count for user {user_id}: {e}")
        return 0


def get_or_create_rag_system(user_id: int) -> Any:
    """Get existing RAG system or create new one."""
    if user_id not in rag_systems_cache:
        if not check_vector_db_exists(user_id):
            raise HTTPException(
                status_code=404,
                detail=f"Vector database not found for user {user_id}. Please run indexing first."
            )
        
        paths = get_user_paths(user_id)
        rag_system = create_rag_system(
            user_id=user_id,
            base_vector_path=paths["base_vector_path"],
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        if not rag_system:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create RAG system for user {user_id}"
            )
        rag_systems_cache[user_id] = rag_system
        logger.info(f"Created RAG system for user {user_id}")
    
    return rag_systems_cache[user_id]


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
    description="Production-ready RAG Personal Diary Chatbot with security, rate limiting, and cost guard.",
    lifespan=lifespan,
    # Hide docs in production
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


class DiaryEntry(BaseModel):
    date: str
    content: str
    tags: str = ""


class IndexRequest(BaseModel):
    user_id: int
    clear_existing: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class QueryResponse(BaseModel):
    user_id: int
    response: str
    processing_time: float
    documents_used: int
    fast_mode: bool


class IndexResponse(BaseModel):
    user_id: int
    status: str
    documents_processed: int
    chunks_created: int
    vector_db_path: str
    processing_time: float
    error: Optional[str] = None


class UserStatusResponse(BaseModel):
    user_id: int
    status: str
    document_count: int
    vector_db_path: str
    last_updated: Optional[str] = None
    error: Optional[str] = None


# ─── Operations & Auth Endpoints ─────────────────────────────────────────────

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
    google_api_key = os.getenv("GOOGLE_API_KEY")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vector_db_base = os.path.join(base_dir, "VectorDB")

    return {
        "status": status,
        "instance_id": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "storage": "redis" if USE_REDIS else "in-memory (not scalable)",
        "environment": settings.ENVIRONMENT,
        "google_api_configured": bool(google_api_key),
        "vector_db_base_exists": os.path.exists(vector_db_base),
        "cached_users": list(rag_systems_cache.keys()),
        "timestamp": datetime.now().isoformat()
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


# ─── Production Ask Agent Endpoint (Satisfies Codelab checks) ───────────────────

@app.post("/ask", tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    user_id_from_key: str = Depends(verify_api_key),
):
    """
    Ask the AI agent a question. Enforces API Key, rate limits and cost guards.
    Uses RAG if the database is configured, falls back to mock LLM.
    """
    effective_user_id = body.user_id if body.user_id != "anonymous" else user_id_from_key

    # Rate limit check (10 req/min for regular users)
    rate_info = rate_limiter_user.check(effective_user_id)

    # Cost guard check
    cost_guard.check_budget(effective_user_id)

    # Call RAG if configured, otherwise fall back to mock LLM
    try:
        # Convert user_id to int if possible, otherwise default to 1
        try:
            numeric_user_id = int(effective_user_id.replace("user_", "").replace("test", "1"))
        except ValueError:
            numeric_user_id = 1
            
        if RAG_MODULES_AVAILABLE and check_vector_db_exists(numeric_user_id):
            rag_system = get_or_create_rag_system(numeric_user_id)
            response_text = rag_system.generate_contextual_response(
                query=body.question,
                chat_history=[]
            )
        else:
            response_text = ask(body.question)
    except Exception as e:
        logger.warning(f"RAG query failed or not initialized: {e}. Falling back to mock LLM.")
        response_text = ask(body.question)

    # Record usage cost
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(response_text.split()) * 2
    monthly_spent = cost_guard.record_usage(effective_user_id, input_tokens, output_tokens)

    # Session management (stateless: state in Redis)
    session_id = body.session_id or str(uuid.uuid4())
    append_to_history(session_id, "user", body.question)
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


# ─── RAG Service Endpoints (Enforces API Key protection) ──────────────────────

@app.get("/")
async def root():
    """Metadata root route."""
    return {
        "message": "Personal Diary RAG Service is running in Production",
        "version": "1.0.0",
        "instance_id": INSTANCE_ID,
        "cached_users": list(rag_systems_cache.keys()),
    }


@app.get("/users/{user_id}/ai-availability", tags=["RAG Troubleshooting"])
async def check_ai_availability(user_id: int, user_id_from_key: str = Depends(verify_api_key)):
    """Check AI availability and provide detailed status for troubleshooting."""
    try:
        availability_info = {
            "user_id": user_id,
            "overall_status": "checking",
            "checks": {
                "rag_modules": {
                    "available": RAG_MODULES_AVAILABLE,
                    "status": "✅ Available" if RAG_MODULES_AVAILABLE else "❌ Not Available",
                    "details": "Required modules: DiaryIndexingPipeline, DiaryRAGSystem"
                },
                "google_api_key": {
                    "configured": bool(os.getenv("GOOGLE_API_KEY")),
                    "status": "✅ Configured" if os.getenv("GOOGLE_API_KEY") else "❌ Not Configured",
                    "details": "Required for embeddings and LLM responses"
                },
                "vector_database": {
                    "exists": check_vector_db_exists(user_id),
                    "status": "✅ Exists" if check_vector_db_exists(user_id) else "⚠️ Not Found",
                    "path": get_user_paths(user_id)["vector_db_path"]
                },
                "document_count": {
                    "count": get_document_count(user_id),
                    "status": "✅ Has Documents" if get_document_count(user_id) > 0 else "⚠️ Empty",
                    "details": f"{get_document_count(user_id)} documents indexed"
                }
            },
            "recommendations": [],
            "actions": []
        }
        
        if not RAG_MODULES_AVAILABLE:
            availability_info["overall_status"] = "unavailable"
            availability_info["recommendations"].append("Install missing RAG modules")
            availability_info["actions"].append({
                "action": "check_imports",
                "description": "Verify DiaryIndexingPipeline and DiaryRAGSystem imports"
            })
        elif not os.getenv("GOOGLE_API_KEY"):
            availability_info["overall_status"] = "not_configured"
            availability_info["recommendations"].append("Configure Google API key")
            availability_info["actions"].append({
                "action": "set_api_key",
                "description": "Add GOOGLE_API_KEY to environment variables"
            })
        elif not check_vector_db_exists(user_id):
            availability_info["overall_status"] = "needs_indexing"
            availability_info["recommendations"].append("Create vector database for user")
            availability_info["actions"].append({
                "action": "initial_index",
                "endpoint": f"/users/{user_id}/auto-index-new-entry",
                "description": "Run initial indexing to create vector database"
            })
        elif get_document_count(user_id) == 0:
            availability_info["overall_status"] = "empty_database"
            availability_info["recommendations"].append("Add diary entries or rebuild index")
            availability_info["actions"].append({
                "action": "check_diary_entries",
                "description": "Verify user has diary entries in database"
            })
            availability_info["actions"].append({
                "action": "rebuild_index",
                "endpoint": f"/users/{user_id}/auto-index-new-entry",
                "description": "Rebuild vector database from existing entries"
            })
        else:
            availability_info["overall_status"] = "available"
            availability_info["recommendations"].append("AI is ready for use")
            availability_info["actions"].append({
                "action": "query_ready",
                "endpoint": f"/users/{user_id}/query",
                "description": "AI is ready to answer questions"
            })
        
        availability_info["cache_status"] = {
            "user_cached": user_id in rag_systems_cache,
            "total_cached_users": len(rag_systems_cache),
            "cached_users": list(rag_systems_cache.keys())
        }
        return availability_info
        
    except Exception as e:
        logger.error(f"Error checking AI availability for user {user_id}: {e}")
        return {
            "user_id": user_id,
            "overall_status": "error",
            "error": str(e),
            "recommendations": ["Check service logs for detailed error information"]
        }


@app.post("/users/{user_id}/fix-ai-availability", tags=["RAG Troubleshooting"])
async def fix_ai_availability(user_id: int, user_id_from_key: str = Depends(verify_api_key)):
    """Attempt to automatically fix AI availability issues."""
    try:
        if not RAG_MODULES_AVAILABLE:
            return {
                "status": "cannot_fix",
                "reason": "RAG modules not available - requires code/environment fix"
            }
        
        if not os.getenv("GOOGLE_API_KEY"):
            return {
                "status": "cannot_fix", 
                "reason": "Google API key not configured"
            }
        
        if not check_vector_db_exists(user_id) or get_document_count(user_id) == 0:
            logger.info(f"Attempting to fix AI availability for user {user_id}")
            
            if user_id in rag_systems_cache:
                del rag_systems_cache[user_id]
            
            config = get_pipeline_config(user_id)
            paths = get_user_paths(user_id)
            os.makedirs(os.path.dirname(paths["vector_db_path"]), exist_ok=True)
            
            pipeline = DiaryIndexingPipeline(**config)
            results = pipeline.run_full_pipeline(clear_existing=True)
            
            if results.get('status') == 'completed_successfully':
                doc_count = get_document_count(user_id)
                return {
                    "status": "fixed",
                    "action_taken": "Created/rebuilt vector database",
                    "documents_processed": results.get('documents_loaded', 0),
                    "chunks_created": results.get('chunks_created', 0),
                    "final_document_count": doc_count,
                    "ai_status": "ready" if doc_count > 0 else "empty"
                }
            else:
                return {
                    "status": "fix_failed",
                    "reason": "Failed to create vector database",
                    "error": format_error_message(results.get('errors', 'Unknown error'))
                }
        else:
            return {
                "status": "already_available",
                "message": "AI is already available for this user",
                "document_count": get_document_count(user_id)
            }
    except Exception as e:
        logger.error(f"Error fixing AI availability for user {user_id}: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/users/{user_id}/status", response_model=UserStatusResponse, tags=["RAG Management"])
async def get_user_status(user_id: int, user_id_from_key: str = Depends(verify_api_key)):
    """Get RAG system status for a user."""
    try:
        paths = get_user_paths(user_id)
        if not check_vector_db_exists(user_id):
            return UserStatusResponse(
                user_id=user_id,
                status="not_indexed",
                document_count=0,
                vector_db_path=paths["vector_db_path"]
            )
        
        doc_count = get_document_count(user_id)
        return UserStatusResponse(
            user_id=user_id,
            status="ready" if doc_count > 0 else "empty",
            document_count=doc_count,
            vector_db_path=paths["vector_db_path"],
            last_updated=datetime.now().isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting status for user {user_id}: {e}")
        return UserStatusResponse(
            user_id=user_id,
            status="error",
            document_count=0,
            vector_db_path="",
            error=str(e)
        )


@app.post("/users/{user_id}/index", response_model=IndexResponse, tags=["RAG Management"])
async def index_user_data(
    user_id: int, 
    request: IndexRequest, 
    background_tasks: BackgroundTasks,
    user_id_from_key: str = Depends(verify_api_key)
):
    """Index diary entries for a user."""
    # Enforce Rate limiting and Cost checks
    rate_limiter_user.check(user_id_from_key)
    cost_guard.check_budget(user_id_from_key)
    
    start_time = datetime.now()
    try:
        paths = get_user_paths(user_id)
        os.makedirs(os.path.dirname(paths["vector_db_path"]), exist_ok=True)
        config = get_pipeline_config(user_id)
        
        logger.info(f"Starting indexing for user {user_id}")
        pipeline = DiaryIndexingPipeline(**config)
        
        if request.start_date and request.end_date:
            results = pipeline.run_full_pipeline(
                start_date=request.start_date,
                end_date=request.end_date,
                clear_existing=request.clear_existing
            )
        else:
            results = pipeline.run_full_pipeline(clear_existing=request.clear_existing)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        if results.get('status') == 'completed_successfully':
            if user_id in rag_systems_cache:
                del rag_systems_cache[user_id]
            
            return IndexResponse(
                user_id=user_id,
                status="success",
                documents_processed=results.get('documents_loaded', 0),
                chunks_created=results.get('chunks_created', 0),
                vector_db_path=paths["vector_db_path"],
                processing_time=processing_time
            )
        else:
            return IndexResponse(
                user_id=user_id,
                status="failed",
                documents_processed=0,
                chunks_created=0,
                vector_db_path=paths["vector_db_path"],
                processing_time=processing_time,
                error=format_error_message(results.get('errors', 'Unknown error'))
            )
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"Indexing error for user {user_id}: {e}")
        return IndexResponse(
            user_id=user_id,
            status="error",
            documents_processed=0,
            chunks_created=0,
            vector_db_path="",
            processing_time=processing_time,
            error=str(e)
        )


@app.post("/users/{user_id}/incremental-index", tags=["RAG Management"])
async def incremental_index(
    user_id: int, 
    start_date: str = None,
    user_id_from_key: str = Depends(verify_api_key)
):
    """Run incremental indexing for user."""
    rate_limiter_user.check(user_id_from_key)
    cost_guard.check_budget(user_id_from_key)
    
    try:
        config = get_pipeline_config(user_id)
        pipeline = DiaryIndexingPipeline(**config)
        
        if start_date:
            results = pipeline.incremental_update(start_date)
        else:
            # Default to last 7 days
            default_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            results = pipeline.incremental_update(default_start)
        
        if results.get('status') == 'success':
            if user_id in rag_systems_cache:
                del rag_systems_cache[user_id]
            
            return {
                "user_id": user_id,
                "status": "success",
                "documents_added": results.get('documents_added', 0),
                "start_date": start_date or default_start
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Incremental indexing failed: {results.get('error', 'Unknown error')}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Incremental indexing error for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}/query", response_model=QueryResponse, tags=["RAG Query"])
async def query_user_rag(
    user_id: int,
    query: str = Query(...),
    fast_mode: bool = Query(False),
    chat_history: str = Query("[]"),
    user_id_from_key: str = Depends(verify_api_key)
):
    """Query RAG system for a user. Validates rate limit and budget."""
    rate_limiter_user.check(user_id_from_key)
    cost_guard.check_budget(user_id_from_key)
    
    start_time = datetime.now()
    try:
        rag_system = get_or_create_rag_system(user_id)
        chat_history_list = json.loads(chat_history)
        
        if fast_mode:
            response = rag_system.generate_fast_response(query=query)
        else:
            response = rag_system.generate_contextual_response(
                query=query,
                chat_history=chat_history_list
            )
            
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Record usage
        input_tokens = len(query.split()) * 2
        output_tokens = len(response.split()) * 2
        cost_guard.record_usage(user_id_from_key, input_tokens, output_tokens)
        
        return QueryResponse(
            user_id=user_id,
            response=response,
            processing_time=processing_time,
            documents_used=5,
            fast_mode=fast_mode
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query error for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.post("/users/{user_id}/auto-index-new-entry", tags=["RAG Management"])
async def auto_index_new_entry(user_id: int, user_id_from_key: str = Depends(verify_api_key)):
    """Auto-index after saving new diary entry. Creates initial index if not exists."""
    rate_limiter_user.check(user_id_from_key)
    cost_guard.check_budget(user_id_from_key)
    
    try:
        if not RAG_MODULES_AVAILABLE:
            return {"status": "skipped", "reason": "RAG modules not available"}
        
        if not check_vector_db_exists(user_id):
            logger.info(f"Creating initial vector database for user {user_id}")
            config = get_pipeline_config(user_id)
            paths = get_user_paths(user_id)
            os.makedirs(os.path.dirname(paths["vector_db_path"]), exist_ok=True)
            
            pipeline = DiaryIndexingPipeline(**config)
            results = pipeline.run_full_pipeline(clear_existing=True)
            
            if results.get('status') == 'completed_successfully':
                if user_id in rag_systems_cache:
                    del rag_systems_cache[user_id]
                
                return {
                    "status": "initial_index_created",
                    "message": f"Created initial vector database for user {user_id}",
                    "documents_processed": results.get('documents_loaded', 0),
                    "chunks_created": results.get('chunks_created', 0)
                }
            else:
                return {
                    "status": "failed",
                    "error": format_error_message(results.get('errors', 'Unknown error'))
                }
        else:
            config = get_pipeline_config(user_id)
            pipeline = DiaryIndexingPipeline(**config)
            
            default_start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            results = pipeline.incremental_update(default_start)
            
            if results.get('status') == 'success':
                if user_id in rag_systems_cache:
                    del rag_systems_cache[user_id]
                
                return {
                    "status": "incremental_update_success",
                    "message": f"Updated vector database for user {user_id}",
                    "documents_added": results.get('documents_added', 0)
                }
            else:
                logger.warning(f"Incremental update failed for user {user_id}, full rebuild")
                results = pipeline.run_full_pipeline(clear_existing=True)
                
                if results.get('status') == 'completed_successfully':
                    if user_id in rag_systems_cache:
                        del rag_systems_cache[user_id]
                    
                    return {
                        "status": "full_rebuild_success",
                        "message": f"Rebuilt vector database for user {user_id}",
                        "documents_processed": results.get('documents_loaded', 0)
                    }
                else:
                    return {
                        "status": "failed",
                        "error": f"Both incremental and full rebuild failed: {format_error_message(results.get('errors', 'Unknown error'))}"
                    }
    except Exception as e:
        logger.error(f"Auto-index error for user {user_id}: {e}")
        return {"status": "error", "error": str(e)}


@app.delete("/users/{user_id}/cache", tags=["RAG Management"])
async def clear_user_cache(user_id: int, user_id_from_key: str = Depends(verify_api_key)):
    """Clear RAG system cache for a user."""
    if user_id in rag_systems_cache:
        del rag_systems_cache[user_id]
        logger.info(f"Cleared cache for user {user_id}")
        return {"message": f"Cache cleared for user {user_id}"}
    return {"message": f"No cache found for user {user_id}"}


@app.delete("/users/{user_id}/vector-db", tags=["RAG Management"])
async def delete_user_vector_db(user_id: int, user_id_from_key: str = Depends(verify_api_key)):
    """Delete vector database for a user."""
    try:
        paths = get_user_paths(user_id)
        if user_id in rag_systems_cache:
            del rag_systems_cache[user_id]
        
        if os.path.exists(paths["vector_db_path"]):
            import shutil
            shutil.rmtree(paths["vector_db_path"])
            logger.info(f"Deleted vector database for user {user_id}")
            return {"message": f"Vector database deleted for user {user_id}"}
        return {"message": f"No vector database found for user {user_id}"}
    except Exception as e:
        logger.error(f"Error deleting vector database for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", tags=["Ops"])
async def get_service_stats(user_id_from_key: str = Depends(verify_api_key)):
    """Get service statistics."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vector_db_base = os.path.join(base_dir, "VectorDB")
        
        existing_dbs = []
        if os.path.exists(vector_db_base):
            for item in os.listdir(vector_db_base):
                if item.startswith("user_") and item.endswith("_vector_db"):
                    user_id = int(item.replace("user_", "").replace("_vector_db", ""))
                    doc_count = get_document_count(user_id)
                    existing_dbs.append({
                        "user_id": user_id,
                        "path": os.path.join(vector_db_base, item),
                        "document_count": doc_count
                    })
        
        return {
            "cached_users": list(rag_systems_cache.keys()),
            "total_cached_systems": len(rag_systems_cache),
            "existing_vector_databases": existing_dbs,
            "vector_db_base_path": vector_db_base,
            "service_status": "running"
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    # Make sure VectorDB folder exists
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vector_db_dir = os.path.join(base_dir, "VectorDB")
    os.makedirs(vector_db_dir, exist_ok=True)
    
    print(f"Starting Production RAG Service...")
    print(f"Vector DB base path: {vector_db_dir}")
    print(f"Google API Key configured: {bool(os.getenv('GOOGLE_API_KEY'))}")
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
