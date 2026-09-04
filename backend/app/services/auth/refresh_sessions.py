"""Refresh-session issuance, rotation, revocation, and replay detection."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.refresh_session import RefreshSession
from app.repositories.auth_session_repository import AuthSessionRepository
from app.services.auth.authentication import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationService,
)


class RefreshSessionError(Exception):
    """An intentionally detail-free refresh-session failure."""


class RefreshTokenReuseDetected(RefreshSessionError):
    """A previously rotated refresh credential was presented again."""


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    refresh_expires_at: datetime
    access_expires_in: int


class RefreshSessionService:
    def __init__(
        self,
        settings: Settings | None = None,
        authentication: AuthenticationService | None = None,
        repository: AuthSessionRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._authentication = authentication or AuthenticationService(self._settings)
        self._repository = repository or AuthSessionRepository()

    @staticmethod
    def token_hash(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    def create_session(
        self, session: Session, user: AuthenticatedUser
    ) -> SessionTokens:
        return self._issue(session, user, family_id=uuid4())

    def rotate_session(self, session: Session, token: str) -> SessionTokens:
        try:
            claims = self._authentication.decode_token(token, "refresh")
        except AuthenticationError as exc:
            raise RefreshSessionError from exc

        stored = self._repository.get_by_token_hash_for_update(
            session, self.token_hash(token)
        )
        if stored is None:
            raise RefreshSessionError

        now = datetime.now(timezone.utc)
        if stored.revoked_at is not None:
            if stored.replaced_by_session_id is not None:
                self._revoke_family(session, stored.family_id, now, "REUSE_DETECTED")
                raise RefreshTokenReuseDetected
            raise RefreshSessionError
        if stored.expires_at <= now:
            stored.revoked_at = now
            stored.revocation_reason = "EXPIRED"
            raise RefreshSessionError
        if (
            stored.user_id != claims.subject
            or stored.organization_id != claims.organization_id
        ):
            self._revoke_family(session, stored.family_id, now, "CLAIMS_MISMATCH")
            raise RefreshSessionError

        user = self._authentication.load_current_user(session, claims)
        if user is None:
            self._revoke_family(session, stored.family_id, now, "USER_INVALID")
            raise RefreshSessionError

        replacement = self._issue(session, user, family_id=stored.family_id)
        session.flush()
        replacement_row = self._repository.get_by_token_hash_for_update(
            session, self.token_hash(replacement.refresh_token)
        )
        if replacement_row is None:  # pragma: no cover - flush invariant
            raise RuntimeError("Refresh-session replacement was not persisted")

        stored.last_used_at = now
        stored.revoked_at = now
        stored.replaced_by_session_id = replacement_row.id
        stored.revocation_reason = "ROTATED"
        session.flush()
        return replacement

    def revoke_session(self, session: Session, token: str) -> None:
        stored = self._repository.get_by_token_hash_for_update(
            session, self.token_hash(token)
        )
        if stored is None or stored.revoked_at is not None:
            return
        now = datetime.now(timezone.utc)
        stored.last_used_at = now
        stored.revoked_at = now
        stored.revocation_reason = "LOGOUT"
        session.flush()

    def _issue(
        self, session: Session, user: AuthenticatedUser, family_id: UUID
    ) -> SessionTokens:
        now = datetime.now(timezone.utc)
        refresh_token = self._authentication.create_refresh_token(user)
        claims = self._authentication.decode_token(refresh_token, "refresh")
        self._repository.add(
            session,
            RefreshSession(
                user_id=user.id,
                organization_id=user.organization_id,
                family_id=family_id,
                token_hash=self.token_hash(refresh_token),
                created_at=now,
                expires_at=claims.expires_at,
            ),
        )
        session.flush()
        return SessionTokens(
            access_token=self._authentication.create_access_token(user),
            refresh_token=refresh_token,
            refresh_expires_at=claims.expires_at,
            access_expires_in=self._settings.access_token_expire_minutes * 60,
        )

    def _revoke_family(
        self, session: Session, family_id: UUID, now: datetime, reason: str
    ) -> None:
        for stored in self._repository.get_family_for_update(session, family_id):
            if stored.revoked_at is None:
                stored.revoked_at = now
            stored.revocation_reason = reason
        session.flush()
