"""Organization-scoped persistence for immutable payroll approval evidence."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.payroll_approval import (
    PayrollImportApproval,
    PayrollImportValidationAcknowledgement,
)
from app.models.payroll_import import PayrollImport
from app.models.payroll_review import PayrollImportReview, PayrollImportReviewSnapshot
from app.models.payroll_validation import (
    PayrollImportValidationResult,
    PayrollImportValidationRun,
)


class PayrollApprovalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_import(self, organization_id: UUID, import_id: UUID):
        return self._session.execute(select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )).scalar_one_or_none()

    def current_snapshot_id(self, organization_id: UUID, import_id: UUID) -> UUID | None:
        return self._session.scalar(select(PayrollImportReview.current_snapshot_id).where(
            PayrollImportReview.organization_id == organization_id,
            PayrollImportReview.payroll_import_id == import_id,
        ))

    def get_snapshot(self, organization_id: UUID, import_id: UUID, snapshot_id: UUID):
        return self._session.execute(select(PayrollImportReviewSnapshot).where(
            PayrollImportReviewSnapshot.id == snapshot_id,
            PayrollImportReviewSnapshot.organization_id == organization_id,
            PayrollImportReviewSnapshot.payroll_import_id == import_id,
        )).scalar_one_or_none()

    def get_run(self, organization_id: UUID, import_id: UUID, run_id: UUID,
                *, for_update: bool = False):
        statement = select(PayrollImportValidationRun).where(
            PayrollImportValidationRun.id == run_id,
            PayrollImportValidationRun.organization_id == organization_id,
            PayrollImportValidationRun.payroll_import_id == import_id,
        ).options(selectinload(PayrollImportValidationRun.results))
        if for_update:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def latest_run_for_snapshot(self, organization_id: UUID, import_id: UUID,
                                snapshot_id: UUID):
        return self._session.execute(
            select(PayrollImportValidationRun).where(
                PayrollImportValidationRun.organization_id == organization_id,
                PayrollImportValidationRun.payroll_import_id == import_id,
                PayrollImportValidationRun.review_snapshot_id == snapshot_id,
            ).options(selectinload(PayrollImportValidationRun.results)).order_by(
                PayrollImportValidationRun.ruleset_version.desc(),
                PayrollImportValidationRun.validation_version.desc(),
                PayrollImportValidationRun.created_at.desc(),
                PayrollImportValidationRun.id.desc(),
            ).limit(1)
        ).scalar_one_or_none()

    def get_result(self, organization_id: UUID, run_id: UUID, result_id: UUID):
        return self._session.execute(select(PayrollImportValidationResult).where(
            PayrollImportValidationResult.id == result_id,
            PayrollImportValidationResult.organization_id == organization_id,
            PayrollImportValidationResult.validation_run_id == run_id,
        )).scalar_one_or_none()

    def decision_for_run(self, organization_id: UUID, run_id: UUID):
        return self._session.execute(select(PayrollImportApproval).where(
            PayrollImportApproval.organization_id == organization_id,
            PayrollImportApproval.validation_run_id == run_id,
        )).scalar_one_or_none()

    def acknowledgement_for_result(self, organization_id: UUID, result_id: UUID):
        return self._session.execute(
            select(PayrollImportValidationAcknowledgement).where(
                PayrollImportValidationAcknowledgement.organization_id == organization_id,
                PayrollImportValidationAcknowledgement.validation_result_id == result_id,
            )
        ).scalar_one_or_none()

    def acknowledgements_for_run(self, organization_id: UUID, run_id: UUID):
        return list(self._session.execute(
            select(PayrollImportValidationAcknowledgement).where(
                PayrollImportValidationAcknowledgement.organization_id == organization_id,
                PayrollImportValidationAcknowledgement.validation_run_id == run_id,
            ).order_by(
                PayrollImportValidationAcknowledgement.validation_result_id,
            )
        ).scalars().all())

    def list_decisions(self, organization_id: UUID, import_id: UUID):
        return list(self._session.execute(select(PayrollImportApproval).where(
            PayrollImportApproval.organization_id == organization_id,
            PayrollImportApproval.payroll_import_id == import_id,
        ).order_by(
            PayrollImportApproval.decided_at,
            PayrollImportApproval.id,
        )).scalars().all())

    def list_acknowledgements(self, organization_id: UUID, import_id: UUID):
        return list(self._session.execute(
            select(PayrollImportValidationAcknowledgement).where(
                PayrollImportValidationAcknowledgement.organization_id == organization_id,
                PayrollImportValidationAcknowledgement.payroll_import_id == import_id,
            ).order_by(
                PayrollImportValidationAcknowledgement.acknowledged_at,
                PayrollImportValidationAcknowledgement.id,
            )
        ).scalars().all())

    def add_acknowledgement(self, row: PayrollImportValidationAcknowledgement) -> None:
        self._session.add(row)
        self._session.flush()

    def add_decision(self, row: PayrollImportApproval) -> None:
        self._session.add(row)
        self._session.flush()


__all__ = ["PayrollApprovalRepository"]
