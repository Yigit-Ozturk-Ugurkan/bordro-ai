from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.enums import (
    CalculationMode,
    EmployeeStatus,
    PayrollSourceType,
    PayrollValidationReadiness,
    PayrollValidationSeverity,
    PayrollVersionStatus,
    UserRoleType,
)
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_import import PayrollImportField, PayrollImportMappedField
from app.models.payroll_review import PayrollImportFieldCorrection, PayrollImportReviewSnapshot
from app.models.payroll_validation import PayrollImportValidationResult, PayrollImportValidationRun
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.schemas.payroll_import import PayrollReviewCorrectionRequest, PayrollReviewFinalizeRequest
from app.services.imports.payroll_adapter_service import PayrollAdapterService
from app.services.imports.payroll_review_service import PayrollReviewService
from app.services.imports.payroll_validation_service import PayrollValidationService
from tests.integration.test_payroll_review import mapped_by_source, seed_review_import
from tests.integration.test_payroll_review_api import bearer, seed_users_and_import


async def make_snapshot(session, user, item, *, net="74400.00", month="9", year="2026"):
    await PayrollAdapterService(session).run(user, item.id)
    review = await PayrollReviewService(session).start(user, item.id)
    rows = await mapped_by_source(session, user, item.id)
    replacements = {
        "source-total_earnings": "100000.00",
        "source-total_deductions": "25600.00",
        "source-net_pay": net,
        "source-period_month": month,
        "source-period_year": year,
    }
    version = review.version
    for source_id, value in replacements.items():
        review = await PayrollReviewService(session).correct(
            user, item.id, rows[source_id].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=version, value=value, reason="Validation fixture",
            ),
        )
        version = review.version
    return await PayrollReviewService(session).finalize(
        user, item.id, PayrollReviewFinalizeRequest(expected_review_version=version),
    )


def add_employee(sync: Session, organization_id, employee_no="EMP-42"):
    employee = Employee(
        id=uuid4(), organization_id=organization_id, employee_no=employee_no,
        first_name="Validation", last_name="Employee", hire_date=date(2024, 1, 1),
        status=EmployeeStatus.ACTIVE,
    )
    sync.add(employee)
    sync.flush()
    return employee


def relevant_counts(sync: Session):
    models = (
        Payroll, PayrollVersion, PayrollEarning, PayrollDeduction, PayrollAbsence,
        TaxCalculationRun, TaxCumulativeRecord, PayrollImportReviewSnapshot,
        PayrollImportFieldCorrection, PayrollImportMappedField, PayrollImportField,
    )
    return tuple(sync.scalar(select(func.count()).select_from(model)) for model in models)


def review_input_state(sync: Session, import_id, snapshot_id):
    snapshot = sync.get(PayrollImportReviewSnapshot, snapshot_id)
    corrections = sync.scalars(select(PayrollImportFieldCorrection).where(
        PayrollImportFieldCorrection.payroll_import_id == import_id,
    ).order_by(PayrollImportFieldCorrection.id)).all()
    mapped = sync.scalars(select(PayrollImportMappedField).where(
        PayrollImportMappedField.payroll_import_id == import_id,
    ).order_by(PayrollImportMappedField.id)).all()
    staging = sync.scalars(select(PayrollImportField).where(
        PayrollImportField.payroll_import_id == import_id,
    ).order_by(PayrollImportField.id)).all()
    return (
        snapshot.snapshot_checksum, snapshot.field_count, snapshot.issue_count,
        tuple((row.id, row.reason, row.override_canonical_key, row.value_text,
               row.value_decimal, row.value_integer, row.value_date) for row in corrections),
        tuple((row.id, row.canonical_key, row.value_text, row.value_decimal,
               row.value_integer, row.value_date) for row in mapped),
        tuple((row.id, row.raw_value, row.normalized_value, row.review_status)
              for row in staging),
    )


@pytest.mark.asyncio
async def test_validation_is_snapshot_only_decimal_exact_idempotent_and_side_effect_free(
    async_db_session: AsyncSession,
):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    snapshot = await make_snapshot(async_db_session, user, item)
    await async_db_session.run_sync(lambda sync: add_employee(sync, user.organization_id))
    before = await async_db_session.run_sync(relevant_counts)
    before_inputs = await async_db_session.run_sync(
        lambda sync: review_input_state(sync, item.id, snapshot.id)
    )
    service = PayrollValidationService(async_db_session)
    first = await service.validate_snapshot(user, item.id, snapshot.id)
    second = await service.validate_snapshot(user, item.id, snapshot.id)
    after = await async_db_session.run_sync(relevant_counts)
    after_inputs = await async_db_session.run_sync(
        lambda sync: review_input_state(sync, item.id, snapshot.id)
    )

    assert first.id == second.id
    assert first.result_checksum == second.result_checksum
    assert first.readiness == PayrollValidationReadiness.READY_FOR_FUTURE_APPROVAL
    net = next(row for row in first.results if row.validation_code == "NET_PAY_RECONCILIATION")
    assert net.severity == PayrollValidationSeverity.INFO
    assert (net.expected_value, net.actual_value) == ("74400.00", "74400.00")
    assert next(row for row in first.results if row.validation_code == "TAX_RECONCILIATION").details == {
        "applicability": "NOT_APPLICABLE"
    }
    assert not any(row.validation_code == "EXISTING_PAYROLL_PERIOD" for row in first.results)
    assert before == after
    assert before_inputs == after_inputs

    newer_ruleset = await service.validate_snapshot(
        user, item.id, snapshot.id, ruleset_version=2,
    )
    assert newer_ruleset.id != first.id
    assert newer_ruleset.validation_version == 2

    review = await PayrollReviewService(async_db_session).get(user, item.id)
    rows = await mapped_by_source(async_db_session, user, item.id)
    review = await PayrollReviewService(async_db_session).correct(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version, value="74400.01",
            reason="Create a changed immutable snapshot",
        ),
    )
    changed_snapshot = await PayrollReviewService(async_db_session).finalize(
        user, item.id,
        PayrollReviewFinalizeRequest(expected_review_version=review.version),
    )
    changed_run = await service.validate_snapshot(user, item.id, changed_snapshot.id)
    assert changed_snapshot.id != snapshot.id
    assert changed_run.id not in {first.id, newer_ruleset.id}
    assert changed_run.validation_version == 1


