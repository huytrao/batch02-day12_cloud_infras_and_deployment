# Day 12 Lab - Mission Answers

> **Student:** Trảo An Huy | **ID:** 2A202600819 | **Date:** 2026-06-12

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (5+ issues in basic app.py)

1. **Hardcoded API key** — `api_key = "sk-abc123..."` directly in source code. If committed to Git, anyone with repo access can steal it.
2. **Hardcoded port** — `app.run(port=8000)`. Cannot change without modifying code; breaks in environments where 8000 is taken.
3. **Debug mode always on** — `debug=True` in production exposes stack traces and the interactive debugger to attackers.
4. **No health check endpoint** — Cloud platforms need `/health` to know when to restart the container. Without it, dead containers stay alive.
5. **No graceful shutdown** — Process kills instantly on SIGTERM, dropping in-flight requests and potentially corrupting data.
6. **`print()` instead of structured logging** — Print statements can't be parsed, searched, or aggregated by log systems (Cloudwatch, Datadog, etc.).
7. **State in memory** — In-process dictionaries prevent horizontal scaling: each instance has a different copy of state.

### Exercise 1.3: Comparison table

| Feature | Develop (Basic) | Production (Advanced) | Why Important? |
|---------|-----------------|----------------------|----------------|
| Config | Hardcoded values | Environment variables (`.env`) | Security — secrets not in source code; flexibility — same code works in dev/staging/prod |
| Health check | ❌ Missing | ✅ `/health` returns 200 | Platforms restart dead containers; load balancers route around unhealthy instances |
| Logging | `print()` statements | Structured JSON logs | JSON logs can be parsed, filtered, and aggregated by monitoring tools |
| Shutdown | Abrupt (kill process) | Graceful (SIGTERM handler) | Ensures in-flight requests complete; prevents data corruption |
| Auth | ❌ None | ✅ API key / JWT | Without auth, anyone can call the API and run up OpenAI bills |
| Rate Limiting | ❌ None | ✅ 10 req/min per user | Prevents abuse and runaway cost from single user |
| State storage | In-memory dict | Redis | Survives restarts, shared across all instances → enables horizontal scaling |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

1. **Base image:** `python:3.11-slim` — Slim variant of the official Python 3.11 image. "Slim" excludes unnecessary packages, reducing image size by ~60%.
2. **Working directory:** `/app` — The directory inside the container where application code lives.
3. **Why `COPY requirements.txt` first?** — Docker caches each layer. If we copy requirements before the full source, the `pip install` layer is only rebuilt when `requirements.txt` changes, not on every code change. This makes builds much faster.
4. **CMD vs ENTRYPOINT:**
   - `ENTRYPOINT` is the fixed executable that always runs (e.g., `python`). It cannot be overridden at `docker run`.
   - `CMD` provides default arguments and **can** be overridden at `docker run`. Using both: `ENTRYPOINT ["python"] CMD ["app.py"]` means `docker run img other.py` overrides the script.

### Exercise 2.3: Image size comparison

| Build | Size | Notes |
|-------|------|-------|
| Develop (basic Dockerfile) | ~900 MB – 1.2 GB | Full Python image, all build tools included |
| Production (multi-stage) | ~150 – 200 MB | Only runtime dependencies copied; builder stage discarded |
| **Difference** | **~85%** smaller | Build tools (gcc, etc.) never reach the final image |

**Why smaller?** Multi-stage builds allow using a "builder" stage with gcc and build tools to compile packages, then only copying the compiled Python packages (`.local/`) into a clean `python:3.11-slim` runtime image. All build tooling is discarded.

### Exercise 2.4: Architecture diagram

```
Client
  │ HTTP :80
  ▼
Nginx (port 80)   ← Load balancer / reverse proxy
  │ round-robin
  ├──────┬──────┐
  ▼      ▼      ▼
Agent  Agent  Agent   ← FastAPI on :8000 (stateless)
  └──────┴──────┘
         │
         ▼
       Redis :6379   ← Shared state (sessions, rate limits, budgets)
```

Services communicate on a Docker internal network. Nginx → Agent via service name `agent:8000`. Agent → Redis via `redis:6379`.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- **URL:** https://day12-ai-agent.onrender.com
- **Platform:** Render.com (Do giới hạn tài khoản free của Railway, dự án đã được deploy qua Render Blueprint thành công)
- **Steps completed:**
  1. Cấu hình dịch vụ Redis free và Web service sử dụng Dockerfile trong file `render.yaml`.
  2. Commit và push code lên GitHub repository.
  3. Đăng nhập Render.com qua tài khoản GitHub, kết nối repo.
  4. Tạo Blueprint Instance, Render tự động liên kết Redis `connectionString` vào biến môi trường `REDIS_URL` của web service.
  5. Thiết lập thêm `AGENT_API_KEY`, `JWT_SECRET`.
  6. Deploy thành công và nhận public URL.

### Exercise 3.2: render.yaml vs railway.toml comparison

| Aspect | `railway.toml` | `render.yaml` |
|--------|----------------|---------------|
| Builder | `DOCKERFILE` | `docker` |
| Health check | `healthcheckPath` | `healthCheckPath` |
| Start command | `startCommand` | `startCommand` |
| Auto-deploy | Push to repo | Push to repo |
| Key difference | Simpler, single file | Supports multiple services (web + worker) in one blueprint |

