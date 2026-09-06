"""Organization-scoped persistence for immutable payroll validation runs."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import Employee
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_import import PayrollImport
from app.models.payroll_review import PayrollImportReviewSnapshot
from app.models.payroll_validation import (
    PayrollImportValidationResult,
    PayrollImportValidationRun,
)
from app.models.enums import PayrollValidationRunStatus


class PayrollValidationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_import(self, organization_id: UUID, import_id: UUID):
        return self._session.execute(select(PayrollImport).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )).scalar_one_or_none()

    def get_snapshot(self, organization_id: UUID, import_id: UUID, snapshot_id: UUID):
        return self._session.execute(
            select(PayrollImportReviewSnapshot).where(
                PayrollImportReviewSnapshot.id == snapshot_id,
                PayrollImportReviewSnapshot.organization_id == organization_id,
                PayrollImportReviewSnapshot.payroll_import_id == import_id,
            ).options(selectinload(PayrollImportReviewSnapshot.fields)).with_for_update()
        ).scalar_one_or_none()

    def completed_for_ruleset(self, organization_id: UUID, snapshot_id: UUID,
                              ruleset_version: int):
        return self._session.execute(
            select(PayrollImportValidationRun).where(
                PayrollImportValidationRun.organization_id == organization_id,
                PayrollImportValidationRun.review_snapshot_id == snapshot_id,
                PayrollImportValidationRun.ruleset_version == ruleset_version,
                PayrollImportValidationRun.status == PayrollValidationRunStatus.COMPLETED,
            ).options(selectinload(PayrollImportValidationRun.results))
        ).scalar_one_or_none()

    def next_validation_version(self, snapshot_id: UUID) -> int:
        current = self._session.scalar(select(func.max(
            PayrollImportValidationRun.validation_version,
        )).where(PayrollImportValidationRun.review_snapshot_id == snapshot_id))
        return (current or 0) + 1

    def employee_ids(self, organization_id: UUID, employee_no: str) -> tuple[UUID, ...]:
        return tuple(self._session.scalars(select(Employee.id).where(
            Employee.organization_id == organization_id,
            Employee.employee_no == employee_no,
        )).all())

    def current_payroll_id(self, organization_id: UUID, employee_id: UUID,
                           year: int, month: int) -> UUID | None:
        return self._session.scalar(
            select(Payroll.id).join(
                PayrollVersion, PayrollVersion.payroll_id == Payroll.id,
            ).where(
                Payroll.organization_id == organization_id,
                Payroll.employee_id == employee_id,
                Payroll.period_year == year,
                Payroll.period_month == month,
                PayrollVersion.is_current.is_(True),
            ).limit(1)
        )

    def add(self, run: PayrollImportValidationRun,
            results: list[PayrollImportValidationResult]) -> None:
        self._session.add(run)
        self._session.flush()
        self._session.add_all(results)
        self._session.flush()
        run.results = results

    def list_runs(self, organization_id: UUID, import_id: UUID):
        return list(self._session.execute(
            select(PayrollImportValidationRun).where(
                PayrollImportValidationRun.organization_id == organization_id,
                PayrollImportValidationRun.payroll_import_id == import_id,
            ).options(selectinload(PayrollImportValidationRun.results)).order_by(
                PayrollImportValidationRun.created_at.desc(),
                PayrollImportValidationRun.id,
            )
        ).scalars().all())

    def get_run(self, organization_id: UUID, import_id: UUID, run_id: UUID):
        return self._session.execute(
            select(PayrollImportValidationRun).where(
                PayrollImportValidationRun.id == run_id,
                PayrollImportValidationRun.organization_id == organization_id,
                PayrollImportValidationRun.payroll_import_id == import_id,
            ).options(selectinload(PayrollImportValidationRun.results))
        ).scalar_one_or_none()


__all__ = ["PayrollValidationRepository"]
