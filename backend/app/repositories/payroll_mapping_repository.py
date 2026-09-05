"""Tenant-scoped persistence operations for payroll adapter configuration/output."""

from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import PayrollFieldMappingScope
from app.models.payroll_import import (
    PayrollFieldMapping,
    PayrollImport,
    PayrollImportMappedField,
    PayrollImportMappingIssue,
)


class PayrollMappingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_import_for_update(self, organization_id: UUID, import_id: UUID) -> PayrollImport | None:
        return self._session.execute(
            select(PayrollImport)
            .where(PayrollImport.id == import_id, PayrollImport.organization_id == organization_id)
            .options(selectinload(PayrollImport.fields))
            .with_for_update()
        ).scalar_one_or_none()

    def get_import(self, organization_id: UUID, import_id: UUID) -> PayrollImport | None:
        return self._session.execute(select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )).scalar_one_or_none()

    def candidates(self, item: PayrollImport, source_field_id: str,
                   normalized_label: str) -> list[PayrollFieldMapping]:
        possible = self._session.execute(
            select(PayrollFieldMapping).where(
                PayrollFieldMapping.is_active.is_(True),
                or_(
                    PayrollFieldMapping.organization_id.is_(None),
                    PayrollFieldMapping.organization_id == item.organization_id,
                ),
                or_(
                    PayrollFieldMapping.source_field_id == source_field_id,
                    (PayrollFieldMapping.source_field_id.is_(None)
                     & (PayrollFieldMapping.source_label_normalized == normalized_label)),
                ),
            )
        ).scalars().all()
        return [mapping for mapping in possible if self._eligible(item, mapping)]

    @staticmethod
    def _eligible(item: PayrollImport, mapping: PayrollFieldMapping) -> bool:
        if mapping.scope == PayrollFieldMappingScope.SYSTEM:
            return mapping.organization_id is None
        if mapping.scope == PayrollFieldMappingScope.ORGANIZATION:
            return mapping.organization_id == item.organization_id
        return (
            mapping.scope == PayrollFieldMappingScope.TEMPLATE
            and mapping.organization_id == item.organization_id
            and mapping.template_provider == item.reader_provider
            and mapping.template_external_id == item.template_external_id
            and item.template_external_id is not None
        )

    def replace_results(self, organization_id: UUID, import_id: UUID,
                        rows: list[PayrollImportMappedField],
                        issues: list[PayrollImportMappingIssue]) -> None:
        self._session.execute(delete(PayrollImportMappedField).where(
            PayrollImportMappedField.organization_id == organization_id,
            PayrollImportMappedField.payroll_import_id == import_id,
        ))
        self._session.execute(delete(PayrollImportMappingIssue).where(
            PayrollImportMappingIssue.organization_id == organization_id,
            PayrollImportMappingIssue.payroll_import_id == import_id,
        ))
        self._session.add_all([*rows, *issues])
        self._session.flush()

    def list_results(self, organization_id: UUID,
                     import_id: UUID) -> list[PayrollImportMappedField]:
        return list(self._session.execute(
            select(PayrollImportMappedField)
            .where(
                PayrollImportMappedField.organization_id == organization_id,
                PayrollImportMappedField.payroll_import_id == import_id,
            )
            .options(selectinload(PayrollImportMappedField.source_field))
            .order_by(PayrollImportMappedField.created_at, PayrollImportMappedField.id)
        ).scalars().all())

    def list_issues(self, organization_id: UUID,
                    import_id: UUID) -> list[PayrollImportMappingIssue]:
        return list(self._session.execute(
            select(PayrollImportMappingIssue).where(
                PayrollImportMappingIssue.organization_id == organization_id,
                PayrollImportMappingIssue.payroll_import_id == import_id,
            ).order_by(PayrollImportMappingIssue.canonical_key)
        ).scalars().all())


__all__ = ["PayrollMappingRepository"]
