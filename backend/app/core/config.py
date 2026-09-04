from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Bordro AI"
    app_env: str = "development"
    app_version: str = "0.1.0"
    database_url: str
    auth_secret_key: SecretStr = Field(min_length=32)
    auth_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    auth_refresh_cookie_name: str = Field(
        default="bordro_refresh", min_length=1, max_length=100
    )
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_path: str = Field(default="/api/v1/auth", pattern=r"^/")
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86400)
    login_rate_limit_cooldown_seconds: int = Field(default=900, ge=1, le=86400)
    demo_auth_password: SecretStr | None = Field(default=None, min_length=12)
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def reject_placeholders_in_production(self) -> "Settings":
        """Prevent documented example credentials from reaching production."""
        if self.app_env.casefold() == "production":
            sensitive_values = [self.auth_secret_key.get_secret_value()]
            if self.demo_auth_password is not None:
                sensitive_values.append(self.demo_auth_password.get_secret_value())
            if any("change_me" in value.casefold() for value in sensitive_values):
                raise ValueError(
                    "Authentication placeholders are forbidden in production"
                )
            if not self.auth_cookie_secure:
                raise ValueError("Secure refresh cookies are required in production")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None refresh cookies must also be Secure")
        return self

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Return configured explicit origins; wildcards are not accepted."""
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        return [origin for origin in origins if origin and origin != "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
