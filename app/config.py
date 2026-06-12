"""
Config management — all settings from environment variables.
Follows 12-Factor App principles: all config from environment variables, no secrets in code.
"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "production"
    DEBUG: bool = False

    # App
    APP_NAME: str = "Production AI Agent"
    APP_VERSION: str = "1.0.0"

    # Security — MUST be overridden in production
    AGENT_API_KEY: str = "dev-key-change-me-in-production"
    JWT_SECRET: str = "dev-jwt-secret-change-in-production"

    # Rate & Budget limits
    RATE_LIMIT_PER_MINUTE: int = 10
    MONTHLY_BUDGET_USD: float = 10.0
    DAILY_BUDGET_USD: float = 1.0

    # Storage
    REDIS_URL: str = "redis://localhost:6379/0"

    # Logging
    LOG_LEVEL: str = "INFO"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost"

    # LLM (optional — not required with mock)
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = ".env.local"
        env_file_encoding = "utf-8"


settings = Settings()
