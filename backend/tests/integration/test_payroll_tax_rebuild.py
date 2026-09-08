from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    TaxRebuildNotRequiredError,
    TaxRebuildPlanStaleError,
    TaxRebuildPriorContextRequiredError,
    TaxRebuildReconciliationFailedError,
    TaxRebuildStateConflictError,
    TaxSyncDownstreamRebuildRequiredError,
)
from app.models.enums import UserRoleType
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_materialization import PayrollImportMaterialization
from app.models.payroll_tax_rebuild import (
    PayrollTaxLedgerRebuild,
    PayrollTaxLedgerRebuildItem,
)
from app.models.payroll_tax_sync import PayrollTaxLedgerSync
from app.models.tax import TaxBracket, TaxCumulativeRecord
from app.services.taxation.payroll_tax_rebuild_service import (
    PayrollTaxLedgerRebuildService,
)
from app.services.taxation.payroll_tax_sync_service import (
    PayrollTaxLedgerSyncService,
)
from tests.integration.test_payroll_review_api import bearer, seed_users_and_import
from tests.integration.test_payroll_approval import (
    immutable_upstream_state,
    immutable_validation_state,
)
from tests.integration.test_payroll_materialization import approval_evidence_state
from tests.integration.test_payroll_tax_sync import (
    additional_period,
    clone_ruleset_for_2027,
    financial_state,
    materialize_period,
    tax_counts,
)


async def synced_months(session: AsyncSession, count: int, *, user=None, item=None):
    user, first, _, _, _, _, _ = await materialize_period(
        session, user=user, item=item, month=1,
        add_identity=user is not None,
    )
    imports = [first]
    syncs = [await PayrollTaxLedgerSyncService(session).sync(user, first.id)]
    for month in range(2, count + 1):
        _, current, _, _, _, _, _ = await additional_period(
            session, user, month=month,
        )
        imports.append(current)
        syncs.append(
            await PayrollTaxLedgerSyncService(session).sync(user, current.id)
        )
    return user, imports, syncs


async def current_syncs(session, employee_id, tax_year, months):
    return list(await session.scalars(select(PayrollTaxLedgerSync).where(
        PayrollTaxLedgerSync.employee_id == employee_id,
        PayrollTaxLedgerSync.tax_year == tax_year,
        PayrollTaxLedgerSync.period_month.in_(months),
        PayrollTaxLedgerSync.is_current.is_(True),
    ).order_by(PayrollTaxLedgerSync.period_month)))


