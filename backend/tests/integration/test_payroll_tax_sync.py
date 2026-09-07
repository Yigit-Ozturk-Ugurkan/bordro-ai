from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    TaxSyncDownstreamRebuildRequiredError,
    TaxSyncNotMaterializedError,
    TaxSyncPriorPeriodRequiredError,
    TaxSyncReconciliationFailedError,
    TaxSyncRuleSetNotFoundError,
    TaxSyncVersionNotCurrentError,
)
from app.models.enums import PayrollValidationSeverity, UserRoleType
from app.models.payroll import PayrollVersion
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_materialization import PayrollImportMaterialization
from app.models.payroll_tax_sync import PayrollTaxLedgerSync
from app.models.tax import TaxBracket, TaxCalculationRun, TaxCumulativeRecord, TaxRuleSet
from app.schemas.payroll_import import (
    PayrollReviewCorrectionRequest,
    PayrollReviewFinalizeRequest,
)
from app.services.imports.payroll_adapter_service import PayrollAdapterService
from app.services.imports.payroll_approval_service import PayrollApprovalService
from app.services.imports.payroll_materialization_service import (
    PayrollMaterializationService,
)
from app.services.imports.payroll_review_service import PayrollReviewService
from app.services.imports.payroll_validation_service import PayrollValidationService
from app.services.taxation.payroll_tax_sync_service import (
    PayrollTaxLedgerSyncService,
)
from tests.integration.test_payroll_approval import (
    immutable_upstream_state,
    immutable_validation_state,
)
from tests.integration.test_payroll_materialization import (
    approval_evidence_state,
    seed_additional_review_import,
)
from tests.integration.test_payroll_review import mapped_by_source, seed_review_import
from tests.integration.test_payroll_review_api import bearer, seed_users_and_import
from tests.integration.test_payroll_validation import add_employee


FINANCIAL_FIELDS = (
    "gross_earnings", "sgk_base", "income_tax_base", "stamp_tax_base",
    "employee_sgk", "employee_unemployment", "income_tax", "stamp_tax",
    "total_earnings", "total_deductions", "net_pay", "paid_days",
    "missing_days",
)


def financial_state(version: PayrollVersion):
    return tuple(getattr(version, field) for field in FINANCIAL_FIELDS)


async def tax_counts(session: AsyncSession):
    return tuple([
        await session.scalar(select(func.count()).select_from(model))
        for model in (
            TaxCalculationRun, TaxCumulativeRecord, PayrollTaxLedgerSync,
            PayrollEarning, PayrollDeduction, PayrollAbsence,
        )
    ])


async def materialize_period(
    session: AsyncSession, *, user=None, item=None,
    year=2026, month=1, income_tax_base="1000.00", income_tax="150.00",
    add_identity=False,
):
    if user is None or item is None:
        user, item, _ = await session.run_sync(seed_review_import)
        add_identity = True

    await PayrollAdapterService(session).run(user, item.id)
    review = await PayrollReviewService(session).start(user, item.id)
    rows = await mapped_by_source(session, user, item.id)
    replacements = {
        "source-total_earnings": "100000.00",
        "source-total_deductions": "25600.00",
        "source-net_pay": "74400.00",
        "source-period_year": str(year),
        "source-period_month": str(month),
        "source-income_tax_base": income_tax_base,
        "source-income_tax": income_tax,
    }
    for source_id, value in replacements.items():
        review = await PayrollReviewService(session).correct(
            user, item.id, rows[source_id].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=review.version,
                value=value,
                reason="V2.1G deterministic tax fixture",
            ),
        )
    snapshot = await PayrollReviewService(session).finalize(
        user, item.id,
        PayrollReviewFinalizeRequest(expected_review_version=review.version),
    )
    if add_identity:
        await session.run_sync(lambda sync: add_employee(sync, user.organization_id))
    run = await PayrollValidationService(session).validate_snapshot(
        user, item.id, snapshot.id,
    )
    approval_service = PayrollApprovalService(session)
    for result in run.results:
        if result.severity == PayrollValidationSeverity.WARNING:
            await approval_service.acknowledge_warning(
                user, item.id, run.id, result.id,
                "V2.1G acknowledged authoritative-period warning",
            )
    approved = await approval_service.approve(
        user, item.id, run.id, "V2.1G approved evidence",
    )
    materialization = await PayrollMaterializationService(session).materialize(
        user, item.id, approved.decision.id,
    )
    version = await session.get(PayrollVersion, materialization.payroll_version_id)
    return user, item, snapshot, run, approved.decision, materialization, version