---

## Part 4: API Security

### Exercise 4.1: API Key authentication

- API key is checked in `app/auth.py` via `verify_api_key()` function using FastAPI's `Depends()`.
- Without a key → **401 Unauthorized** with `WWW-Authenticate: ApiKey` header.
- To rotate: update `AGENT_API_KEY` environment variable and redeploy. Zero downtime rotation possible by supporting multiple keys in a list.

**Test output:**
```bash
# Without key → 401
curl -X POST http://localhost:8000/ask -d '{"question": "test"}'
{"detail":"Authentication required. Include header: X-API-Key: <your-key>"}

# With key → 200
curl -X POST http://localhost:8000/ask \
  -H "X-API-Key: secret-key-123" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "question": "Hello"}'
{"session_id":"...","answer":"..."}
```

### Exercise 4.2: JWT authentication

JWT flow:
1. `POST /auth/token` with username/password → receive signed JWT
2. Include `Authorization: Bearer <token>` in subsequent requests
3. Server verifies signature using `JWT_SECRET` → extracts username + role
4. Expired tokens (after 60 min) → 401, must re-login

### Exercise 4.3: Rate limiting

- **Algorithm:** Fixed-window counter (simple, effective for most use cases)
- **Limit:** 10 requests per 60-second window per user (configurable via `RATE_LIMIT_PER_MINUTE`)
- **Storage:** Redis — shared across all instances, ensures limit is global not per-instance
- **Admin bypass:** `rate_limiter_admin` has a limit of 100 req/min
- **Response when limit hit:** `429 Too Many Requests` with `Retry-After` header

### Exercise 4.4: Cost guard implementation

```python
# Implementation in app/cost_guard.py
def check_budget(self, user_id: str) -> None:
    month_key = time.strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    
    current = float(r.get(key) or 0)
    if current >= self.monthly_budget_usd:  # Default $10
        raise HTTPException(status_code=402, detail="Monthly budget exceeded")

def record_usage(self, user_id: str, input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens / 1000 * 0.00015 + output_tokens / 1000 * 0.0006)
    key = f"budget:{user_id}:{time.strftime('%Y-%m')}"
    r.incrbyfloat(key, cost)
    r.expire(key, 32 * 24 * 3600)  # Auto-reset: expires after 32 days
    return float(r.get(key))
```

**Approach:** Track cumulative cost in Redis with a monthly key that auto-expires after 32 days (ensuring monthly reset). Check BEFORE request, record AFTER successful LLM call.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health and readiness checks

```python
@app.get("/health")
def health():
    """Liveness probe — container still alive?"""
    return {"status": "ok", "instance_id": INSTANCE_ID, "uptime_seconds": ...}

@app.get("/ready")
def ready():
    """Readiness probe — ready to serve traffic?"""
    try:
        _redis.ping()  # Check Redis connection
    except Exception:
        raise HTTPException(503, "Redis not available")
    return {"ready": True}
```

- `/health` → Always 200 if process is running (liveness)
- `/ready` → 200 only if Redis is reachable (readiness). Returns 503 if not → load balancer stops sending traffic

### Exercise 5.2: Graceful shutdown

```python
def shutdown_handler(signum, frame):
    """Handle SIGTERM from container orchestrator."""
    global _shutting_down
    _shutting_down = True
    logger.info("Graceful shutdown initiated...")
    time.sleep(2)  # Let in-flight requests complete
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
```

The middleware also returns 503 during shutdown, preventing new requests from being accepted.

### Exercise 5.3: Stateless design

**Anti-pattern (stateful):**
```python
# ❌ Each instance has its own copy — breaks with multiple instances
conversation_history = {}

@app.post("/ask")
def ask(user_id: str, question: str):
    history = conversation_history.get(user_id, [])
```

**Correct (stateless):**
```python
# ✅ State in Redis — shared by all instances
def load_session(session_id: str) -> dict:
    raw = _redis.get(f"session:{session_id}")
    return json.loads(raw) if raw else {}

@app.post("/ask")
def ask(body: AskRequest):
    history = load_session(body.session_id)
```

**Why critical:** With 3 agent instances behind a load balancer, consecutive requests from the same user may hit different instances. If state is in memory, instance 2 doesn't know about conversations handled by instance 1. Redis solves this — all instances read/write the same shared store.

### Exercise 5.4: Load balancing

```bash
docker compose up --scale agent=3
```

- 3 agent instances start on the Docker network
- Nginx round-robins requests across `agent:8000` (Docker handles DNS resolution to multiple containers)
- If one instance dies: Docker Compose restarts it; Nginx routes to healthy ones via health check

### Exercise 5.5: Stateless test

With 3 instances running:
1. `POST /ask` with `session_id=abc` → handled by Agent1, history saved to Redis
2. Kill Agent1: `docker compose kill agent` (kills one instance)
3. `POST /ask` with `session_id=abc` → handled by Agent2 or Agent3
4. ✅ Conversation history still intact — loaded from Redis, not instance memory