@pytest.mark.asyncio
async def test_three_period_rebuild_is_explicit_sequential_and_append_only(
    async_db_session: AsyncSession,
):
    user, old_imports, old_sync_reads = await synced_months(async_db_session, 3)
    old_syncs = [
        await async_db_session.get(PayrollTaxLedgerSync, row.id)
        for row in old_sync_reads
    ]
    old_records = [
        await async_db_session.get(TaxCumulativeRecord, row.tax_cumulative_record_id)
        for row in old_sync_reads
    ]
    historical_values = [(
        record.id, record.opening_cumulative_base,
        record.monthly_taxable_base, record.closing_cumulative_base,
        record.gross_calculated_tax, record.tax_exemptions,
        record.withholding_tax, record.effective_tax_rate,
    ) for record in old_records]
    _, revised, snapshot, validation, _, materialization, trigger_version = await additional_period(
        async_db_session, user, month=1,
    )
    source_before = financial_state(trigger_version)
    upstream_before = await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, revised.id, snapshot.id)
    )
    validation_before = await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, validation.id)
    )
    approval_before = await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, revised.id)
    )
    materialization_before = (
        materialization.id, materialization.materialization_checksum,
        materialization.payroll_version_id,
    )
    downstream_versions = [
        await async_db_session.get(PayrollVersion, row.payroll_version_id)
        for row in old_syncs[1:]
    ]
    downstream_financial = {
        row.id: financial_state(row) for row in downstream_versions
    }
    before = await tax_counts(async_db_session)

    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revised.id)

    assert plan.status == "PLANNED"
    assert plan.trigger_period == "2026-01"
    assert plan.affected_periods == ["2026-01", "2026-02", "2026-03"]
    assert plan.affected_count == 3
    assert len(plan.plan_checksum) == 64
    assert all(item.execution_status == "PENDING" for item in plan.items)
    assert await tax_counts(async_db_session) == before

    completed = await service.execute(user, revised.id, plan.id)

    assert completed.status == "COMPLETED"
    assert len(completed.result_checksum) == 64
    assert all(item.execution_status == "COMPLETED" for item in completed.items)
    after = await tax_counts(async_db_session)
    assert after[:3] == tuple(value + 3 for value in before[:3])
    new_syncs = await current_syncs(
        async_db_session, completed.employee_id, 2026, [1, 2, 3],
    )
    assert len(new_syncs) == 3
    assert new_syncs[0].prior_sync_id is None
    assert new_syncs[1].prior_sync_id == new_syncs[0].id
    assert new_syncs[2].prior_sync_id == new_syncs[1].id
    assert [row.supersedes_sync_id for row in new_syncs] == [
        row.id for row in old_syncs
    ]
    for month in (1, 2, 3):
        assert await async_db_session.scalar(select(func.count()).select_from(
            TaxCumulativeRecord,
        ).where(
            TaxCumulativeRecord.employee_id == completed.employee_id,
            TaxCumulativeRecord.tax_year == 2026,
            TaxCumulativeRecord.period_month == month,
            TaxCumulativeRecord.is_current.is_(True),
        )) == 1
    for old_sync, old_record, values, new_sync in zip(
        old_syncs, old_records, historical_values, new_syncs, strict=True,
    ):
        await async_db_session.refresh(old_sync)
        await async_db_session.refresh(old_record)
        assert old_sync.is_current is False
        assert old_record.is_current is False
        assert values == (
            old_record.id, old_record.opening_cumulative_base,
            old_record.monthly_taxable_base, old_record.closing_cumulative_base,
            old_record.gross_calculated_tax, old_record.tax_exemptions,
            old_record.withholding_tax, old_record.effective_tax_rate,
        )
        new_record = await async_db_session.get(
            TaxCumulativeRecord, new_sync.tax_cumulative_record_id,
        )
        assert new_record.supersedes_record_id == old_record.id
        assert new_record.is_current is True
    assert financial_state(trigger_version) == source_before
    assert upstream_before == await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, revised.id, snapshot.id)
    )
    assert validation_before == await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, validation.id)
    )
    assert approval_before == await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, revised.id)
    )
    stored_materialization = await async_db_session.get(
        PayrollImportMaterialization, materialization.id,
    )
    assert materialization_before == (
        stored_materialization.id, stored_materialization.materialization_checksum,
        stored_materialization.payroll_version_id,
    )
    for version_id, values in downstream_financial.items():
        stored_version = await async_db_session.get(PayrollVersion, version_id)
        assert financial_state(stored_version) == values
    idempotent_downstream = await PayrollTaxLedgerSyncService(
        async_db_session,
    ).sync(user, old_imports[1].id)
    assert idempotent_downstream.id == new_syncs[1].id
    assert await tax_counts(async_db_session) == after


@pytest.mark.asyncio
async def test_midyear_plan_starts_at_trigger_and_skips_missing_months(
    async_db_session: AsyncSession,
):
    user, imports, initial_sync_reads = await synced_months(async_db_session, 6)
    earlier_syncs = await current_syncs(
        async_db_session, initial_sync_reads[0].employee_id, 2026, [1, 2, 3],
    )
    _, april_revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=4,
    )
    plan = await PayrollTaxLedgerRebuildService(async_db_session).create(
        user, april_revision.id,
    )
    assert plan.affected_periods == ["2026-04", "2026-05", "2026-06"]
    assert "2026-01" not in plan.affected_periods
    assert plan.items[0].old_tax_sync_id is not None
    assert imports[0].id != april_revision.id
    completed = await PayrollTaxLedgerRebuildService(async_db_session).execute(
        user, april_revision.id, plan.id,
    )
    current = await current_syncs(
        async_db_session, completed.employee_id, 2026, [1, 2, 3, 4],
    )
    assert [row.id for row in current[:3]] == [row.id for row in earlier_syncs]
    april_record = await async_db_session.get(
        TaxCumulativeRecord, current[3].tax_cumulative_record_id,
    )
    assert current[3].prior_sync_id == current[2].id
    assert april_record.opening_cumulative_base == Decimal("3000.00")


