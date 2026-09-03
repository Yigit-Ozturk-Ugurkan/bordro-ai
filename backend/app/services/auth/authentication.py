"""Password verification, token handling, and current-user resolution."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models.enums import UserRoleType
from app.models.user import User


class AuthenticationError(Exception):
    """An intentionally detail-free authentication failure."""


@dataclass(frozen=True)
class TokenClaims:
    subject: UUID
    organization_id: UUID
    token_type: str


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    organization_id: UUID
    roles: frozenset[UserRoleType]
    employee_id: UUID | None
    employee_organization_id: UUID | None = None
    email: str = ""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int


class AuthenticationService:
    """Centralizes all authentication-sensitive operations."""

    _password_hash = PasswordHash.recommended()
    _dummy_hash = _password_hash.hash("not-a-real-account-password")

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @classmethod
    def hash_password(cls, password: str) -> str:
        return cls._password_hash.hash(password)

    @classmethod
    def verify_password(cls, plain_password: str, password_hash: str) -> bool:
        try:
            return cls._password_hash.verify(plain_password, password_hash)
        except Exception:
            # Malformed/unsupported stored hashes are authentication failures,
            # never exception details exposed through the API.
            return False

    def authenticate_user(
        self, session: Session, email: str, password: str
    ) -> AuthenticatedUser | None:
        normalized_email = email.strip().casefold()
        users = list(
            session.execute(
                self._user_query().where(func.lower(User.email) == normalized_email)
            )
            .scalars()
            .all()
        )

        # Email is tenant-unique, not globally unique. Refuse ambiguity instead
        # of guessing a tenant; use dummy verification to reduce timing leaks.
        if len(users) != 1:
            self.verify_password(password, self._dummy_hash)
            return None

        user = users[0]
        if not self.verify_password(password, user.password_hash):
            return None
        if not user.is_active or not user.organization.is_active:
            return None
        return self._to_authenticated_user(user)

    def load_current_user(
        self, session: Session, claims: TokenClaims
    ) -> AuthenticatedUser | None:
        user = session.execute(
            self._user_query().where(User.id == claims.subject)
        ).scalar_one_or_none()
        if user is None or not user.is_active or not user.organization.is_active:
            return None
        if user.organization_id != claims.organization_id:
            return None
        return self._to_authenticated_user(user)

    def create_access_token(
        self,
        user: AuthenticatedUser,
        expires_delta: timedelta | None = None,
    ) -> str:
        lifetime = expires_delta or timedelta(
            minutes=self._settings.access_token_expire_minutes
        )
        return self._create_token(user, "access", lifetime)

    def create_refresh_token(
        self,
        user: AuthenticatedUser,
        expires_delta: timedelta | None = None,
    ) -> str:
        lifetime = expires_delta or timedelta(
            days=self._settings.refresh_token_expire_days
        )
        return self._create_token(user, "refresh", lifetime)

    def create_token_pair(self, user: AuthenticatedUser) -> TokenPair:
        return TokenPair(
            access_token=self.create_access_token(user),
            refresh_token=self.create_refresh_token(user),
            access_expires_in=self._settings.access_token_expire_minutes * 60,
        )

    def decode_token(self, token: str, expected_type: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._settings.auth_secret_key.get_secret_value(),
                algorithms=[self._settings.auth_algorithm],
                options={"require": ["sub", "org", "type", "iat", "exp", "jti"]},
            )
            if payload["type"] != expected_type:
                raise AuthenticationError
            return TokenClaims(
                subject=UUID(payload["sub"]),
                organization_id=UUID(payload["org"]),
                token_type=payload["type"],
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError from exc

    def _create_token(
        self, user: AuthenticatedUser, token_type: str, lifetime: timedelta
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.id),
            "org": str(user.organization_id),
            "type": token_type,
            "iat": now,
            "exp": now + lifetime,
            "jti": str(uuid4()),
        }
        return jwt.encode(
            payload,
            self._settings.auth_secret_key.get_secret_value(),
            algorithm=self._settings.auth_algorithm,
        )

    @staticmethod
    def _user_query():
        return select(User).options(
            selectinload(User.roles),
            selectinload(User.employee),
            selectinload(User.organization),
        )

    @staticmethod
    def _to_authenticated_user(user: User) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            roles=frozenset(role.role for role in user.roles),
            employee_id=user.employee.id if user.employee is not None else None,
            employee_organization_id=(
                user.employee.organization_id if user.employee is not None else None
            ),
        )
