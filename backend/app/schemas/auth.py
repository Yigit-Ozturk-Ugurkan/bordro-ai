"""Public authentication schemas. Credential hashes never cross this boundary."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import UserRoleType


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class CurrentUserResponse(BaseModel):
    id: UUID
    organization_id: UUID
    email: str
    roles: list[UserRoleType]
    employee_id: UUID | None
