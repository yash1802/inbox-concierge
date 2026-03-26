from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_BACKEND_ROOT / ".env"),
            str(_REPO_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""
    session_secret: str = "change-me-in-production-min-32-chars-long!!"
    token_encryption_key: str  # Fernet key, base64 urlsafe 32 bytes

    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    frontend_origin: str = "http://localhost:5173"
    cors_allow_origins: str = ""

    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    environment: str = "development"

    max_parallel_gmail_batches: int = 5
    max_parallel_llm_batches: int = 5
    sync_max_threads: int = 200
    gmail_batch_size: int = 20
    queue_maxsize: int = 30

    @field_validator("database_url")
    @classmethod
    def database_url_default(cls, v: str) -> str:
        v = (v or "").strip()
        if v:
            return v
        return "postgresql+asyncpg://inbox:inbox@127.0.0.1:5432/inbox_concierge"

    @field_validator("session_secret")
    @classmethod
    def session_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("session_secret must be at least 32 characters")
        return v

    def resolved_cors_origins(self) -> list[str]:
        extra = [p.strip() for p in (self.cors_allow_origins or "").split(",") if p.strip()]
        fo = (self.frontend_origin or "").strip()
        seen: set[str] = set()
        out: list[str] = []
        for o in ([fo] if fo else []) + extra:
            if not o or o in seen:
                continue
            seen.add(o)
            out.append(o)
        return out if out else ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
