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
    groq_model: str = "openai/gpt-oss-120b"

    upload_dir: Path = BASE_DIR / "uploads"
    max_resume_bytes: int = 5 * 1024 * 1024

    # Google Drive resume browsing. Read-only and stateless: files are parsed
    # in memory, never saved to uploads/ and never written to the database.
    drive_root_folder_id: str = ""
    drive_service_account_file: str = ""
    drive_cache_ttl_seconds: int = 900
    drive_max_workers: int = 6

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

    @property
    def drive_enabled(self) -> bool:
        """Both halves are required: an ID with no key, or a key with no ID,
        is a half-configured feature and is treated as off."""
        return bool(
            self.drive_root_folder_id.strip()
            and self.drive_service_account_file.strip()
        )


@lru_cache
def get_settings() -> Settings:
    loaded = Settings()
    loaded.upload_dir.mkdir(parents=True, exist_ok=True)
    return loaded


settings = get_settings()