@pytest.mark.asyncio
async def test_missing_calendar_month_is_not_fabricated(
    async_db_session: AsyncSession,
):
    user, january, _, _, _, _, _ = await materialize_period(
        async_db_session, month=1,
    )
    sync_service = PayrollTaxLedgerSyncService(async_db_session)
    await sync_service.sync(user, january.id)
    _, march, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=3,
    )
    await sync_service.sync(user, march.id)
    _, april, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=4,
    )
    await sync_service.sync(user, april.id)
    _, revised, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    plan = await PayrollTaxLedgerRebuildService(async_db_session).create(
        user, revised.id,
    )
    assert plan.affected_periods == ["2026-01", "2026-03", "2026-04"]
    assert await async_db_session.scalar(select(func.count()).select_from(
        Payroll,
    ).where(
        Payroll.employee_id == plan.employee_id,
        Payroll.period_year == 2026,
        Payroll.period_month == 2,
    )) == 0
    completed = await PayrollTaxLedgerRebuildService(async_db_session).execute(
        user, revised.id, plan.id,
    )
    current = await current_syncs(
        async_db_session, completed.employee_id, 2026, [1, 3, 4],
    )
    assert [row.period_month for row in current] == [1, 3, 4]
    assert current[1].prior_sync_id == current[0].id
    assert current[2].prior_sync_id == current[1].id


@pytest.mark.asyncio
async def test_tax_year_boundary_isolated_from_next_year(
    async_db_session: AsyncSession,
):
    await clone_ruleset_for_2027(async_db_session)
    user, november, _, _, _, _, _ = await materialize_period(
        async_db_session, year=2026, month=11,
    )
    sync_service = PayrollTaxLedgerSyncService(async_db_session)
    await sync_service.sync(user, november.id)
    _, december, _, _, _, _, _ = await additional_period(
        async_db_session, user, year=2026, month=12,
    )
    await sync_service.sync(user, december.id)
    _, january, _, _, _, _, _ = await additional_period(
        async_db_session, user, year=2027, month=1,
    )
    january_sync = await sync_service.sync(user, january.id)
    _, revised_november, _, _, _, _, _ = await additional_period(
        async_db_session, user, year=2026, month=11,
    )

    plan = await PayrollTaxLedgerRebuildService(async_db_session).create(
        user, revised_november.id,
    )
    assert plan.affected_periods == ["2026-11", "2026-12"]
    await PayrollTaxLedgerRebuildService(async_db_session).execute(
        user, revised_november.id, plan.id,
    )
    stored_january = await async_db_session.get(
        PayrollTaxLedgerSync, january_sync.id,
    )
    assert stored_january.is_current is True


@pytest.mark.asyncio
async def test_rebuild_not_required_and_normal_sync_still_blocks_downstream(
    async_db_session: AsyncSession,
):
    user, imports, _ = await synced_months(async_db_session, 2)
    with pytest.raises(TaxRebuildNotRequiredError):
        await PayrollTaxLedgerRebuildService(async_db_session).create(
            user, imports[1].id,
        )
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    with pytest.raises(TaxSyncDownstreamRebuildRequiredError):
        await PayrollTaxLedgerSyncService(async_db_session).sync(user, revision.id)


