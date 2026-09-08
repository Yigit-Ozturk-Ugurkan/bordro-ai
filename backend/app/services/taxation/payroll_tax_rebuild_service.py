"""Explicit, audited, atomic rebuilding of a cumulative payroll-tax chain."""

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BordroError,
    PayrollImportNotFoundError,
    TaxRebuildAlreadyRunningError,
    TaxRebuildIntegrityFailedError,
    TaxRebuildNotFoundError,
    TaxRebuildNotRequiredError,
    TaxRebuildPlanStaleError,
    TaxRebuildPriorContextRequiredError,
    TaxRebuildReconciliationFailedError,
    TaxRebuildRuleSetNotFoundError,
    TaxRebuildStateConflictError,
)
from app.core.money import ZERO_MONEY, quantize_money
from app.models.enums import PayrollApprovalDecision, PayrollVersionStatus
from app.models.payroll_tax_rebuild import (
    PayrollTaxLedgerRebuild,
    PayrollTaxLedgerRebuildItem,
)
from app.models.payroll_tax_sync import PayrollTaxLedgerSync
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.repositories.payroll_tax_rebuild_repository import (
    PayrollTaxRebuildRepository,
)
from app.schemas.payroll_tax_rebuild import (
    PayrollTaxRebuildItemRead,
    PayrollTaxRebuildList,
    PayrollTaxRebuildRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.taxation.cumulative_tax_service import CumulativeTaxService
from app.services.taxation.payroll_tax_sync_service import (
    PayrollTaxLedgerSyncService,
)
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.tax_service import TaxService


TAX_REBUILD_CALCULATION_VERSION = "PAYROLL_TAX_REBUILD_V1"
FINANCIAL_FIELDS = (
    "gross_earnings", "sgk_base", "income_tax_base", "stamp_tax_base",
    "employee_sgk", "employee_unemployment", "income_tax", "stamp_tax",
    "total_earnings", "total_deductions", "net_pay", "paid_days",
    "missing_days",
)


class PayrollTaxLedgerRebuildService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user: AuthenticatedUser, import_id: UUID,
    ) -> PayrollTaxRebuildRead:
        def work(sync_session):
            repository = PayrollTaxRebuildRepository(sync_session)
            materialization = self._context(repository, user, import_id)
            payroll_hint = repository.payroll(
                user.organization_id, materialization.payroll_id,
            )
            if payroll_hint is None:
                raise TaxRebuildIntegrityFailedError()
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
                raise TaxRebuildIntegrityFailedError()
            self._verify_trigger(
                repository, user, import_id, materialization, payroll, version,
            )
            if repository.downstream_current_sync(
                user.organization_id, employee.id,
                payroll.period_year, payroll.period_month,
            ) is None:
                raise TaxRebuildNotRequiredError()

            actionable = repository.actionable_rebuild(
                user.organization_id, employee.id, payroll.period_year,
            )
            if actionable is not None:
                if (actionable.trigger_payroll_import_id == import_id
                        and actionable.trigger_payroll_version_id == version.id):
                    return self._read(repository, actionable)
                raise TaxRebuildStateConflictError(
                    "Another actionable rebuild already protects this employee/tax year",
                )

            prior_sync, prior_record = self._prior_context(
                repository, user.organization_id, employee.id,
                payroll.period_year, payroll.period_month,
            )
            chain = repository.authoritative_chain(
                user.organization_id, employee.id,
                payroll.period_year, payroll.period_month,
            )
            if (not chain or chain[0][0].id != payroll.id
                    or chain[0][1].id != version.id):
                raise TaxRebuildIntegrityFailedError()

            item_values = [
                self._plan_item_values(
                    repository, user.organization_id, employee.id,
                    payroll.period_year, sequence, chain_payroll, chain_version,
                )
                for sequence, (chain_payroll, chain_version)
                in enumerate(chain, start=1)
            ]
            rebuild_id = uuid4()
            plan_checksum = self._plan_checksum(
                organization_id=user.organization_id,
                employee_id=employee.id,
                tax_year=payroll.period_year,
                trigger_payroll_version_id=version.id,
                prior_sync_id=prior_sync.id if prior_sync else None,
                prior_record_id=prior_record.id if prior_record else None,
                prior_sync_result_checksum=(
                    prior_sync.result_checksum if prior_sync else None
                ),
                items=item_values,
            )
            rebuild = PayrollTaxLedgerRebuild(
                id=rebuild_id, organization_id=user.organization_id,
                employee_id=employee.id, tax_year=payroll.period_year,
                trigger_payroll_import_id=import_id,
                trigger_materialization_id=materialization.id,
                trigger_payroll_id=payroll.id,
                trigger_payroll_version_id=version.id,
                trigger_period_year=payroll.period_year,
                trigger_period_month=payroll.period_month,
                prior_sync_id=prior_sync.id if prior_sync else None,
                prior_cumulative_record_id=prior_record.id if prior_record else None,
                prior_sync_result_checksum=(
                    prior_sync.result_checksum if prior_sync else None
                ),
                status="PLANNED", created_by_user_id=user.id,
                plan_checksum=plan_checksum,
            )
            repository.add(rebuild)
            for values in item_values:
                repository.add(PayrollTaxLedgerRebuildItem(
                    id=uuid4(), rebuild_id=rebuild_id, **values,
                ))
            return self._read(repository, rebuild)

        return await self._commit(work, constraint_conflict=True)

    async def get(
        self, user: AuthenticatedUser, import_id: UUID, rebuild_id: UUID,
    ) -> PayrollTaxRebuildRead:
        def work(sync_session):
            repository = PayrollTaxRebuildRepository(sync_session)
            self._require_import(repository, user, import_id)
            rebuild = repository.rebuild(
                user.organization_id, import_id, rebuild_id,
            )
            if rebuild is None:
                raise TaxRebuildNotFoundError()
            return self._read(repository, rebuild)

        return await self._session.run_sync(work)

    async def list(
        self, user: AuthenticatedUser, import_id: UUID,
    ) -> PayrollTaxRebuildList:
        def work(sync_session):
            repository = PayrollTaxRebuildRepository(sync_session)
            self._require_import(repository, user, import_id)
            return PayrollTaxRebuildList(items=[
                self._read(repository, rebuild)
                for rebuild in repository.rebuilds(user.organization_id, import_id)
            ])

        return await self._session.run_sync(work)

    async def execute(
        self, user: AuthenticatedUser, import_id: UUID, rebuild_id: UUID,
    ) -> PayrollTaxRebuildRead:
        def work(sync_session):
            repository = PayrollTaxRebuildRepository(sync_session)
            self._require_import(repository, user, import_id)
            rebuild_hint = repository.rebuild(
                user.organization_id, import_id, rebuild_id,
            )
            if rebuild_hint is None:
                raise TaxRebuildNotFoundError()
            employee = repository.employee_for_update(
                user.organization_id, rebuild_hint.employee_id,
            )
            if employee is None:
                raise TaxRebuildIntegrityFailedError()
            rebuild = repository.rebuild(
                user.organization_id, import_id, rebuild_id, for_update=True,
            )
            if rebuild is None:
                raise TaxRebuildNotFoundError()
            if rebuild.status == "COMPLETED":
                return self._read(repository, rebuild)
            if rebuild.status == "RUNNING":
                raise TaxRebuildAlreadyRunningError()
            if rebuild.status != "PLANNED":
                raise TaxRebuildStateConflictError()
            contexts = self._verify_plan(repository, rebuild)
            items = repository.items(rebuild.id)
            now = datetime.now(timezone.utc)
            rebuild.status = "RUNNING"
            rebuild.executed_by_user_id = user.id
            rebuild.started_at = now
            repository.flush()

            prior_sync = None
            prior_record = None
            if rebuild.prior_sync_id is not None:
                prior_record = repository.record(
                    rebuild.prior_cumulative_record_id,
                )
                if prior_record is None:
                    raise TaxRebuildPlanStaleError()
                prior_sync = repository.current_sync(
                    rebuild.organization_id, rebuild.employee_id,
                    rebuild.tax_year, prior_record.period_month,
                )
                if prior_sync is None or prior_sync.id != rebuild.prior_sync_id:
                    raise TaxRebuildPlanStaleError()

            opening_base = (
                prior_record.closing_cumulative_base if prior_record else ZERO_MONEY
            )
            previous_gross_tax = (
                prior_record.gross_calculated_tax if prior_record else ZERO_MONEY
            )
            result_values = []
            for item, context in zip(items, contexts, strict=True):
                payroll, version, materialization, rule_set = context
                old_sync = repository.current_sync(
                    rebuild.organization_id, rebuild.employee_id,
                    rebuild.tax_year, payroll.period_month, for_update=True,
                )
                old_record = None
                if item.old_tax_sync_id is not None:
                    if old_sync is None or old_sync.id != item.old_tax_sync_id:
                        raise TaxRebuildPlanStaleError()
                    old_record = repository.record(item.old_cumulative_record_id)
                    if old_record is None or not old_record.is_current:
                        raise TaxRebuildPlanStaleError()
                    old_sync.is_current = False
                    repository.flush()
                    repository.refresh(old_record)
                elif old_sync is not None:
                    raise TaxRebuildPlanStaleError()

                target_date = date(payroll.period_year, payroll.period_month, 1)
                tax_service = TaxService(sync_session)
                tax_engine = TaxEngine(sync_session, tax_service)
                closing_base = quantize_money(opening_base + version.income_tax_base)
                try:
                    position = tax_engine.calculate_progressive_tax(
                        closing_cumulative_base=closing_base,
                        monthly_taxable_base=version.income_tax_base,
                        rule_set=rule_set, income_type="EMPLOYMENT",
                        target_date=target_date,
                    )
                    withholding = CumulativeTaxService.calculate_monthly_withholding(
                        position.calculated_tax, previous_gross_tax, ZERO_MONEY,
                    )
                except RuntimeError as exc:
                    raise TaxRebuildRuleSetNotFoundError() from exc
                except (TypeError, ValueError) as exc:
                    raise TaxRebuildIntegrityFailedError() from exc
                if withholding != version.income_tax:
                    raise TaxRebuildReconciliationFailedError()

                effective_rate = CumulativeTaxService.calculate_effective_tax_rate(
                    withholding, version.income_tax_base,
                )
                row_time = datetime.now(timezone.utc)
                run = TaxCalculationRun(
                    id=uuid4(), organization_id=rebuild.organization_id,
                    employee_id=rebuild.employee_id, tax_year=rebuild.tax_year,
                    rule_set_id=rule_set.id, payroll_version_id=version.id,
                    trigger_type="DOWNSTREAM_REBUILD", status="COMPLETED",
                    calculation_version=TAX_REBUILD_CALCULATION_VERSION,
                    started_at=row_time, completed_at=row_time,
                )
                record = TaxCumulativeRecord(
                    id=uuid4(), calculation_run_id=run.id,
                    employee_id=rebuild.employee_id,
                    payroll_version_id=version.id, tax_year=rebuild.tax_year,
                    period_month=payroll.period_month,
                    opening_cumulative_base=opening_base,
                    monthly_taxable_base=version.income_tax_base,
                    closing_cumulative_base=closing_base,
                    gross_calculated_tax=position.calculated_tax,
                    tax_exemptions=ZERO_MONEY, withholding_tax=withholding,
                    effective_tax_rate=effective_rate, is_current=True,
                    supersedes_record_id=old_record.id if old_record else None,
                    created_at=row_time,
                )
                repository.add(run)
                repository.add(record)
                sync_checksum = PayrollTaxLedgerSyncService.result_checksum(
                    organization_id=rebuild.organization_id,
                    import_id=materialization.payroll_import_id,
                    materialization_id=materialization.id,
                    payroll_id=payroll.id, payroll_version_id=version.id,
                    employee_id=rebuild.employee_id, tax_year=rebuild.tax_year,
                    period_month=payroll.period_month,
                    ruleset_id=rule_set.id, ruleset_version=rule_set.version,
                    payroll_source_checksum=version.source_checksum,
                    prior_sync_id=prior_sync.id if prior_sync else None,
                    supersedes_sync_id=old_sync.id if old_sync else None,
                    opening_base=opening_base,
                    monthly_base=version.income_tax_base,
                    closing_base=closing_base,
                    gross_tax=position.calculated_tax,
                    withholding=withholding,
                )
                evidence = PayrollTaxLedgerSync(
                    id=uuid4(), organization_id=rebuild.organization_id,
                    payroll_import_id=materialization.payroll_import_id,
                    materialization_id=materialization.id,
                    payroll_id=payroll.id, payroll_version_id=version.id,
                    employee_id=rebuild.employee_id,
                    tax_year=rebuild.tax_year, period_year=rebuild.tax_year,
                    period_month=payroll.period_month,
                    tax_calculation_run_id=run.id,
                    tax_cumulative_record_id=record.id,
                    prior_sync_id=prior_sync.id if prior_sync else None,
                    supersedes_sync_id=old_sync.id if old_sync else None,
                    ruleset_id=rule_set.id, ruleset_version=rule_set.version,
                    payroll_source_checksum=version.source_checksum,
                    result_checksum=sync_checksum,
                    reconciliation_status="MATCHED", is_current=True,
                    synced_by_user_id=user.id, synced_at=row_time,
                    created_at=row_time,
                )
                repository.add(evidence)
                item.execution_status = "COMPLETED"
                item.new_tax_calculation_run_id = run.id
                item.new_tax_sync_id = evidence.id
                item.new_cumulative_record_id = record.id
                item.reconciliation_status = "MATCHED"
                item.completed_at = row_time
                repository.flush()
                result_values.append({
                    "sequence": item.sequence,
                    "tax_sync_id": evidence.id,
                    "result_checksum": sync_checksum,
                    "cumulative_record_id": record.id,
                })
                prior_sync, prior_record = evidence, record
                opening_base = record.closing_cumulative_base
                previous_gross_tax = record.gross_calculated_tax

            rebuild.status = "COMPLETED"
            rebuild.completed_at = datetime.now(timezone.utc)
            rebuild.result_checksum = self._sha256({
                "plan_checksum": rebuild.plan_checksum,
                "results": result_values,
            })
            repository.flush()
            return self._read(repository, rebuild)

        try:
            return await self._commit(work)
        except (TaxRebuildNotFoundError, TaxRebuildAlreadyRunningError,
                TaxRebuildStateConflictError):
            raise
        except BordroError as exc:
            await self._mark_failed(user, import_id, rebuild_id, exc)
            raise

    def _verify_plan(self, repository, rebuild):
        items = repository.items(rebuild.id)
        if not items or rebuild.plan_checksum != self._plan_checksum_from_rows(
            rebuild, items,
        ):
            raise TaxRebuildPlanStaleError()
        chain = repository.authoritative_chain(
            rebuild.organization_id, rebuild.employee_id, rebuild.tax_year,
            rebuild.trigger_period_month, for_update=True,
        )
        if len(chain) != len(items):
            raise TaxRebuildPlanStaleError()
        contexts = []
        for item, (payroll, version) in zip(items, chain, strict=True):
            materialization = repository.materialization_for_version(
                rebuild.organization_id, version.id,
            )
            if (item.sequence != len(contexts) + 1
                    or item.period_year != rebuild.tax_year
                    or item.period_month != payroll.period_month
                    or item.payroll_id != payroll.id
                    or item.payroll_version_id != version.id
                    or materialization is None
                    or item.materialization_id != materialization.id
                    or item.payroll_import_id != materialization.payroll_import_id
                    or item.payroll_version_checksum != self._version_checksum(version)
                    or item.execution_status != "PENDING"):
                raise TaxRebuildPlanStaleError()
            current_sync, current_record = self._current_evidence(
                repository, rebuild.organization_id, rebuild.employee_id,
                rebuild.tax_year, payroll.period_month,
            )
            if ((current_sync.id if current_sync else None) != item.old_tax_sync_id
                    or (current_record.id if current_record else None)
                        != item.old_cumulative_record_id
                    or (current_sync.result_checksum if current_sync else None)
                        != item.old_sync_result_checksum):
                raise TaxRebuildPlanStaleError()
            target_date = date(rebuild.tax_year, payroll.period_month, 1)
            rule_set = TaxService(repository.session).resolve_rule_set(
                target_date, "TR",
            )
            if rule_set is None:
                raise TaxRebuildRuleSetNotFoundError()
            locked_rule_set = repository.rule_set_for_share(rule_set.id)
            brackets = repository.brackets_for_share(rule_set.id, target_date)
            if (locked_rule_set is None or rule_set.id != item.ruleset_id
                    or rule_set.version != item.ruleset_version
                    or self._ruleset_checksum(rule_set, brackets)
                        != item.ruleset_checksum):
                raise TaxRebuildPlanStaleError()
            contexts.append((payroll, version, materialization, rule_set))

        if (items[0].payroll_version_id != rebuild.trigger_payroll_version_id
                or items[0].payroll_id != rebuild.trigger_payroll_id
                or items[0].payroll_import_id != rebuild.trigger_payroll_import_id
                or items[0].materialization_id != rebuild.trigger_materialization_id):
            raise TaxRebuildPlanStaleError()
        expected_prior_sync, expected_prior_record = self._prior_context(
            repository, rebuild.organization_id, rebuild.employee_id,
            rebuild.tax_year, rebuild.trigger_period_month,
        )
        if ((expected_prior_sync.id if expected_prior_sync else None)
                != rebuild.prior_sync_id
                or (expected_prior_record.id if expected_prior_record else None)
                != rebuild.prior_cumulative_record_id
                or (expected_prior_sync.result_checksum
                    if expected_prior_sync else None)
                != rebuild.prior_sync_result_checksum):
            raise TaxRebuildPlanStaleError()
        return contexts

    def _plan_item_values(
        self, repository, organization_id, employee_id, tax_year,
        sequence, payroll, version,
    ):
        materialization = repository.materialization_for_version(
            organization_id, version.id,
        )
        if (materialization is None or version.source_import_id is None
                or materialization.payroll_import_id != version.source_import_id
                or materialization.snapshot_checksum != version.source_checksum):
            raise TaxRebuildIntegrityFailedError()
        current_sync, current_record = self._current_evidence(
            repository, organization_id, employee_id,
            tax_year, payroll.period_month,
        )
        target_date = date(tax_year, payroll.period_month, 1)
        tax_service = TaxService(repository.session)
        rule_set = tax_service.resolve_rule_set(target_date, "TR")
        if rule_set is None:
            raise TaxRebuildRuleSetNotFoundError()
        brackets = tax_service.get_tax_brackets(
            rule_set.id, "EMPLOYMENT", target_date,
        )
        if not brackets:
            raise TaxRebuildRuleSetNotFoundError()
        return {
            "sequence": sequence,
            "payroll_import_id": materialization.payroll_import_id,
            "materialization_id": materialization.id,
            "payroll_id": payroll.id,
            "payroll_version_id": version.id,
            "period_year": payroll.period_year,
            "period_month": payroll.period_month,
            "old_tax_sync_id": current_sync.id if current_sync else None,
            "old_cumulative_record_id": current_record.id if current_record else None,
            "old_sync_result_checksum": (
                current_sync.result_checksum if current_sync else None
            ),
            "ruleset_id": rule_set.id,
            "ruleset_version": rule_set.version,
            "ruleset_checksum": self._ruleset_checksum(rule_set, brackets),
            "payroll_version_checksum": self._version_checksum(version),
            "execution_status": "PENDING",
        }

    @staticmethod
    def _current_evidence(
        repository, organization_id, employee_id, tax_year, period_month,
    ):
        sync = repository.current_sync(
            organization_id, employee_id, tax_year, period_month,
        )
        record = repository.current_record_for_period(
            employee_id, tax_year, period_month,
        )
        if sync is None:
            if record is not None or repository.any_period_sync(
                organization_id, employee_id, tax_year, period_month,
            ) is not None:
                raise TaxRebuildIntegrityFailedError()
            return None, None
        linked = repository.record(sync.tax_cumulative_record_id)
        if (record is None or linked is None or linked.id != record.id
                or not sync.is_current or not record.is_current):
            raise TaxRebuildIntegrityFailedError()
        return sync, record

    @staticmethod
    def _prior_context(
        repository, organization_id, employee_id, tax_year, trigger_month,
    ):
        version = repository.prior_authoritative_version(
            organization_id, employee_id, tax_year, trigger_month,
        )
        if version is None:
            return None, None
        sync = repository.for_version(organization_id, version.id)
        if sync is None or not sync.is_current:
            raise TaxRebuildPriorContextRequiredError()
        record = repository.record(sync.tax_cumulative_record_id)
        if (record is None or not record.is_current
                or record.payroll_version_id != version.id):
            raise TaxRebuildPriorContextRequiredError()
        return sync, record

    @staticmethod
    def _context(repository, user, import_id):
        if not repository.import_exists(user.organization_id, import_id):
            raise PayrollImportNotFoundError()
        materialization = repository.materialization_for_import(
            user.organization_id, import_id,
        )
        if materialization is None:
            raise TaxRebuildStateConflictError(
                "An authoritative materialization is required for a tax rebuild",
            )
        return materialization

    @staticmethod
    def _require_import(repository, user, import_id):
        if not repository.import_exists(user.organization_id, import_id):
            raise PayrollImportNotFoundError()

    @staticmethod
    def _verify_trigger(repository, user, import_id, materialization, payroll, version):
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
                or version.source_checksum != materialization.snapshot_checksum
                or version.status != PayrollVersionStatus.ACTIVE
                or not version.is_current):
            raise TaxRebuildIntegrityFailedError()

    @classmethod
    def _version_checksum(cls, version) -> str:
        values = {
            "id": version.id, "payroll_id": version.payroll_id,
            "revision_no": version.revision_no, "status": version.status,
            "source_type": version.source_type, "currency": version.currency,
            "calculation_mode": version.calculation_mode,
            "calculation_version": version.calculation_version,
            "rule_set_id": version.rule_set_id,
            "source_import_id": version.source_import_id,
            "source_checksum": version.source_checksum,
            "is_current": version.is_current,
            **{field: getattr(version, field) for field in FINANCIAL_FIELDS},
        }
        return cls._sha256(values)

    @classmethod
    def _ruleset_checksum(cls, rule_set, brackets) -> str:
        return cls._sha256({
            "id": rule_set.id, "jurisdiction": rule_set.jurisdiction,
            "version": rule_set.version,
            "effective_from": rule_set.effective_from,
            "effective_to": rule_set.effective_to,
            "status": rule_set.status,
            "brackets": [{
                "id": row.id, "income_type": row.income_type,
                "effective_from": row.effective_from,
                "effective_to": row.effective_to,
                "lower_limit": row.lower_limit,
                "upper_limit": row.upper_limit, "rate": row.rate,
                "base_tax_amount": row.base_tax_amount,
                "sort_order": row.sort_order,
            } for row in brackets],
        })

    @classmethod
    def _plan_checksum(
        cls, *, organization_id, employee_id, tax_year,
        trigger_payroll_version_id, prior_sync_id, prior_record_id,
        prior_sync_result_checksum, items,
    ) -> str:
        stable_items = [{
            key: value for key, value in item.items()
            if key not in {"execution_status"}
        } for item in items]
        return cls._sha256({
            "organization_id": organization_id,
            "employee_id": employee_id,
            "tax_year": tax_year,
            "trigger_payroll_version_id": trigger_payroll_version_id,
            "prior_sync_id": prior_sync_id,
            "prior_cumulative_record_id": prior_record_id,
            "prior_sync_result_checksum": prior_sync_result_checksum,
            "items": stable_items,
        })

    @classmethod
    def _plan_checksum_from_rows(cls, rebuild, items) -> str:
        return cls._plan_checksum(
            organization_id=rebuild.organization_id,
            employee_id=rebuild.employee_id, tax_year=rebuild.tax_year,
            trigger_payroll_version_id=rebuild.trigger_payroll_version_id,
            prior_sync_id=rebuild.prior_sync_id,
            prior_record_id=rebuild.prior_cumulative_record_id,
            prior_sync_result_checksum=rebuild.prior_sync_result_checksum,
            items=[{
                "sequence": item.sequence,
                "payroll_import_id": item.payroll_import_id,
                "materialization_id": item.materialization_id,
                "payroll_id": item.payroll_id,
                "payroll_version_id": item.payroll_version_id,
                "period_year": item.period_year,
                "period_month": item.period_month,
                "old_tax_sync_id": item.old_tax_sync_id,
                "old_cumulative_record_id": item.old_cumulative_record_id,
                "old_sync_result_checksum": item.old_sync_result_checksum,
                "ruleset_id": item.ruleset_id,
                "ruleset_version": item.ruleset_version,
                "ruleset_checksum": item.ruleset_checksum,
                "payroll_version_checksum": item.payroll_version_checksum,
                "execution_status": "PENDING",
            } for item in items],
        )

    @staticmethod
    def _sha256(values) -> str:
        def normalize(value):
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            if isinstance(value, (UUID, Decimal)):
                return str(value)
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            if hasattr(value, "value"):
                return value.value
            return value

        canonical = json.dumps(
            normalize(values), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _commit(self, work, *, constraint_conflict=False):
        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except IntegrityError as exc:
            await self._session.rollback()
            error_type = (
                TaxRebuildStateConflictError
                if constraint_conflict else TaxRebuildIntegrityFailedError
            )
            raise error_type() from exc
        except DBAPIError as exc:
            await self._session.rollback()
            raise TaxRebuildIntegrityFailedError() from exc
        except Exception:
            await self._session.rollback()
            raise

    async def _mark_failed(self, user, import_id, rebuild_id, error):
        try:
            def work(sync_session):
                repository = PayrollTaxRebuildRepository(sync_session)
                rebuild = repository.rebuild(
                    user.organization_id, import_id, rebuild_id, for_update=True,
                )
                if rebuild is None or rebuild.status != "PLANNED":
                    return
                rebuild.status = "FAILED"
                rebuild.executed_by_user_id = user.id
                rebuild.completed_at = datetime.now(timezone.utc)
                rebuild.failure_code = error.code or "TAX_REBUILD_INTEGRITY_FAILED"
                rebuild.failure_message = error.default_message
                repository.flush()

            await self._session.run_sync(work)
            await self._session.commit()
        except Exception:
            await self._session.rollback()

    @staticmethod
    def _read(repository, rebuild):
        items = repository.items(rebuild.id)
        return PayrollTaxRebuildRead(
            id=rebuild.id, status=rebuild.status,
            employee_id=rebuild.employee_id, tax_year=rebuild.tax_year,
            trigger_period=(
                f"{rebuild.trigger_period_year:04d}-"
                f"{rebuild.trigger_period_month:02d}"
            ),
            trigger_payroll_version_id=rebuild.trigger_payroll_version_id,
            affected_periods=[
                f"{item.period_year:04d}-{item.period_month:02d}" for item in items
            ],
            affected_count=len(items), plan_checksum=rebuild.plan_checksum,
            result_checksum=rebuild.result_checksum,
            created_by_user_id=rebuild.created_by_user_id,
            executed_by_user_id=rebuild.executed_by_user_id,
            created_at=rebuild.created_at, started_at=rebuild.started_at,
            completed_at=rebuild.completed_at, failure_code=rebuild.failure_code,
            items=[PayrollTaxRebuildItemRead(
                sequence=item.sequence, payroll_id=item.payroll_id,
                payroll_version_id=item.payroll_version_id,
                period=f"{item.period_year:04d}-{item.period_month:02d}",
                old_tax_sync_id=item.old_tax_sync_id,
                old_cumulative_record_id=item.old_cumulative_record_id,
                execution_status=item.execution_status,
                new_tax_sync_id=item.new_tax_sync_id,
                new_cumulative_record_id=item.new_cumulative_record_id,
                reconciliation_status=item.reconciliation_status,
            ) for item in items],
        )


__all__ = ["PayrollTaxLedgerRebuildService", "TAX_REBUILD_CALCULATION_VERSION"]
