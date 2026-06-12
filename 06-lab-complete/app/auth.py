"""
Authentication module — API Key + JWT.

Two auth methods:
1. X-API-Key header  (simple, used in /ask)
2. JWT Bearer token  (advanced, via /auth/token)
"""
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Demo users — in production, store in database
DEMO_USERS = {
    "student": {"password": "demo123", "role": "user", "daily_limit": 50},
    "teacher": {"password": "teach456", "role": "admin", "daily_limit": 1000},
}

_bearer_scheme = HTTPBearer(auto_error=False)


# ─── API Key authentication (simple) ───────────────────────────────────────

def verify_api_key(x_api_key: str = Header(None)) -> str:
    """
    Verify X-API-Key header.
    Returns user_id if valid, raises 401 if missing/invalid.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Include header: X-API-Key: <your-key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if x_api_key != settings.AGENT_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    # Return a deterministic user_id derived from the key
    return f"user_{x_api_key[:8]}"


# ─── JWT authentication (advanced) ─────────────────────────────────────────

def create_token(username: str, role: str) -> str:
    """Create signed JWT token."""
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> dict:
    """Verify JWT Bearer token. Returns user dict."""
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Include: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials, settings.JWT_SECRET, algorithms=[ALGORITHM]
        )
        return {"username": payload["sub"], "role": payload["role"]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="Invalid token.")


def authenticate_user(username: str, password: str) -> dict:
    """Validate username/password. Returns user dict or raises 401."""
    user = DEMO_USERS.get(username)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": username, "role": user["role"]}
