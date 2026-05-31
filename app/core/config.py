"""Application settings, loaded once from .env at startup."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ─────────────────────────────────────────────
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Adzuna ─────────────────────────────────────────────
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""
    adzuna_country: str = "au"

    # ── Langfuse ───────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # ── Data paths ─────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    chroma_path: Path = Field(default=Path("./data/vector_store"))
    upload_dir: Path = Field(default=Path("./data/uploads"))

    # ── App ────────────────────────────────────────────────
    app_env: str = "dev"
    debug: bool = True
    log_level: str = "INFO"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    def ensure_dirs(self) -> None:
        """Create local data dirs if missing. Called once at startup."""
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()
