"""Organization-scoped persistence for authoritative payroll materialization."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_approval import PayrollImportApproval
from app.models.payroll_materialization import PayrollImportMaterialization


class PayrollMaterializationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_approval_for_update(
        self, organization_id: UUID, import_id: UUID, approval_id: UUID,
    ):
        return self._session.execute(select(PayrollImportApproval).where(
            PayrollImportApproval.id == approval_id,
            PayrollImportApproval.organization_id == organization_id,
            PayrollImportApproval.payroll_import_id == import_id,
        ).with_for_update()).scalar_one_or_none()

    def for_approval(self, organization_id: UUID, approval_id: UUID):
        return self._session.execute(select(PayrollImportMaterialization).where(
            PayrollImportMaterialization.organization_id == organization_id,
            PayrollImportMaterialization.approval_id == approval_id,
        )).scalar_one_or_none()

    def employee_for_update(self, organization_id: UUID, employee_no: str):
        return self._session.execute(select(Employee).where(
            Employee.organization_id == organization_id,
            Employee.employee_no == employee_no,
        ).with_for_update()).scalar_one_or_none()

    def payroll_for_update(
        self, organization_id: UUID, employee_id: UUID, year: int, month: int,
    ):
        return self._session.execute(select(Payroll).where(
            Payroll.organization_id == organization_id,
            Payroll.employee_id == employee_id,
            Payroll.period_year == year,
            Payroll.period_month == month,
        ).with_for_update()).scalar_one_or_none()

    def current_version_for_update(self, payroll_id: UUID):
        return self._session.execute(select(PayrollVersion).where(
            PayrollVersion.payroll_id == payroll_id,
            PayrollVersion.is_current.is_(True),
        ).with_for_update()).scalar_one_or_none()

    def next_revision(self, payroll_id: UUID) -> int:
        maximum = self._session.scalar(select(func.max(
            PayrollVersion.revision_no,
        )).where(PayrollVersion.payroll_id == payroll_id))
        return (maximum or 0) + 1

    def get_payroll(self, organization_id: UUID, payroll_id: UUID):
        return self._session.execute(select(Payroll).where(
            Payroll.id == payroll_id,
            Payroll.organization_id == organization_id,
        )).scalar_one_or_none()

    def get_version(self, payroll_id: UUID, version_id: UUID):
        return self._session.execute(select(PayrollVersion).where(
            PayrollVersion.id == version_id,
            PayrollVersion.payroll_id == payroll_id,
        )).scalar_one_or_none()

    def add_payroll(self, row: Payroll) -> None:
        self._session.add(row)
        self._session.flush()

    def add_version(self, row: PayrollVersion) -> None:
        self._session.add(row)
        self._session.flush()

    def add_materialization(self, row: PayrollImportMaterialization) -> None:
        self._session.add(row)
        self._session.flush()


__all__ = ["PayrollMaterializationRepository"]
