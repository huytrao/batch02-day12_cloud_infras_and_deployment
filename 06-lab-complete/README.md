# Production AI Agent — Lab 6 Final Project

> **AICB-P1 · VinUniversity 2026** | Day 12 — Cloud Deployment

## 🚀 Quick Start

```bash
# 1. Clone & enter directory
cd 06-lab-complete

# 2. Copy env template
cp .env.example .env.local
# Edit .env.local and set AGENT_API_KEY

# 3. Start the full stack (agent + redis + nginx)
docker compose up --scale agent=3

# 4. Test
curl http://localhost/health
curl -X POST http://localhost/ask \
  -H "X-API-Key: secret-key-123" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "question": "Hello!"}'
```

## 📐 Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ HTTP :80
       ▼
┌─────────────────┐
│  Nginx (LB)     │  ← Load balancer
└──────┬──────────┘
       │ round-robin
       ├─────────┬─────────┐
       ▼         ▼         ▼
   ┌──────┐  ┌──────┐  ┌──────┐
   │Agent1│  │Agent2│  │Agent3│  ← Stateless FastAPI instances
   └───┬──┘  └───┬──┘  └───┬──┘
       └─────────┴─────────┘
                 │
                 ▼
           ┌──────────┐
           │  Redis   │  ← Shared state (sessions, rate limits, costs)
           └──────────┘
```

## 📁 Project Structure

```
06-lab-complete/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI application (all endpoints)
│   ├── config.py        # Settings from environment variables
│   ├── auth.py          # API Key + JWT authentication
│   ├── rate_limiter.py  # 10 req/min per user (Redis-backed)
│   └── cost_guard.py    # $10/month budget guard (Redis-backed)
├── utils/
│   └── mock_llm.py      # Mock LLM (no API key needed)
├── Dockerfile           # Multi-stage build (<500 MB)
├── docker-compose.yml   # Full stack: agent + redis + nginx
├── nginx.conf           # Nginx load balancer config
├── requirements.txt     # Python dependencies
├── .env.example         # Environment template (safe to commit)
├── .env.local           # Actual secrets (gitignored)
├── .dockerignore        # Docker build exclusions
├── railway.toml         # Railway deployment config
└── render.yaml          # Render deployment config
```

## ✅ Features

| Feature | Implementation |
|---------|---------------|
| REST API | FastAPI `/ask`, `/health`, `/ready` |
| Authentication | `X-API-Key` header → 401 without key |
| Rate Limiting | 10 req/min per user → 429 when exceeded |
| Cost Guard | $10/month per user → 402 when exceeded |
| Liveness Check | `GET /health` → 200 always |
| Readiness Check | `GET /ready` → 200 (Redis OK) / 503 (Redis down) |
| Graceful Shutdown | `SIGTERM` handler waits for in-flight requests |
| Stateless Design | Session history in Redis, not in memory |
| Structured Logging | JSON-formatted logs for easy parsing |
| Multi-stage Docker | Builder + Runtime stages, slim base |
| Non-root Container | Runs as `agent` user, not root |
| Load Balancing | Nginx round-robin across agent instances |

## 🔒 API Reference

### Health Check
```bash
curl http://localhost/health
# → {"status": "ok", "instance_id": "...", "uptime_seconds": 42.1}
```

### Readiness Check
```bash
curl http://localhost/ready
# → {"ready": true, "instance": "instance-abc123"}
```

### Ask Agent (requires API key)
```bash
curl -X POST http://localhost/ask \
  -H "X-API-Key: secret-key-123" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "question": "What is Docker?"}'

# → {"session_id": "...", "question": "...", "answer": "...", "usage": {...}}
```

### Without API key → 401
```bash
curl -X POST http://localhost/ask -d '{"question": "test"}'
# → 401 Unauthorized
```

### After 10 requests → 429
```bash
for i in $(seq 1 15); do
  curl -X POST http://localhost/ask \
    -H "X-API-Key: secret-key-123" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"bob\", \"question\": \"Request $i\"}"
done
# → 429 Too Many Requests after 10 requests
```

## 🌐 Deploy to Railway

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login
railway login

# Initialize (in this directory)
railway init

# Set environment variables
railway variables set AGENT_API_KEY=your-secret-key-here
railway variables set JWT_SECRET=your-jwt-secret-here
railway variables set REDIS_URL=redis://...  # Add Redis plugin first

# Deploy
railway up

# Get public URL
railway domain
```

## 🐳 Docker Commands

```bash
# Build image
docker build -t my-agent:latest .

# Check image size (should be <500 MB)
docker images my-agent:latest

# Run single instance
docker run -p 8000:8000 \
  -e AGENT_API_KEY=secret \
  -e REDIS_URL=redis://host:6379 \
  my-agent:latest

# Run full stack with 3 agents
docker compose up --scale agent=3

# View logs
docker compose logs -f agent

# Run production readiness check
python check_production_ready.py
```

## 🧪 Run Tests

```bash
# Production readiness checker (local file checks)
python check_production_ready.py

# Manual API tests
curl http://localhost/health
curl http://localhost/ready

# Auth test
curl -X POST http://localhost/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "test"}'
# Expected: 401

curl -X POST http://localhost/ask \
  -H "X-API-Key: secret-key-123" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 200
```

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_API_KEY` | `dev-key-...` | API key for authentication (**change in production**) |
| `JWT_SECRET` | `dev-jwt-...` | JWT signing secret (**change in production**) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `RATE_LIMIT_PER_MINUTE` | `10` | Max requests per user per minute |
| `MONTHLY_BUDGET_USD` | `10.0` | Monthly budget per user (USD) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `PORT` | `8000` | Server port |
| `ENVIRONMENT` | `production` | `development` enables docs UI |

## 👤 Author

- **Student:** Trảo An Huy
- **Student ID:** 2A202600819
- **Course:** AICB-P1 · VinUniversity 2026
