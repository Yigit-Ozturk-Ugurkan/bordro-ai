"""Organization-scoped persistence and locking for explicit tax rebuilds."""

from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.models.enums import PayrollVersionStatus
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_materialization import PayrollImportMaterialization
from app.models.payroll_tax_rebuild import (
    PayrollTaxLedgerRebuild,
    PayrollTaxLedgerRebuildItem,
)
from app.models.payroll_tax_sync import PayrollTaxLedgerSync
from app.models.tax import TaxBracket, TaxRuleSet
from app.repositories.payroll_tax_sync_repository import PayrollTaxSyncRepository


class PayrollTaxRebuildRepository(PayrollTaxSyncRepository):
    @property
    def session(self):
        return self._session

    def rebuild(
        self, organization_id: UUID, import_id: UUID, rebuild_id: UUID,
        *, for_update: bool = False,
    ) -> PayrollTaxLedgerRebuild | None:
        stmt = select(PayrollTaxLedgerRebuild).where(
            PayrollTaxLedgerRebuild.id == rebuild_id,
            PayrollTaxLedgerRebuild.organization_id == organization_id,
            PayrollTaxLedgerRebuild.trigger_payroll_import_id == import_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self._session.execute(stmt).scalar_one_or_none()

    def rebuilds(
        self, organization_id: UUID, import_id: UUID,
    ) -> list[PayrollTaxLedgerRebuild]:
        return list(self._session.scalars(select(PayrollTaxLedgerRebuild).where(
            PayrollTaxLedgerRebuild.organization_id == organization_id,
            PayrollTaxLedgerRebuild.trigger_payroll_import_id == import_id,
        ).order_by(
            PayrollTaxLedgerRebuild.created_at.desc(),
            PayrollTaxLedgerRebuild.id.desc(),
        )))

    def actionable_rebuild(
        self, organization_id: UUID, employee_id: UUID, tax_year: int,
    ) -> PayrollTaxLedgerRebuild | None:
        return self._session.execute(select(PayrollTaxLedgerRebuild).where(
            PayrollTaxLedgerRebuild.organization_id == organization_id,
            PayrollTaxLedgerRebuild.employee_id == employee_id,
            PayrollTaxLedgerRebuild.tax_year == tax_year,
            PayrollTaxLedgerRebuild.status.in_(("PLANNED", "RUNNING")),
        ).with_for_update()).scalar_one_or_none()

    def items(self, rebuild_id: UUID) -> list[PayrollTaxLedgerRebuildItem]:
        return list(self._session.scalars(select(PayrollTaxLedgerRebuildItem).where(
            PayrollTaxLedgerRebuildItem.rebuild_id == rebuild_id,
        ).order_by(PayrollTaxLedgerRebuildItem.sequence)))

    def authoritative_chain(
        self, organization_id: UUID, employee_id: UUID, tax_year: int,
        first_month: int, *, for_update: bool = False,
    ) -> list[tuple[Payroll, PayrollVersion]]:
        stmt = select(Payroll, PayrollVersion).join(
            PayrollVersion, PayrollVersion.payroll_id == Payroll.id,
        ).where(
            Payroll.organization_id == organization_id,
            Payroll.employee_id == employee_id,
            Payroll.period_year == tax_year,
            Payroll.period_month >= first_month,
            PayrollVersion.status == PayrollVersionStatus.ACTIVE,
            PayrollVersion.is_current.is_(True),
        ).order_by(Payroll.period_month, Payroll.id, PayrollVersion.id)
        if for_update:
            stmt = stmt.with_for_update(of=(Payroll, PayrollVersion))
        return [(row[0], row[1]) for row in self._session.execute(stmt).all()]

    def materialization_for_version(
        self, organization_id: UUID, version_id: UUID,
    ) -> PayrollImportMaterialization | None:
        return self._session.execute(select(PayrollImportMaterialization).where(
            PayrollImportMaterialization.organization_id == organization_id,
            PayrollImportMaterialization.payroll_version_id == version_id,
        )).scalar_one_or_none()

    def current_sync(
        self, organization_id: UUID, employee_id: UUID, tax_year: int,
        period_month: int, *, for_update: bool = False,
    ) -> PayrollTaxLedgerSync | None:
        stmt = select(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.organization_id == organization_id,
            PayrollTaxLedgerSync.employee_id == employee_id,
            PayrollTaxLedgerSync.tax_year == tax_year,
            PayrollTaxLedgerSync.period_month == period_month,
            PayrollTaxLedgerSync.is_current.is_(True),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self._session.execute(stmt).scalar_one_or_none()

    def any_period_sync(
        self, organization_id: UUID, employee_id: UUID, tax_year: int,
        period_month: int,
    ) -> PayrollTaxLedgerSync | None:
        return self._session.execute(select(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.organization_id == organization_id,
            PayrollTaxLedgerSync.employee_id == employee_id,
            PayrollTaxLedgerSync.tax_year == tax_year,
            PayrollTaxLedgerSync.period_month == period_month,
        ).order_by(PayrollTaxLedgerSync.created_at.desc()).limit(1)).scalar_one_or_none()

    def rule_set_for_share(self, rule_set_id: UUID) -> TaxRuleSet | None:
        return self._session.execute(select(TaxRuleSet).where(
            TaxRuleSet.id == rule_set_id,
        ).with_for_update(read=True)).scalar_one_or_none()

    def brackets_for_share(
        self, rule_set_id: UUID, target_date: date,
    ) -> list[TaxBracket]:
        return list(self._session.scalars(select(TaxBracket).where(
            TaxBracket.rule_set_id == rule_set_id,
            TaxBracket.income_type == "EMPLOYMENT",
            TaxBracket.effective_from <= target_date,
            ((TaxBracket.effective_to.is_(None))
             | (TaxBracket.effective_to > target_date)),
        ).order_by(TaxBracket.sort_order).with_for_update(read=True)))


__all__ = ["PayrollTaxRebuildRepository"]
