# ============================================================
# Production Dockerfile — Multi-stage, < 500 MB, non-root
# ============================================================

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim AS runtime

# Non-root user
RUN groupadd -r agent && useradd -r -m -g agent -d /home/agent agent

WORKDIR /app

# Copy packages từ builder
COPY --from=builder /root/.local /home/agent/.local

# Copy application
COPY app/ ./app/
COPY utils/ ./utils/

# Create VectorDB and check permissions
RUN mkdir -p /app/VectorDB && chown -R agent:agent /app

USER agent

ENV PATH=/home/agent/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check (Queries internal FastAPI backend on port 8001)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" \
    || exit 1

CMD ["python", "app/app.py"]
