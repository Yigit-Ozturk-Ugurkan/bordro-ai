"""Organization-scoped persistence boundary for import review and snapshots."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.payroll_import import PayrollImport, PayrollImportMappedField
from app.models.payroll_review import (
    PayrollImportFieldCorrection,
    PayrollImportReview,
    PayrollImportReviewSnapshot,
    PayrollImportReviewSnapshotField,
)


class PayrollReviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_import(self, organization_id: UUID, import_id: UUID) -> PayrollImport | None:
        return self._session.execute(select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )).scalar_one_or_none()

    def get_review(self, organization_id: UUID, import_id: UUID) -> PayrollImportReview | None:
        return self._session.execute(select(PayrollImportReview).where(
            PayrollImportReview.organization_id == organization_id,
            PayrollImportReview.payroll_import_id == import_id,
        )).scalar_one_or_none()

    def get_review_for_update(
        self, organization_id: UUID, import_id: UUID,
    ) -> PayrollImportReview | None:
        return self._session.execute(
            select(PayrollImportReview).where(
                PayrollImportReview.organization_id == organization_id,
                PayrollImportReview.payroll_import_id == import_id,
            ).with_for_update()
        ).scalar_one_or_none()

    def add_review(self, review: PayrollImportReview) -> None:
        self._session.add(review)
        self._session.flush()

    def list_mapped_fields(
        self, organization_id: UUID, import_id: UUID,
    ) -> list[PayrollImportMappedField]:
        return list(self._session.execute(
            select(PayrollImportMappedField)
            .where(
                PayrollImportMappedField.organization_id == organization_id,
                PayrollImportMappedField.payroll_import_id == import_id,
            )
            .options(selectinload(PayrollImportMappedField.source_field))
            .order_by(PayrollImportMappedField.payroll_import_field_id)
        ).scalars().all())

    def get_mapped_field(
        self, organization_id: UUID, import_id: UUID, mapped_field_id: UUID,
    ) -> PayrollImportMappedField | None:
        return self._session.execute(
            select(PayrollImportMappedField)
            .where(
                PayrollImportMappedField.id == mapped_field_id,
                PayrollImportMappedField.organization_id == organization_id,
                PayrollImportMappedField.payroll_import_id == import_id,
            )
            .options(selectinload(PayrollImportMappedField.source_field))
        ).scalar_one_or_none()

    def list_corrections(
        self, organization_id: UUID, review_id: UUID,
    ) -> list[PayrollImportFieldCorrection]:
        return list(self._session.execute(
            select(PayrollImportFieldCorrection).where(
                PayrollImportFieldCorrection.organization_id == organization_id,
                PayrollImportFieldCorrection.review_id == review_id,
            ).order_by(
                PayrollImportFieldCorrection.payroll_import_field_id,
                PayrollImportFieldCorrection.revision,
                PayrollImportFieldCorrection.id,
            )
        ).scalars().all())

    def add_correction(self, correction: PayrollImportFieldCorrection) -> None:
        self._session.add(correction)
        self._session.flush()

    def next_correction_revision(self, review_id: UUID, source_field_id: UUID) -> int:
        current = self._session.scalar(select(func.max(PayrollImportFieldCorrection.revision)).where(
            PayrollImportFieldCorrection.review_id == review_id,
            PayrollImportFieldCorrection.payroll_import_field_id == source_field_id,
        ))
        return (current or 0) + 1

    def add_snapshot(
        self, snapshot: PayrollImportReviewSnapshot,
        fields: list[PayrollImportReviewSnapshotField],
    ) -> None:
        self._session.add(snapshot)
        self._session.flush()
        self._session.add_all(fields)
        self._session.flush()

    def next_snapshot_version(self, review_id: UUID) -> int:
        current = self._session.scalar(select(func.max(PayrollImportReviewSnapshot.snapshot_version)).where(
            PayrollImportReviewSnapshot.review_id == review_id,
        ))
        return (current or 0) + 1

    def latest_snapshot(
        self, organization_id: UUID, review_id: UUID,
    ) -> PayrollImportReviewSnapshot | None:
        return self._session.execute(
            select(PayrollImportReviewSnapshot)
            .where(
                PayrollImportReviewSnapshot.organization_id == organization_id,
                PayrollImportReviewSnapshot.review_id == review_id,
            )
            .options(selectinload(PayrollImportReviewSnapshot.fields))
            .order_by(PayrollImportReviewSnapshot.snapshot_version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def list_snapshots(
        self, organization_id: UUID, import_id: UUID,
    ) -> list[PayrollImportReviewSnapshot]:
        return list(self._session.execute(
            select(PayrollImportReviewSnapshot)
            .where(
                PayrollImportReviewSnapshot.organization_id == organization_id,
                PayrollImportReviewSnapshot.payroll_import_id == import_id,
            )
            .order_by(PayrollImportReviewSnapshot.snapshot_version)
        ).scalars().all())

    def get_review_snapshot(
        self, organization_id: UUID, import_id: UUID, snapshot_id: UUID,
    ) -> PayrollImportReviewSnapshot | None:
        return self._session.execute(
            select(PayrollImportReviewSnapshot)
            .where(
                PayrollImportReviewSnapshot.id == snapshot_id,
                PayrollImportReviewSnapshot.organization_id == organization_id,
                PayrollImportReviewSnapshot.payroll_import_id == import_id,
            )
            .options(selectinload(PayrollImportReviewSnapshot.fields))
        ).scalar_one_or_none()

    def list_review_snapshot_fields(
        self, organization_id: UUID, snapshot_id: UUID,
    ) -> list[PayrollImportReviewSnapshotField]:
        return list(self._session.execute(
            select(PayrollImportReviewSnapshotField)
            .where(
                PayrollImportReviewSnapshotField.organization_id == organization_id,
                PayrollImportReviewSnapshotField.snapshot_id == snapshot_id,
            )
            .order_by(PayrollImportReviewSnapshotField.source_import_field_id)
        ).scalars().all())


__all__ = ["PayrollReviewRepository"]
