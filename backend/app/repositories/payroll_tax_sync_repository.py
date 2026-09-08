"""Organization-scoped locking and persistence for payroll tax sync."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.enums import PayrollVersionStatus
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_approval import PayrollImportApproval
from app.models.payroll_import import PayrollImport
from app.models.payroll_materialization import PayrollImportMaterialization
from app.models.payroll_tax_sync import PayrollTaxLedgerSync
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord, TaxRuleSet


class PayrollTaxSyncRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def import_exists(self, organization_id: UUID, import_id: UUID) -> bool:
        return self._session.scalar(select(PayrollImport.id).where(
            PayrollImport.id == import_id,
            PayrollImport.organization_id == organization_id,
        )) is not None

    def materialization_for_import(
        self, organization_id: UUID, import_id: UUID,
    ) -> PayrollImportMaterialization | None:
        return self._session.execute(select(PayrollImportMaterialization).where(
            PayrollImportMaterialization.organization_id == organization_id,
            PayrollImportMaterialization.payroll_import_id == import_id,
        ).order_by(
            PayrollImportMaterialization.payroll_revision_no.desc(),
        ).limit(1)).scalar_one_or_none()

    def approval(self, approval_id: UUID) -> PayrollImportApproval | None:
        return self._session.get(PayrollImportApproval, approval_id)

    def employee_for_update(
        self, organization_id: UUID, employee_id: UUID,
    ) -> Employee | None:
        return self._session.execute(select(Employee).where(
            Employee.id == employee_id,
            Employee.organization_id == organization_id,
        ).with_for_update()).scalar_one_or_none()

    def payroll_for_update(
        self, organization_id: UUID, payroll_id: UUID,
    ) -> Payroll | None:
        return self._session.execute(select(Payroll).where(
            Payroll.id == payroll_id,
            Payroll.organization_id == organization_id,
        ).with_for_update()).scalar_one_or_none()

    def payroll(self, organization_id: UUID, payroll_id: UUID) -> Payroll | None:
        return self._session.execute(select(Payroll).where(
            Payroll.id == payroll_id,
            Payroll.organization_id == organization_id,
        )).scalar_one_or_none()

    def version_for_update(
        self, payroll_id: UUID, version_id: UUID,
    ) -> PayrollVersion | None:
        return self._session.execute(select(PayrollVersion).where(
            PayrollVersion.id == version_id,
            PayrollVersion.payroll_id == payroll_id,
        ).with_for_update()).scalar_one_or_none()

    def for_version(
        self, organization_id: UUID, version_id: UUID,
    ) -> PayrollTaxLedgerSync | None:
        return self._session.execute(select(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.organization_id == organization_id,
            PayrollTaxLedgerSync.payroll_version_id == version_id,
        ).order_by(
            PayrollTaxLedgerSync.is_current.desc(),
            PayrollTaxLedgerSync.created_at.desc(),
        ).limit(1)).scalar_one_or_none()

    def for_import(
        self, organization_id: UUID, import_id: UUID,
    ) -> PayrollTaxLedgerSync | None:
        return self._session.execute(select(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.organization_id == organization_id,
            PayrollTaxLedgerSync.payroll_import_id == import_id,
        ).order_by(
            PayrollTaxLedgerSync.period_year.desc(),
            PayrollTaxLedgerSync.period_month.desc(),
            PayrollTaxLedgerSync.created_at.desc(),
        ).limit(1)).scalar_one_or_none()

    def prior_authoritative_version(
        self, organization_id: UUID, employee_id: UUID,
        tax_year: int, period_month: int,
    ) -> PayrollVersion | None:
        return self._session.execute(select(PayrollVersion).join(
            Payroll, Payroll.id == PayrollVersion.payroll_id,
        ).where(
            Payroll.organization_id == organization_id,
            Payroll.employee_id == employee_id,
            Payroll.period_year == tax_year,
            Payroll.period_month < period_month,
            PayrollVersion.status == PayrollVersionStatus.ACTIVE,
            PayrollVersion.is_current.is_(True),
        ).order_by(Payroll.period_month.desc()).limit(1)).scalar_one_or_none()

    def downstream_current_sync(
        self, organization_id: UUID, employee_id: UUID,
        tax_year: int, period_month: int,
    ) -> PayrollTaxLedgerSync | None:
        return self._session.execute(select(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.organization_id == organization_id,
            PayrollTaxLedgerSync.employee_id == employee_id,
            PayrollTaxLedgerSync.tax_year == tax_year,
            PayrollTaxLedgerSync.period_month > period_month,
            PayrollTaxLedgerSync.is_current.is_(True),
        ).order_by(PayrollTaxLedgerSync.period_month).limit(1)).scalar_one_or_none()

    def current_period_sync_for_update(
        self, organization_id: UUID, employee_id: UUID,
        tax_year: int, period_month: int,
    ) -> PayrollTaxLedgerSync | None:
        return self._session.execute(select(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.organization_id == organization_id,
            PayrollTaxLedgerSync.employee_id == employee_id,
            PayrollTaxLedgerSync.tax_year == tax_year,
            PayrollTaxLedgerSync.period_month == period_month,
            PayrollTaxLedgerSync.is_current.is_(True),
        ).with_for_update()).scalar_one_or_none()

    def current_record_for_period(
        self, employee_id: UUID, tax_year: int, period_month: int,
    ) -> TaxCumulativeRecord | None:
        return self._session.execute(select(TaxCumulativeRecord).where(
            TaxCumulativeRecord.employee_id == employee_id,
            TaxCumulativeRecord.tax_year == tax_year,
            TaxCumulativeRecord.period_month == period_month,
            TaxCumulativeRecord.is_current.is_(True),
        ).with_for_update()).scalar_one_or_none()

    def record(self, record_id: UUID) -> TaxCumulativeRecord | None:
        return self._session.get(TaxCumulativeRecord, record_id)

    def calculation_run(self, run_id: UUID) -> TaxCalculationRun | None:
        return self._session.get(TaxCalculationRun, run_id)

    def version(self, version_id: UUID) -> PayrollVersion | None:
        return self._session.get(PayrollVersion, version_id)

    def rule_set(self, rule_set_id: UUID) -> TaxRuleSet | None:
        return self._session.get(TaxRuleSet, rule_set_id)

    def add(self, row: object) -> None:
        self._session.add(row)
        self._session.flush()

    def flush(self) -> None:
        self._session.flush()

    def refresh(self, row: object) -> None:
        self._session.refresh(row)


__all__ = ["PayrollTaxSyncRepository"]
