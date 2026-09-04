"""Database access for refresh-session lifecycle operations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.refresh_session import RefreshSession


class AuthSessionRepository:
    def add(self, session: Session, refresh_session: RefreshSession) -> None:
        session.add(refresh_session)

    def get_by_token_hash_for_update(
        self, session: Session, token_hash: str
    ) -> RefreshSession | None:
        return session.execute(
            select(RefreshSession)
            .where(RefreshSession.token_hash == token_hash)
            .with_for_update()
        ).scalar_one_or_none()

    def get_family_for_update(
        self, session: Session, family_id: UUID
    ) -> list[RefreshSession]:
        return list(
            session.execute(
                select(RefreshSession)
                .where(RefreshSession.family_id == family_id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
