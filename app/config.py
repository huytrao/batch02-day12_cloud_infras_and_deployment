import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PORT: int = 8000
    REDIS_URL: str = "redis://redis:6379/0"
    JWT_SECRET: str = "super-secret-change-in-production-please"
    ENVIRONMENT: str = "production"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost"
    
    class Config:
        env_file = ".env"

settings = Settings()