@pytest.mark.asyncio
async def test_validation_errors_identity_period_and_net_pay_without_cross_tenant_disclosure(
    async_db_session: AsyncSession,
):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    snapshot = await make_snapshot(async_db_session, user, item, net="74399.99", month="13", year="0")
    outsider, _, _ = await async_db_session.run_sync(seed_review_import)
    await async_db_session.run_sync(lambda sync: add_employee(sync, outsider.organization_id))
    result = await PayrollValidationService(async_db_session).validate_snapshot(
        user, item.id, snapshot.id,
    )
    assert result.readiness == PayrollValidationReadiness.NOT_READY
    by_code = {row.validation_code: row for row in result.results}
    assert by_code["NET_PAY_RECONCILIATION"].severity == PayrollValidationSeverity.ERROR
    assert by_code["PERIOD_VALIDITY"].severity == PayrollValidationSeverity.BLOCKING
    assert by_code["EMPLOYEE_IDENTITY"].severity == PayrollValidationSeverity.BLOCKING
    assert by_code["EMPLOYEE_IDENTITY"].actual_value == "0"


@pytest.mark.asyncio
async def test_existing_current_payroll_warns_without_creating_revision(
    async_db_session: AsyncSession,
):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    snapshot = await make_snapshot(async_db_session, user, item)

    def seed_payroll(sync):
        employee = add_employee(sync, user.organization_id)
        payroll = Payroll(
            id=uuid4(), organization_id=user.organization_id, employee_id=employee.id,
            period_year=2026, period_month=9,
        )
        sync.add(payroll)
        sync.flush()
        sync.add(PayrollVersion(
            id=uuid4(), payroll_id=payroll.id, revision_no=1,
            status=PayrollVersionStatus.ACTIVE, source_type=PayrollSourceType.MANUAL,
            calculation_mode=CalculationMode.IMPORTED, is_current=True,
        ))
        sync.flush()
        return payroll.id

    payroll_id = await async_db_session.run_sync(seed_payroll)
    before_versions = await async_db_session.scalar(
        select(func.count()).select_from(PayrollVersion)
    )
    result = await PayrollValidationService(async_db_session).validate_snapshot(user, item.id, snapshot.id)
    warning = next(row for row in result.results if row.validation_code == "EXISTING_PAYROLL_PERIOD")
    assert warning.severity == PayrollValidationSeverity.WARNING
    assert warning.details["existing_payroll_id"] == str(payroll_id)
    assert await async_db_session.scalar(
        select(func.count()).select_from(PayrollVersion)
    ) == before_versions


@pytest.mark.asyncio
async def test_completed_run_and_results_are_database_immutable(async_db_session: AsyncSession):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    snapshot = await make_snapshot(async_db_session, user, item)
    run = await PayrollValidationService(async_db_session).validate_snapshot(user, item.id, snapshot.id)
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="completed payroll validation data is immutable"):
        await async_db_session.execute(update(PayrollImportValidationRun).where(
            PayrollImportValidationRun.id == run.id,
        ).values(info_count=99))
    await nested.rollback()

    result_id = run.results[0].id
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="payroll validation results are immutable"):
        await async_db_session.execute(update(PayrollImportValidationResult).where(
            PayrollImportValidationResult.id == result_id,
        ).values(message="tampered"))
    await nested.rollback()


@pytest.mark.asyncio
async def test_validation_api_rbac_and_tenant_isolation(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    owner = users[UserRoleType.PAYROLL_ADMIN]
    snapshot = await make_snapshot(async_db_session, owner, item)
    headers = {role: bearer(user) for role, user in users.items()}
    route = f"/api/v1/payroll-imports/{item.id}/review/snapshots/{snapshot.id}/validate"
    assert (await api_client.post(route, headers=headers[UserRoleType.AUDITOR])).status_code == 403
    for role in (UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.post(route, headers=headers[role])).status_code == 403
    created = await api_client.post(route, headers=headers[UserRoleType.HR_ADMIN])
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN, UserRoleType.AUDITOR):
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{item.id}/validations",
            headers=headers[role],
        )).status_code == 200
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{item.id}/validations/{run_id}",
            headers=headers[role],
        )).status_code == 200
    outsider, other_item = await async_db_session.run_sync(seed_users_and_import)
    other = outsider[UserRoleType.PAYROLL_ADMIN]
    assert (await api_client.get(
        f"/api/v1/payroll-imports/{item.id}/validations/{run_id}", headers=bearer(other),
    )).status_code == 404
    assert other_item.id != item.id
