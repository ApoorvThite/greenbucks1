from functools import lru_cache
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables (.env).

    Add new settings here as your app grows. Sensitive values should be provided via env vars.
    """

    # App
    app_name: str = "GreenBucks API"
    environment: str = "development"
    debug: bool = True

    # Database
    # Default to local SQLite for easy development if not provided
    database_url: str | None = "sqlite:///./greenbucks.db"  # e.g., postgresql+psycopg://user:pass@localhost:5432/greenbucks

    # Object storage (S3 compatible)
    s3_endpoint_url: str | None = None
    s3_bucket_name: str | None = None

    # Plaid
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_env: str = "sandbox"  # sandbox | development | production

    # Cerebras
    cerebras_api_key: str | None = None

    # Eco/OCR/Climatiq
    google_vision_api_key: Optional[str] = None
    climatiq_api_key: Optional[str] = None
    use_real_ocr: bool = False
    use_real_climatiq: bool = False
    use_cerebras_parser: bool = False

    # Encryption key for securing secrets at rest (Fernet key)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str | None = None

    # Auth/JWT
    jwt_secret_key: str = "dev-secret-change-me"  # override via ENV in prod
    jwt_algorithm: str = "HS256"
    jwt_access_token_expires_minutes: int = 60 * 24  # 24 hours

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class AppInfo(BaseModel):
    name: str
    environment: str
    version: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
