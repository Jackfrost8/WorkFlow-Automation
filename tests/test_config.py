import pytest
from pydantic import ValidationError
from backend.config import Settings


def test_valid_settings_initialization():
    """Verify Settings initializes with standard defaults."""
    settings = Settings(
        APP_NAME="AICTE Test Instance",
        SECRET_KEY="a-sufficiently-long-secret-key-32-chars",
        DATABASE_URL="sqlite:///./test.db",
    )
    assert settings.APP_NAME == "AICTE Test Instance"
    assert settings.is_sqlite is True


def test_invalid_database_url_raises_validation_error():
    """Verify improper database protocols are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            SECRET_KEY="a-sufficiently-long-secret-key-32-chars",
            DATABASE_URL="mysql://root:pass@localhost/db",
        )
    assert "DATABASE_URL must be a valid SQLite or PostgreSQL" in str(exc_info.value)


def test_short_secret_key_raises_validation_error():
    """Verify overly short secret keys fail validation."""
    with pytest.raises(ValidationError):
        Settings(
            SECRET_KEY="short",
            DATABASE_URL="sqlite:///./test.db",
        )