@pytest.mark.asyncio
async def test_midyear_rebuild_requires_exact_current_prior_context(
    async_db_session: AsyncSession,
):
    user, _, sync_reads = await synced_months(async_db_session, 3)
    january_sync = await async_db_session.get(
        PayrollTaxLedgerSync, sync_reads[0].id,
    )
    january_sync.is_current = False
    await async_db_session.commit()
    _, february_revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=2,
    )
    before = await tax_counts(async_db_session)

    with pytest.raises(TaxRebuildPriorContextRequiredError):
        await PayrollTaxLedgerRebuildService(async_db_session).create(
            user, february_revision.id,
        )
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_reconciliation_failure_rolls_back_entire_tax_chain(
    async_db_session: AsyncSession,
):
    user, january, _, _, _, _, _ = await materialize_period(
        async_db_session, month=1, income_tax_base="180000.00",
        income_tax="27000.00",
    )
    sync_service = PayrollTaxLedgerSyncService(async_db_session)
    january_sync = await sync_service.sync(user, january.id)
    _, february, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=2, income_tax_base="20000.00",
        income_tax="3500.00",
    )
    february_sync = await sync_service.sync(user, february.id)
    _, march, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=3, income_tax_base="1000.00",
        income_tax="200.00",
    )
    march_sync = await sync_service.sync(user, march.id)
    _, revised, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1, income_tax_base="170000.00",
        income_tax="25500.00",
    )
    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revised.id)
    revised_id = revised.id
    plan_id = plan.id
    before = await tax_counts(async_db_session)

    with pytest.raises(TaxRebuildReconciliationFailedError):
        await service.execute(user, revised_id, plan_id)

    assert await tax_counts(async_db_session) == before
    for sync_id in (january_sync.id, february_sync.id, march_sync.id):
        sync = await async_db_session.get(PayrollTaxLedgerSync, sync_id)
        record = await async_db_session.get(
            TaxCumulativeRecord, sync.tax_cumulative_record_id,
        )
        assert sync.is_current is True
        assert record.is_current is True
    failed = await service.get(user, revised_id, plan_id)
    assert failed.status == "FAILED"
    assert failed.failure_code == "TAX_REBUILD_RECONCILIATION_FAILED"
    assert all(item.execution_status == "PENDING" for item in failed.items)
    with pytest.raises(TaxRebuildStateConflictError):
        await service.execute(user, revised_id, plan_id)
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_changed_planned_version_makes_plan_stale_without_tax_writes(
    async_db_session: AsyncSession,
):
    user, _, _ = await synced_months(async_db_session, 2)
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revision.id)
    revision_id = revision.id
    plan_id = plan.id
    _, _, _, _, _, _, newer_february = await additional_period(
        async_db_session, user, month=2,
    )
    newer_february_id = newer_february.id
    before = await tax_counts(async_db_session)

    with pytest.raises(TaxRebuildPlanStaleError):
        await service.execute(user, revision_id, plan_id)

    assert await tax_counts(async_db_session) == before
    newer_february = await async_db_session.get(PayrollVersion, newer_february_id)
    assert newer_february.is_current is True
    assert (await service.get(user, revision_id, plan_id)).status == "FAILED"


@pytest.mark.asyncio
async def test_new_later_period_makes_plan_stale(
    async_db_session: AsyncSession,
):
    user, _, _ = await synced_months(async_db_session, 2)
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revision.id)
    _, march, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=3,
    )
    march_sync = await PayrollTaxLedgerSyncService(async_db_session).sync(
        user, march.id,
    )
    before = await tax_counts(async_db_session)

    with pytest.raises(TaxRebuildPlanStaleError):
        await service.execute(user, revision.id, plan.id)
    assert await tax_counts(async_db_session) == before
    assert (await async_db_session.get(
        PayrollTaxLedgerSync, march_sync.id,
    )).is_current is True


@pytest.mark.asyncio
async def test_ruleset_change_makes_plan_stale(
    async_db_session: AsyncSession,
):
    user, _, _ = await synced_months(async_db_session, 2)
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revision.id)
    stored_item = await async_db_session.scalar(select(
        PayrollTaxLedgerRebuildItem,
    ).where(PayrollTaxLedgerRebuildItem.rebuild_id == plan.id).order_by(
        PayrollTaxLedgerRebuildItem.sequence,
    ).limit(1))
    bracket = await async_db_session.scalar(select(TaxBracket).where(
        TaxBracket.rule_set_id == stored_item.ruleset_id,
    ).order_by(TaxBracket.sort_order).limit(1))
    bracket.rate = Decimal("0.160000")
    await async_db_session.commit()
    before = await tax_counts(async_db_session)

    with pytest.raises(TaxRebuildPlanStaleError):
        await service.execute(user, revision.id, plan.id)
    assert await tax_counts(async_db_session) == before


