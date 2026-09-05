"""Organization-scoped persistence for durable payroll imports."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session, selectinload

from app.models.payroll_import import (
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
)


class PayrollImportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: PayrollImport, document: PayrollImportDocument) -> None:
        self._session.add_all([item, document])
        self._session.flush()

    def find_by_hash(self, organization_id: UUID, sha256: str) -> PayrollImport | None:
        return self._session.execute(
            select(PayrollImport).where(
                PayrollImport.organization_id == organization_id,
                PayrollImport.content_sha256 == sha256,
            )
        ).scalar_one_or_none()

    def get(self, organization_id: UUID, import_id: UUID,
            *, load_documents: bool = False) -> PayrollImport | None:
        query = select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )
        if load_documents:
            query = query.options(selectinload(PayrollImport.documents))
        return self._session.execute(query).scalar_one_or_none()

    def get_for_update(self, organization_id: UUID,
                       import_id: UUID) -> PayrollImport | None:
        return self._session.execute(
            select(PayrollImport)
            .where(
                PayrollImport.id == import_id,
                PayrollImport.organization_id == organization_id,
            )
            .options(selectinload(PayrollImport.documents))
            .with_for_update()
        ).scalar_one_or_none()

    def list(self, organization_id: UUID) -> list[PayrollImport]:
        return list(self._session.execute(
            select(PayrollImport)
            .where(PayrollImport.organization_id == organization_id)
            .order_by(desc(PayrollImport.created_at), desc(PayrollImport.id))
        ).scalars().all())

    def list_fields(self, organization_id: UUID,
                    import_id: UUID) -> list[PayrollImportField]:
        return list(self._session.execute(
            select(PayrollImportField)
            .where(
                PayrollImportField.organization_id == organization_id,
                PayrollImportField.payroll_import_id == import_id,
            )
            .order_by(
                PayrollImportField.page_number,
                PayrollImportField.source_field_id,
            )
        ).scalars().all())

    def replace_fields(self, import_id: UUID,
                       fields: list[PayrollImportField]) -> None:
        self._session.execute(delete(PayrollImportField).where(
            PayrollImportField.payroll_import_id == import_id
        ))
        self._session.add_all(fields)
        self._session.flush()


__all__ = ["PayrollImportRepository"]
