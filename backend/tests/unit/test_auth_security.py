"""Focused configuration and login-throttling security tests."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services.auth.login_throttle import LoginThrottle


def test_login_throttle_has_temporary_cooldown() -> None:
    settings = get_settings().model_copy(
        update={
            "login_rate_limit_attempts": 2,
            "login_rate_limit_window_seconds": 60,
            "login_rate_limit_cooldown_seconds": 120,
        }
    )
    throttle = LoginThrottle(settings)
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)

    throttle.record_failure("127.0.0.1", "USER@example.com", now)
    assert not throttle.is_blocked("127.0.0.1", "user@example.com", now)
    throttle.record_failure("127.0.0.1", "user@example.com", now)
    assert throttle.is_blocked("127.0.0.1", "user@example.com", now)
    assert not throttle.is_blocked(
        "127.0.0.1", "user@example.com", now + timedelta(seconds=121)
    )


def test_success_clears_failed_login_history() -> None:
    throttle = LoginThrottle(get_settings())
    throttle.record_failure("127.0.0.1", "user@example.com")

    throttle.record_success("127.0.0.1", "user@example.com")

    assert not throttle.is_blocked("127.0.0.1", "user@example.com")


def test_production_rejects_non_secure_refresh_cookie() -> None:
    with pytest.raises(ValidationError, match="Secure refresh cookies"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+psycopg://example.invalid/db",
            auth_secret_key="x" * 32,
            auth_cookie_secure=False,
        )


def test_samesite_none_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="SameSite=None"):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://example.invalid/db",
            auth_secret_key="x" * 32,
            auth_cookie_samesite="none",
            auth_cookie_secure=False,
        )