async def additional_period(session, user, **values):
    item = await session.run_sync(
        lambda sync: seed_additional_review_import(sync, user)
    )
    return await materialize_period(session, user=user, item=item, **values)


async def clone_ruleset_for_2027(session: AsyncSession):
    source = await session.scalar(select(TaxRuleSet).where(
        TaxRuleSet.version == "TR_PAYROLL_2026_V1",
    ))
    brackets = list(await session.scalars(select(TaxBracket).where(
        TaxBracket.rule_set_id == source.id,
    ).order_by(TaxBracket.sort_order)))
    clone = TaxRuleSet(
        id=uuid4(), jurisdiction=source.jurisdiction,
        name="Test rollover rules copied from active reference data",
        version=f"TEST_2027_{uuid4().hex}",
        effective_from=date(2027, 1, 1), effective_to=date(2028, 1, 1),
        source_reference=source.source_reference, status="ACTIVE",
    )
    session.add(clone)
    await session.flush()
    session.add_all([TaxBracket(
        id=uuid4(), rule_set_id=clone.id, income_type=row.income_type,
        effective_from=date(2027, 1, 1), effective_to=date(2028, 1, 1),
        lower_limit=row.lower_limit, upper_limit=row.upper_limit,
        rate=row.rate, base_tax_amount=row.base_tax_amount,
        sort_order=row.sort_order,
    ) for row in brackets])
    await session.flush()


@pytest.mark.asyncio
async def test_first_year_sync_is_exact_idempotent_and_source_immutable(
    async_db_session: AsyncSession,
):
    user, item, snapshot, run, approval, materialization, version = (
        await materialize_period(async_db_session)
    )
    before_counts = await tax_counts(async_db_session)
    before_financial = financial_state(version)
    before_upstream = await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item.id, snapshot.id)
    )
    before_validation = await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    before_approval = await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, item.id)
    )
    before_materialization = tuple((
        materialization.id, materialization.materialization_checksum,
        materialization.payroll_version_id,
    ))

    service = PayrollTaxLedgerSyncService(async_db_session)
    first = await service.sync(user, item.id)
    after_first = await tax_counts(async_db_session)
    second = await service.sync(user, item.id)

    assert first == second
    assert first.opening_cumulative_base == "0.00"
    assert first.period_income_tax_base == "1000.00"
    assert first.closing_cumulative_base == "1000.00"
    assert first.calculated_withholding == "150.00"
    assert first.authoritative_payroll_withholding == "150.00"
    assert first.reconciliation_status == "MATCHED"
    assert first.prior_sync_id is None
    assert after_first[:3] == tuple(value + 1 for value in before_counts[:3])
    assert after_first[3:] == before_counts[3:]
    assert await tax_counts(async_db_session) == after_first
    assert financial_state(version) == before_financial
    assert before_upstream == await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item.id, snapshot.id)
    )
    assert before_validation == await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    assert before_approval == await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, item.id)
    )
    stored_materialization = await async_db_session.get(
        PayrollImportMaterialization, materialization.id,
    )
    assert before_materialization == tuple((
        stored_materialization.id,
        stored_materialization.materialization_checksum,
        stored_materialization.payroll_version_id,
    ))

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="payroll tax sync evidence is immutable"):
        await async_db_session.execute(update(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.id == first.id,
        ).values(result_checksum="0" * 64))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(
        DBAPIError, match="synchronized tax cumulative evidence is immutable",
    ):
        await async_db_session.execute(update(TaxCumulativeRecord).where(
            TaxCumulativeRecord.id == first.tax_cumulative_record_id,
        ).values(monthly_taxable_base=Decimal("999.00")))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(
        DBAPIError, match="synchronized tax calculation evidence is immutable",
    ):
        await async_db_session.execute(update(TaxCalculationRun).where(
            TaxCalculationRun.id == first.tax_calculation_run_id,
        ).values(calculation_version="tampered"))
    await nested.rollback()


