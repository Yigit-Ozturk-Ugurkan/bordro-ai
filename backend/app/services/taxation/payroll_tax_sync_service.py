"""Atomic reconciliation and revision-aware tax-ledger synchronization."""

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PayrollImportNotFoundError,
    TaxSyncDownstreamRebuildRequiredError,
    TaxSyncIntegrityFailedError,
    TaxSyncNotMaterializedError,
    TaxSyncPriorPeriodRequiredError,
    TaxSyncReconciliationFailedError,
    TaxSyncRuleSetNotFoundError,
    TaxSyncStateConflictError,
    TaxSyncVersionNotCurrentError,
)
from app.core.money import ZERO_MONEY, money_str, quantize_money
from app.models.enums import PayrollApprovalDecision, PayrollVersionStatus
from app.models.payroll_tax_sync import PayrollTaxLedgerSync
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.repositories.payroll_tax_sync_repository import PayrollTaxSyncRepository
from app.schemas.payroll_tax_sync import PayrollTaxSyncRead, PayrollTaxSyncStateRead
from app.services.auth.authentication import AuthenticatedUser
from app.services.taxation.cumulative_tax_service import CumulativeTaxService
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.tax_service import TaxService


TAX_SYNC_CALCULATION_VERSION = "PAYROLL_TAX_SYNC_V1"


class PayrollTaxLedgerSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync(
        self, user: AuthenticatedUser, import_id: UUID,
    ) -> PayrollTaxSyncRead:
        def work(sync_session):
            repository = PayrollTaxSyncRepository(sync_session)
            if not repository.import_exists(user.organization_id, import_id):
                raise PayrollImportNotFoundError()

            materialization = repository.materialization_for_import(
                user.organization_id, import_id,
            )
            if materialization is None:
                raise TaxSyncNotMaterializedError()

            payroll_hint = repository.payroll(
                user.organization_id, materialization.payroll_id,
            )
            if payroll_hint is None:
                raise TaxSyncIntegrityFailedError()

            # One employee lock serializes every period/year chain for that
            # employee. Payroll and version locks follow in stable order.
            employee = repository.employee_for_update(
                user.organization_id, payroll_hint.employee_id,
            )
            payroll = repository.payroll_for_update(
                user.organization_id, materialization.payroll_id,
            )
            version = repository.version_for_update(
                materialization.payroll_id, materialization.payroll_version_id,
            )
            if employee is None or payroll is None or version is None:
                raise TaxSyncIntegrityFailedError()

            existing = repository.for_version(user.organization_id, version.id)
            if existing is not None:
                return self._read(repository, existing)

            self._verify_materialization(
                repository, user, import_id, materialization, payroll, version,
            )
            if (version.status != PayrollVersionStatus.ACTIVE
                    or not version.is_current):
                raise TaxSyncVersionNotCurrentError()

            downstream = repository.downstream_current_sync(
                user.organization_id, employee.id,
                payroll.period_year, payroll.period_month,
            )
            if downstream is not None:
                raise TaxSyncDownstreamRebuildRequiredError()

            prior_sync, prior_record = self._prior_context(
                repository, user.organization_id, employee.id,
                payroll.period_year, payroll.period_month,
            )
            opening_base = (
                prior_record.closing_cumulative_base
                if prior_record is not None else ZERO_MONEY
            )
            previous_gross_tax = (
                prior_record.gross_calculated_tax
                if prior_record is not None else ZERO_MONEY
            )

            superseded_sync = repository.current_period_sync_for_update(
                user.organization_id, employee.id,
                payroll.period_year, payroll.period_month,
            )
            current_record = repository.current_record_for_period(
                employee.id, payroll.period_year, payroll.period_month,
            )
            superseded_record = None
            if superseded_sync is not None:
                superseded_record = repository.record(
                    superseded_sync.tax_cumulative_record_id,
                )
                if (superseded_sync.payroll_version_id == version.id
                        or superseded_record is None
                        or not superseded_record.is_current
                        or current_record is None
                        or current_record.id != superseded_record.id):
                    raise TaxSyncStateConflictError()
            elif current_record is not None:
                raise TaxSyncStateConflictError()

            target_date = date(payroll.period_year, payroll.period_month, 1)
            tax_service = TaxService(sync_session)
            rule_set = tax_service.resolve_rule_set(target_date, "TR")
            if rule_set is None:
                raise TaxSyncRuleSetNotFoundError()
            tax_engine = TaxEngine(sync_session, tax_service)
            closing_base = quantize_money(opening_base + version.income_tax_base)
            try:
                position = tax_engine.calculate_progressive_tax(
                    closing_cumulative_base=closing_base,
                    monthly_taxable_base=version.income_tax_base,
                    rule_set=rule_set,
                    income_type="EMPLOYMENT",
                    target_date=target_date,
                )
                withholding = CumulativeTaxService.calculate_monthly_withholding(
                    position.calculated_tax, previous_gross_tax, ZERO_MONEY,
                )
            except RuntimeError as exc:
                raise TaxSyncRuleSetNotFoundError() from exc
            except (TypeError, ValueError) as exc:
                raise TaxSyncStateConflictError() from exc

            if withholding != version.income_tax:
                raise TaxSyncReconciliationFailedError(
                    "Calculated withholding "
                    f"{money_str(withholding)} does not match authoritative "
                    "payroll withholding "
                    f"{money_str(version.income_tax)}",
                )

            effective_rate = CumulativeTaxService.calculate_effective_tax_rate(
                withholding, version.income_tax_base,
            )
            now = datetime.now(timezone.utc)
            run = TaxCalculationRun(
                id=uuid4(), organization_id=user.organization_id,
                employee_id=employee.id, tax_year=payroll.period_year,
                rule_set_id=rule_set.id, payroll_version_id=version.id,
                trigger_type=(
                    "PAYROLL_REVISION" if superseded_sync is not None else "IMPORT"
                ),
                status="COMPLETED",
                calculation_version=TAX_SYNC_CALCULATION_VERSION,
                started_at=now, completed_at=now,
            )

            if superseded_sync is not None:
                superseded_sync.is_current = False
                repository.flush()
                repository.refresh(superseded_record)

            record = TaxCumulativeRecord(
                id=uuid4(), calculation_run_id=run.id,
                employee_id=employee.id, payroll_version_id=version.id,
                tax_year=payroll.period_year, period_month=payroll.period_month,
                opening_cumulative_base=opening_base,
                monthly_taxable_base=version.income_tax_base,
                closing_cumulative_base=closing_base,
                gross_calculated_tax=position.calculated_tax,
                tax_exemptions=ZERO_MONEY,
                withholding_tax=withholding,
                effective_tax_rate=effective_rate,
                is_current=True,
                supersedes_record_id=(
                    superseded_record.id if superseded_record is not None else None
                ),
                created_at=now,
            )
            repository.add(run)
            repository.add(record)

            checksum = self.result_checksum(
                organization_id=user.organization_id,
                import_id=import_id,
                materialization_id=materialization.id,
                payroll_id=payroll.id,
                payroll_version_id=version.id,
                employee_id=employee.id,
                tax_year=payroll.period_year,
                period_month=payroll.period_month,
                ruleset_id=rule_set.id,
                ruleset_version=rule_set.version,
                payroll_source_checksum=version.source_checksum,
                prior_sync_id=prior_sync.id if prior_sync is not None else None,
                supersedes_sync_id=(
                    superseded_sync.id if superseded_sync is not None else None
                ),
                opening_base=opening_base,
                monthly_base=version.income_tax_base,
                closing_base=closing_base,
                gross_tax=position.calculated_tax,
                withholding=withholding,
            )
            evidence = PayrollTaxLedgerSync(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id,
                materialization_id=materialization.id,
                payroll_id=payroll.id, payroll_version_id=version.id,
                employee_id=employee.id,
                tax_year=payroll.period_year, period_year=payroll.period_year,
                period_month=payroll.period_month,
                tax_calculation_run_id=run.id,
                tax_cumulative_record_id=record.id,
                prior_sync_id=prior_sync.id if prior_sync is not None else None,
                supersedes_sync_id=(
                    superseded_sync.id if superseded_sync is not None else None
                ),
                ruleset_id=rule_set.id, ruleset_version=rule_set.version,
                payroll_source_checksum=version.source_checksum,
                result_checksum=checksum, reconciliation_status="MATCHED",
                is_current=True, synced_by_user_id=user.id,
                synced_at=now, created_at=now,
            )
            repository.add(evidence)
            return self._read(repository, evidence)

        return await self._commit(work)

    async def current(
        self, user: AuthenticatedUser, import_id: UUID,
    ) -> PayrollTaxSyncStateRead:
        def work(sync_session):
            repository = PayrollTaxSyncRepository(sync_session)
            if not repository.import_exists(user.organization_id, import_id):
                raise PayrollImportNotFoundError()
            evidence = repository.for_import(user.organization_id, import_id)
            return PayrollTaxSyncStateRead(
                import_id=import_id,
                synced=evidence is not None,
                tax_sync=(self._read(repository, evidence)
                          if evidence is not None else None),
            )

        return await self._session.run_sync(work)

    @staticmethod
    def _verify_materialization(
        repository, user, import_id, materialization, payroll, version,
    ) -> None:
        approval = repository.approval(materialization.approval_id)
        if (approval is None
                or approval.decision != PayrollApprovalDecision.APPROVED
                or approval.organization_id != user.organization_id
                or approval.payroll_import_id != import_id
                or materialization.organization_id != user.organization_id
                or materialization.payroll_import_id != import_id
                or materialization.payroll_id != payroll.id
                or materialization.payroll_version_id != version.id
                or payroll.organization_id != user.organization_id
                or version.payroll_id != payroll.id
                or version.source_import_id != import_id
                or version.source_checksum is None
                or version.source_checksum != materialization.snapshot_checksum
                or approval.snapshot_checksum != materialization.snapshot_checksum
                or approval.validation_result_checksum
                    != materialization.validation_result_checksum
                or approval.approval_checksum != materialization.approval_checksum):
            raise TaxSyncIntegrityFailedError()

    @staticmethod
    def _prior_context(
        repository, organization_id, employee_id, tax_year, period_month,
    ):
        prior_version = repository.prior_authoritative_version(
            organization_id, employee_id, tax_year, period_month,
        )
        if prior_version is None:
            return None, None
        prior_sync = repository.for_version(organization_id, prior_version.id)
        if prior_sync is None or not prior_sync.is_current:
            raise TaxSyncPriorPeriodRequiredError()
        prior_record = repository.record(prior_sync.tax_cumulative_record_id)
        if (prior_record is None or not prior_record.is_current
                or prior_record.payroll_version_id != prior_version.id):
            raise TaxSyncIntegrityFailedError()
        return prior_sync, prior_record

    async def _commit(self, work):
        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except DBAPIError as exc:
            await self._session.rollback()
            raise TaxSyncIntegrityFailedError() from exc
        except Exception:
            await self._session.rollback()
            raise

    @staticmethod
    def result_checksum(**values) -> str:
        payload = {
            key: (str(value) if isinstance(value, (UUID, Decimal)) else value)
            for key, value in values.items()
        }
        canonical = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _read(
        repository: PayrollTaxSyncRepository, evidence: PayrollTaxLedgerSync,
    ) -> PayrollTaxSyncRead:
        record = repository.record(evidence.tax_cumulative_record_id)
        run = repository.calculation_run(evidence.tax_calculation_run_id)
        version = repository.version(evidence.payroll_version_id)
        if (record is None or run is None or version is None
                or version.income_tax != record.withholding_tax
                or version.income_tax_base != record.monthly_taxable_base):
            raise TaxSyncIntegrityFailedError()
        return PayrollTaxSyncRead(
            id=evidence.id, import_id=evidence.payroll_import_id,
            materialization_id=evidence.materialization_id,
            payroll_id=evidence.payroll_id,
            payroll_version_id=evidence.payroll_version_id,
            employee_id=evidence.employee_id,
            tax_year=evidence.tax_year, period_year=evidence.period_year,
            period_month=evidence.period_month,
            ruleset_id=evidence.ruleset_id,
            ruleset_version=evidence.ruleset_version,
            tax_calculation_run_id=evidence.tax_calculation_run_id,
            tax_cumulative_record_id=evidence.tax_cumulative_record_id,
            prior_sync_id=evidence.prior_sync_id,
            supersedes_sync_id=evidence.supersedes_sync_id,
            opening_cumulative_base=money_str(record.opening_cumulative_base),
            period_income_tax_base=money_str(record.monthly_taxable_base),
            closing_cumulative_base=money_str(record.closing_cumulative_base),
            calculated_withholding=money_str(record.withholding_tax),
            authoritative_payroll_withholding=money_str(version.income_tax),
            reconciliation_status=evidence.reconciliation_status,
            result_checksum=evidence.result_checksum,
            is_current=evidence.is_current,
            synced_by_user_id=evidence.synced_by_user_id,
            synced_at=evidence.synced_at,
        )


__all__ = ["PayrollTaxLedgerSyncService", "TAX_SYNC_CALCULATION_VERSION"]
