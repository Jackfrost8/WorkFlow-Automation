from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application configuration settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Core Application Settings
    APP_NAME: str = Field(default="AICTE Workflow Automation Platform")
    APP_ENV: str = Field(default="development")
    DEBUG: bool = Field(default=True)
    API_V1_PREFIX: str = Field(default="/api/v1")

    # Server Settings
    HOST: str = Field(default="127.0.0.1")
    PORT: int = Field(default=8000)

    # Security & JWT
    SECRET_KEY: str = Field(
        default="aicte-dev-secret-key-phase1-validation-2026",
        min_length=16,
    )
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=480)

    # Database
    DATABASE_URL: str = Field(default="sqlite:///./backend/aicte_workflow.db")

    # Storage
    UPLOAD_DIR: Path = Field(default=Path("./uploads"))
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=10 * 1024 * 1024)  # 10 MB

    # Time Simulation
    ENABLE_TIME_SIMULATION: bool = Field(default=True)

    # Notification & Mock SMTP
    SMTP_ENABLED: bool = Field(default=False)
    SMTP_HOST: str = Field(default="localhost")
    SMTP_PORT: int = Field(default=1025)
    SMTP_USER: Optional[str] = Field(default=None)
    SMTP_PASSWORD: Optional[str] = Field(default=None)
    SMTP_FROM_EMAIL: str = Field(default="no-reply@aicte.gov.in")

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not (v.startswith("sqlite:///") or v.startswith("postgresql://") or v.startswith("postgresql+psycopg2://")):
            raise ValueError(
                "DATABASE_URL must be a valid SQLite or PostgreSQL connection string."
            )
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache()
def get_settings() -> Settings:
    """Return cached instance of application settings."""
    return Settings()
