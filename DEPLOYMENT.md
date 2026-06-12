# Deployment Information

> **Student:** Trảo An Huy | **ID:** 2A202600819

## Public URL

🔗 [https://day12-agent.railway.app](https://day12-agent.railway.app)

> **Note:** Deploy lên Railway sau khi push code lên GitHub và kết nối Railway với repo.  
> Update URL thật ở đây sau khi deploy thành công.

## Platform

**Railway** — được chọn vì có $5 free credit, CLI đơn giản, và hỗ trợ Dockerfile.

## Configuration

### Files
- `railway.toml` — Railway deployment config
- `Dockerfile` — Multi-stage build, non-root user

### Environment Variables Set on Railway

| Variable | Description |
|----------|-------------|
| `PORT` | Server port (Railway injects automatically) |
| `AGENT_API_KEY` | Authentication key for `/ask` endpoint |
| `JWT_SECRET` | JWT signing secret |
| `REDIS_URL` | Redis connection (from Railway Redis plugin) |
| `LOG_LEVEL` | `INFO` |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `MONTHLY_BUDGET_USD` | `10.0` |

## Test Commands

### 1. Health Check (no auth needed)
```bash
curl https://day12-agent.railway.app/health
# Expected: {"status": "ok", "instance_id": "...", "uptime_seconds": ...}
```

### 2. Readiness Check
```bash
curl https://day12-agent.railway.app/ready
# Expected: {"ready": true, "instance": "..."}
```

### 3. Without API Key → 401
```bash
curl -X POST https://day12-agent.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 401 Unauthorized
```

### 4. With API Key → 200
```bash
curl -X POST https://day12-agent.railway.app/ask \
  -H "X-API-Key: YOUR_API_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is Docker?"}'
# Expected: 200 with answer
```

### 5. Rate Limiting → 429 after 10 requests
```bash
for i in $(seq 1 15); do
  curl -X POST https://day12-agent.railway.app/ask \
    -H "X-API-Key: YOUR_API_KEY_HERE" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"test\", \"question\": \"Request $i\"}"
  echo ""
done
# Expected: 429 Too Many Requests after 10 requests
```

## Deploy Steps

```bash
# 1. Install Railway CLI
npm i -g @railway/cli

# 2. Login
railway login

# 3. Initialize (in 06-lab-complete directory)
cd 06-lab-complete
railway init

# 4. Add Redis plugin via Railway dashboard (or CLI)
railway add --plugin redis

# 5. Set environment variables
railway variables set AGENT_API_KEY=your-secret-key
railway variables set JWT_SECRET=your-jwt-secret
railway variables set LOG_LEVEL=INFO
railway variables set ENVIRONMENT=production
railway variables set RATE_LIMIT_PER_MINUTE=10
railway variables set MONTHLY_BUDGET_USD=10.0

# 6. Deploy
railway up

# 7. Get public URL
railway domain
```

## Screenshots

> Screenshots will be added after deployment.
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Health check test](screenshots/health.png)
- [API test results](screenshots/test.png)
