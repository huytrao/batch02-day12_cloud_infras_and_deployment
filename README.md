# AI Agent - Cloud Deployment Lab

This repository contains the completed Day 12 Cloud Deployment Lab, demonstrating a production-ready, stateless AI Agent with a full security stack.

## Features

- **Stateless Design**: Uses Redis to store chat sessions.
- **Security**: JWT Authentication for user and admin roles.
- **Rate Limiting**: Limits requests per minute (10 for users, 100 for admins).
- **Cost Guard**: Protects against high LLM API bills ($1/day per user limit).
- **Graceful Shutdown**: Properly handles SIGTERM signals.
- **Multi-stage Docker Build**: Optimized image size (< 200MB).
- **Health Checks**: Ready/Health endpoints for load balancers.

## Project Structure

```
your-repo/
├── app/
│   ├── main.py              # Main application
│   ├── config.py            # Configuration
│   ├── auth.py              # Authentication
│   ├── rate_limiter.py      # Rate limiting
│   └── cost_guard.py        # Cost protection
├── utils/
│   └── mock_llm.py          # Mock LLM
├── Dockerfile               # Multi-stage build
├── docker-compose.yml       # Full stack
├── requirements.txt         # Dependencies
├── .env.example             # Environment template
├── .dockerignore            # Docker ignore
├── railway.toml             # Railway config
└── README.md                # Setup instructions
```

## Running Locally

1. Create environment file:
```bash
cp .env.example .env
```

2. Start the stack (Redis + Agent):
```bash
docker compose up --build
```

3. Test Health Check:
```bash
curl http://localhost:8000/health
```

4. Get Authentication Token:
```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "student", "password": "demo123"}'
```

5. Ask a question:
```bash
curl -X POST http://localhost:8000/ask \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello!"}'
```

## Deployment

The application is deployed to Railway and configured using `railway.toml` and Docker.
See `DEPLOYMENT.md` for the live URL and tests.