@pytest.mark.asyncio
async def test_completed_execution_is_idempotent_and_evidence_immutable(
    async_db_session: AsyncSession,
):
    user, _, _ = await synced_months(async_db_session, 2)
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revision.id)
    first = await service.execute(user, revision.id, plan.id)
    counts = await tax_counts(async_db_session)
    second = await service.execute(user, revision.id, plan.id)
    assert second == first
    assert await tax_counts(async_db_session) == counts

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="tax rebuild evidence is immutable"):
        await async_db_session.execute(update(PayrollTaxLedgerRebuild).where(
            PayrollTaxLedgerRebuild.id == plan.id,
        ).values(plan_checksum="0" * 64))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="tax rebuild item evidence is immutable"):
        await async_db_session.execute(update(PayrollTaxLedgerRebuildItem).where(
            PayrollTaxLedgerRebuildItem.rebuild_id == plan.id,
        ).values(old_sync_result_checksum="0" * 64))
    await nested.rollback()


@pytest.mark.asyncio
async def test_only_one_actionable_plan_per_employee_tax_year(
    async_db_session: AsyncSession,
):
    user, _, _ = await synced_months(async_db_session, 2)
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    service = PayrollTaxLedgerRebuildService(async_db_session)
    plan = await service.create(user, revision.id)
    assert (await service.create(user, revision.id)).id == plan.id

    index_definition = await async_db_session.scalar(text(
        "SELECT indexdef FROM pg_indexes "
        "WHERE indexname = 'uq_tax_rebuild_actionable_chain'"
    ))
    assert "UNIQUE INDEX" in index_definition
    assert "status" in index_definition and "PLANNED" in index_definition
    _, newer_revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    with pytest.raises(TaxRebuildStateConflictError):
        await service.create(user, newer_revision.id)


@pytest.mark.asyncio
async def test_rebuild_api_rbac_payload_and_tenant_isolation(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    owner = users[UserRoleType.PAYROLL_ADMIN]
    user, _, _ = await synced_months(
        async_db_session, 2, user=owner, item=item,
    )
    _, revision, _, _, _, _, _ = await additional_period(
        async_db_session, user, month=1,
    )
    route = f"/api/v1/payroll-imports/{revision.id}/materialization/tax-rebuilds"
    headers = {role: bearer(principal) for role, principal in users.items()}

    for role in (UserRoleType.HR_ADMIN, UserRoleType.AUDITOR,
                 UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.post(
            route, headers=headers[role], json={},
        )).status_code == 403
    assert (await api_client.post(
        route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"periods": [1, 2]},
    )).status_code == 422
    created = await api_client.post(
        route, headers=headers[UserRoleType.PAYROLL_ADMIN], json={},
    )
    assert created.status_code == 201, created.text
    rebuild_id = created.json()["id"]
    detail_route = f"{route}/{rebuild_id}"
    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN,
                 UserRoleType.AUDITOR):
        assert (await api_client.get(
            detail_route, headers=headers[role],
        )).status_code == 200
        assert (await api_client.get(
            route, headers=headers[role],
        )).status_code == 200
    for role in (UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.get(
            detail_route, headers=headers[role],
        )).status_code == 403
    assert (await api_client.post(
        f"{detail_route}/execute",
        headers=headers[UserRoleType.HR_ADMIN], json={},
    )).status_code == 403
    assert (await api_client.post(
        f"{detail_route}/execute",
        headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"income_tax": "1.00"},
    )).status_code == 422
    completed = await api_client.post(
        f"{detail_route}/execute",
        headers=headers[UserRoleType.PAYROLL_ADMIN], json={},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"

    outsiders, _ = await async_db_session.run_sync(seed_users_and_import)
    outsider = outsiders[UserRoleType.PAYROLL_ADMIN]
    await async_db_session.commit()
    assert (await api_client.get(
        route, headers=bearer(outsider),
    )).status_code == 404
    assert (await api_client.post(
        route, headers=bearer(outsider), json={},
    )).status_code == 404
    assert (await api_client.get(
        detail_route, headers=bearer(outsider),
    )).status_code == 404
    assert (await api_client.post(
        f"{detail_route}/execute", headers=bearer(outsider), json={},
    )).status_code == 404