@pytest.mark.asyncio
async def test_import_without_materialization_is_rejected_without_tax_writes(
    async_db_session: AsyncSession,
):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    before = await tax_counts(async_db_session)
    with pytest.raises(TaxSyncNotMaterializedError):
        await PayrollTaxLedgerSyncService(async_db_session).sync(user, item.id)
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_missing_effective_ruleset_fails_closed_without_tax_writes(
    async_db_session: AsyncSession,
):
    user, item, _, _, _, _, _ = await materialize_period(
        async_db_session, year=2027, month=1,
    )
    before = await tax_counts(async_db_session)
    with pytest.raises(TaxSyncRuleSetNotFoundError):
        await PayrollTaxLedgerSyncService(async_db_session).sync(user, item.id)
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_sequential_period_uses_current_prior_chain(
    async_db_session: AsyncSession,
):
    user, _, _, _, _, _, _ = await materialize_period(async_db_session, month=1)
    first_item_id = await async_db_session.scalar(select(
        PayrollImportMaterialization.payroll_import_id,
    ).where(PayrollImportMaterialization.organization_id == user.organization_id))
    first = await PayrollTaxLedgerSyncService(async_db_session).sync(
        user, first_item_id,
    )
    _, second_item, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=2,
    )
    second = await PayrollTaxLedgerSyncService(async_db_session).sync(
        user, second_item.id,
    )

    assert second.prior_sync_id == first.id
    assert second.opening_cumulative_base == "1000.00"
    assert second.closing_cumulative_base == "2000.00"
    assert second.calculated_withholding == "150.00"


@pytest.mark.asyncio
async def test_year_rollover_does_not_carry_previous_year(
    async_db_session: AsyncSession,
):
    await clone_ruleset_for_2027(async_db_session)
    user, item, _, _, _, _, _ = await materialize_period(
        async_db_session, year=2026, month=12,
    )
    await PayrollTaxLedgerSyncService(async_db_session).sync(user, item.id)
    _, january, _, _, _, _, _ = await additional_period(
        async_db_session, user, year=2027, month=1,
    )
    result = await PayrollTaxLedgerSyncService(async_db_session).sync(
        user, january.id,
    )

    assert result.prior_sync_id is None
    assert result.opening_cumulative_base == "0.00"
    assert result.closing_cumulative_base == "1000.00"


@pytest.mark.asyncio
async def test_unsynced_prior_authoritative_period_fails_without_tax_writes(
    async_db_session: AsyncSession,
):
    user, _, _, _, _, _, _ = await materialize_period(async_db_session, month=1)
    _, february, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=2,
    )
    before = await tax_counts(async_db_session)
    with pytest.raises(TaxSyncPriorPeriodRequiredError):
        await PayrollTaxLedgerSyncService(async_db_session).sync(
            user, february.id,
        )
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_reconciliation_mismatch_fails_before_any_tax_persistence(
    async_db_session: AsyncSession,
):
    user, item, _, _, _, _, version = await materialize_period(
        async_db_session, income_tax="151.00",
    )
    before = await tax_counts(async_db_session)
    before_financial = financial_state(version)
    with pytest.raises(TaxSyncReconciliationFailedError):
        await PayrollTaxLedgerSyncService(async_db_session).sync(user, item.id)
    assert await tax_counts(async_db_session) == before
    await async_db_session.refresh(version)
    assert financial_state(version) == before_financial


