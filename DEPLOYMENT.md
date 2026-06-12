# Deployment Information

> **Student:** Trảo An Huy | **ID:** 2A202600819

## Public URL

🔗 [https://day12-ai-agent.onrender.com](https://day12-ai-agent.onrender.com)

> **Note:** Dự án đã được deploy lên Render.com sử dụng mô hình Blueprint thông qua file `render.yaml`.

## Platform

**Render.com** — được chọn làm môi trường thay thế cho Railway do chính sách giới hạn tài khoản free của Railway. Render cung cấp gói Free (Web Service + Redis) ổn định và dễ cấu hình qua file `render.yaml`.

## Configuration

### Files
- `render.yaml` — Render Blueprint configuration file
- `Dockerfile` — Multi-stage build, non-root user

### Environment Variables Set on Render

| Variable | Description |
|----------|-------------|
| `PORT` | Server port (Render injects automatically) |
| `AGENT_API_KEY` | Authentication key for `/ask` endpoint (e.g. `secret-key-lab12`) |
| `JWT_SECRET` | JWT signing secret |
| `REDIS_URL` | Redis connection string (tự động lấy từ Key-Value/Redis service) |
| `LOG_LEVEL` | `INFO` |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `MONTHLY_BUDGET_USD` | `10.0` |

## Test Commands

### 1. Health Check (no auth needed)
```bash
curl https://day12-ai-agent.onrender.com/health
# Expected: {"status": "ok", "instance_id": "...", "uptime_seconds": ...}
```

### 2. Readiness Check
```bash
curl https://day12-ai-agent.onrender.com/ready
# Expected: {"ready": true, "instance": "..."}
```

### 3. Without API Key → 401
```bash
curl -X POST https://day12-ai-agent.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 401 Unauthorized
```

### 4. With API Key → 200
```bash
curl -X POST https://day12-ai-agent.onrender.com/ask \
  -H "X-API-Key: YOUR_API_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is Docker?"}'
# Expected: 200 with answer
```

### 5. Rate Limiting → 429 after 10 requests
```bash
for i in $(seq 1 15); do
  curl -X POST https://day12-ai-agent.onrender.com/ask \
    -H "X-API-Key: YOUR_API_KEY_HERE" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"test\", \"question\": \"Request $i\"}"
  echo ""
done
# Expected: 429 Too Many Requests after 10 requests
```

## Deploy Steps

1. Định nghĩa file `render.yaml` ở thư mục gốc của project (đã định cấu hình web service và redis).
2. Commit và push code lên GitHub repo.
3. Đăng nhập vào Render Dashboard, chọn **New** -> **Blueprint**.
4. Chọn repo GitHub `day12_ha-tang-cloud_va_deployment`.
5. Đặt tên cho Blueprint Instance (ví dụ `HuytraoCICD`) và bấm **Apply**.
6. Render sẽ tự động khởi tạo Redis và Web Service, chạy build Dockerfile và deploy lên domain public.

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
