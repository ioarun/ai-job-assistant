import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # API Keys (empty by default)
    openai_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""

    # Database
    database_url: str = "sqlite:///./data/app.db"
    faiss_path: str = "./data/vector_store/"

    # App Config
    debug: bool = True
    log_level: str = "INFO"
    app_name: str = "AI Job Application Assistant"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