@pytest.mark.asyncio
async def test_same_period_revision_supersedes_only_ledger_lifecycle(
    async_db_session: AsyncSession,
):
    user, first_item, _, _, _, _, first_version = await materialize_period(
        async_db_session, month=1,
    )
    service = PayrollTaxLedgerSyncService(async_db_session)
    first = await service.sync(user, first_item.id)
    old_sync = await async_db_session.get(PayrollTaxLedgerSync, first.id)
    old_record = await async_db_session.get(
        TaxCumulativeRecord, first.tax_cumulative_record_id,
    )
    old_record_id = old_record.id
    old_sync_id = old_sync.id
    historical_values = (
        old_record.calculation_run_id, old_record.employee_id,
        old_record.payroll_version_id, old_record.tax_year,
        old_record.period_month, old_record.opening_cumulative_base,
        old_record.monthly_taxable_base, old_record.closing_cumulative_base,
        old_record.gross_calculated_tax, old_record.tax_exemptions,
        old_record.withholding_tax, old_record.effective_tax_rate,
        old_record.supersedes_record_id,
    )
    historical_evidence = (
        old_sync.organization_id, old_sync.payroll_import_id,
        old_sync.materialization_id, old_sync.payroll_id,
        old_sync.payroll_version_id, old_sync.employee_id,
        old_sync.tax_year, old_sync.period_year, old_sync.period_month,
        old_sync.tax_calculation_run_id, old_sync.tax_cumulative_record_id,
        old_sync.prior_sync_id, old_sync.supersedes_sync_id,
        old_sync.ruleset_id, old_sync.ruleset_version,
        old_sync.payroll_source_checksum, old_sync.result_checksum,
        old_sync.reconciliation_status, old_sync.synced_by_user_id,
        old_sync.synced_at, old_sync.created_at,
    )
    _, second_item, _, _, _, _, second_version = await additional_period(
        async_db_session, user, month=1,
    )
    second = await service.sync(user, second_item.id)

    await async_db_session.refresh(old_sync)
    await async_db_session.refresh(old_record)
    new_record = await async_db_session.get(
        TaxCumulativeRecord, second.tax_cumulative_record_id,
    )
    assert first_version.is_current is False
    assert second_version.is_current is True
    assert old_sync.is_current is False
    assert old_record.is_current is False
    assert second.is_current is True
    assert second.supersedes_sync_id == first.id
    assert new_record.supersedes_record_id == old_record.id
    assert historical_values == (
        old_record.calculation_run_id, old_record.employee_id,
        old_record.payroll_version_id, old_record.tax_year,
        old_record.period_month, old_record.opening_cumulative_base,
        old_record.monthly_taxable_base, old_record.closing_cumulative_base,
        old_record.gross_calculated_tax, old_record.tax_exemptions,
        old_record.withholding_tax, old_record.effective_tax_rate,
        old_record.supersedes_record_id,
    )
    assert historical_evidence == (
        old_sync.organization_id, old_sync.payroll_import_id,
        old_sync.materialization_id, old_sync.payroll_id,
        old_sync.payroll_version_id, old_sync.employee_id,
        old_sync.tax_year, old_sync.period_year, old_sync.period_month,
        old_sync.tax_calculation_run_id, old_sync.tax_cumulative_record_id,
        old_sync.prior_sync_id, old_sync.supersedes_sync_id,
        old_sync.ruleset_id, old_sync.ruleset_version,
        old_sync.payroll_source_checksum, old_sync.result_checksum,
        old_sync.reconciliation_status, old_sync.synced_by_user_id,
        old_sync.synced_at, old_sync.created_at,
    )
    assert await async_db_session.scalar(select(func.count()).select_from(
        PayrollTaxLedgerSync,
    ).where(
        PayrollTaxLedgerSync.organization_id == user.organization_id,
        PayrollTaxLedgerSync.employee_id == old_sync.employee_id,
        PayrollTaxLedgerSync.tax_year == old_sync.tax_year,
        PayrollTaxLedgerSync.period_month == old_sync.period_month,
        PayrollTaxLedgerSync.is_current.is_(True),
    )) == 1
    assert await async_db_session.scalar(select(func.count()).select_from(
        TaxCumulativeRecord,
    ).where(
        TaxCumulativeRecord.employee_id == old_record.employee_id,
        TaxCumulativeRecord.tax_year == old_record.tax_year,
        TaxCumulativeRecord.period_month == old_record.period_month,
        TaxCumulativeRecord.is_current.is_(True),
    )) == 1
    assert await async_db_session.scalar(select(func.count()).select_from(
        TaxCalculationRun,
    ).where(TaxCalculationRun.payroll_version_id.in_([
        first_version.id, second_version.id,
    ]))) == 2
    assert (await service.current(user, first_item.id)).tax_sync.is_current is False

    nested = await async_db_session.begin_nested()
    with pytest.raises(
        DBAPIError, match="synchronized tax cumulative evidence is immutable",
    ):
        await async_db_session.execute(update(TaxCumulativeRecord).where(
            TaxCumulativeRecord.id == old_record_id,
        ).values(is_current=True))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(
        DBAPIError, match="synchronized tax cumulative evidence is immutable",
    ):
        await async_db_session.execute(update(TaxCumulativeRecord).where(
            TaxCumulativeRecord.id == old_record_id,
        ).values(withholding_tax=Decimal("1.00")))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="payroll tax sync evidence is immutable"):
        await async_db_session.execute(update(PayrollTaxLedgerSync).where(
            PayrollTaxLedgerSync.id == old_sync_id,
        ).values(is_current=True))
    await nested.rollback()


@pytest.mark.asyncio
async def test_earlier_revision_is_blocked_when_downstream_sync_exists(
    async_db_session: AsyncSession,
):
    user, january, _, _, _, _, _ = await materialize_period(
        async_db_session, month=1,
    )
    service = PayrollTaxLedgerSyncService(async_db_session)
    await service.sync(user, january.id)
    _, february, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=2,
    )
    february_sync = await service.sync(user, february.id)
    february_before = await async_db_session.get(
        TaxCumulativeRecord, february_sync.tax_cumulative_record_id,
    )
    february_state = (
        february_before.opening_cumulative_base,
        february_before.closing_cumulative_base,
        february_before.withholding_tax,
        february_before.is_current,
    )
    _, revised_january, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    before = await tax_counts(async_db_session)
    with pytest.raises(TaxSyncDownstreamRebuildRequiredError):
        await service.sync(user, revised_january.id)
    assert await tax_counts(async_db_session) == before
    await async_db_session.refresh(february_before)
    assert february_state == (
        february_before.opening_cumulative_base,
        february_before.closing_cumulative_base,
        february_before.withholding_tax,
        february_before.is_current,
    )


