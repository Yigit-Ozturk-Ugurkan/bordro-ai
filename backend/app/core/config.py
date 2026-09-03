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
    demo_auth_password: SecretStr | None = Field(default=None, min_length=12)

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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
