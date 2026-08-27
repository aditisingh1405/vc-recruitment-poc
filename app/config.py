from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Placeholder only -- the real URL comes from .env, which is gitignored.
    database_url: str = "postgresql://user:password@localhost:5432/vc_recruitment"

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"

    upload_dir: Path = BASE_DIR / "uploads"
    max_resume_bytes: int = 5 * 1024 * 1024

    @property
    def sqlalchemy_url(self) -> str:
        """A bare postgresql:// URL makes SQLAlchemy look for psycopg2, which we
        don't install -- requirements.txt pins psycopg 3. Name the driver."""
        url = self.database_url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    loaded = Settings()
    loaded.upload_dir.mkdir(parents=True, exist_ok=True)
    return loaded


settings = get_settings()