@pytest.mark.asyncio
async def test_fresh_sync_of_superseded_version_is_denied(
    async_db_session: AsyncSession,
):
    user, first_item, _, _, _, _, _ = await materialize_period(
        async_db_session, month=1,
    )
    await additional_period(async_db_session, user, month=1)
    before = await tax_counts(async_db_session)
    with pytest.raises(TaxSyncVersionNotCurrentError):
        await PayrollTaxLedgerSyncService(async_db_session).sync(
            user, first_item.id,
        )
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_database_uniqueness_rejects_competing_current_record(
    async_db_session: AsyncSession,
):
    user, item, _, _, _, _, _ = await materialize_period(async_db_session)
    result = await PayrollTaxLedgerSyncService(async_db_session).sync(user, item.id)
    record = await async_db_session.get(
        TaxCumulativeRecord, result.tax_cumulative_record_id,
    )
    original_run = await async_db_session.get(
        TaxCalculationRun, result.tax_calculation_run_id,
    )
    nested = await async_db_session.begin_nested()
    competing_run = TaxCalculationRun(
        id=uuid4(), organization_id=original_run.organization_id,
        employee_id=original_run.employee_id, tax_year=original_run.tax_year,
        rule_set_id=original_run.rule_set_id,
        payroll_version_id=original_run.payroll_version_id,
        trigger_type="IMPORT", status="COMPLETED",
        calculation_version="PAYROLL_TAX_SYNC_V1",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    async_db_session.add(competing_run)
    await async_db_session.flush()
    duplicate = TaxCumulativeRecord(
        id=uuid4(), calculation_run_id=competing_run.id,
        employee_id=record.employee_id,
        payroll_version_id=record.payroll_version_id,
        tax_year=record.tax_year, period_month=record.period_month,
        opening_cumulative_base=record.opening_cumulative_base,
        monthly_taxable_base=record.monthly_taxable_base,
        closing_cumulative_base=record.closing_cumulative_base,
        gross_calculated_tax=record.gross_calculated_tax,
        tax_exemptions=record.tax_exemptions,
        withholding_tax=record.withholding_tax,
        effective_tax_rate=record.effective_tax_rate,
        is_current=True,
    )
    async_db_session.add(duplicate)
    with pytest.raises(IntegrityError, match="uq_tax_cumulative_current_period"):
        await async_db_session.flush()
    await nested.rollback()


@pytest.mark.asyncio
async def test_tax_sync_api_rbac_empty_payload_and_tenant_isolation(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    owner = users[UserRoleType.PAYROLL_ADMIN]
    await materialize_period(
        async_db_session, user=owner, item=item, add_identity=True,
    )
    route = f"/api/v1/payroll-imports/{item.id}/materialization/tax-sync"
    headers = {role: bearer(user) for role, user in users.items()}

    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN,
                 UserRoleType.AUDITOR):
        response = await api_client.get(route, headers=headers[role])
        assert response.status_code == 200
        assert response.json()["synced"] is False
    for role in (UserRoleType.HR_ADMIN, UserRoleType.AUDITOR,
                 UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.post(
            route, headers=headers[role], json={},
        )).status_code == 403
    assert (await api_client.post(
        route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"income_tax": "1.00"},
    )).status_code == 422

    response = await api_client.post(
        route, headers=headers[UserRoleType.PAYROLL_ADMIN], json={},
    )
    assert response.status_code == 200, response.text
    assert response.json()["calculated_withholding"] == "150.00"
    assert response.json()["authoritative_payroll_withholding"] == "150.00"
    assert response.json()["synced_by_user_id"] == str(owner.id)
    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN,
                 UserRoleType.AUDITOR):
        assert (await api_client.get(route, headers=headers[role])).json()[
            "synced"
        ] is True

    outsiders, _ = await async_db_session.run_sync(seed_users_and_import)
    outsider = outsiders[UserRoleType.PAYROLL_ADMIN]
    assert (await api_client.get(route, headers=bearer(outsider))).status_code == 404
    assert (await api_client.post(
        route, headers=bearer(outsider), json={},
    )).status_code == 404
