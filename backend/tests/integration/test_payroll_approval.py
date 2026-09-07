from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidWarningAcknowledgementError,
    PayrollApprovalAlreadyDecidedError,
    PayrollApprovalContextStaleError,
    PayrollApprovalValidationNotCompletedError,
    PayrollApprovalValidationNotReadyError,
    PayrollApprovalWarningsUnacknowledgedError,
    WarningAlreadyAcknowledgedError,
)
from app.models.enums import (
    PayrollApprovalDecision,
    PayrollApprovalStatus,
    PayrollValidationRunStatus,
    PayrollValidationSeverity,
    UserRoleType,
)
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_approval import (
    PayrollImportApproval,
    PayrollImportValidationAcknowledgement,
)
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_import import PayrollImportField, PayrollImportMappedField
from app.models.payroll_review import (
    PayrollImportFieldCorrection,
    PayrollImportReviewSnapshot,
    PayrollImportReviewSnapshotField,
)
from app.models.payroll_validation import (
    PayrollImportValidationResult,
    PayrollImportValidationRun,
)
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.schemas.payroll_import import PayrollReviewCorrectionRequest, PayrollReviewFinalizeRequest
from app.services.imports.payroll_approval_service import PayrollApprovalService
from app.services.imports.payroll_review_service import PayrollReviewService
from app.services.imports.payroll_validation_service import PayrollValidationService
from tests.integration.test_payroll_review import mapped_by_source, seed_review_import
from tests.integration.test_payroll_review_api import bearer, seed_users_and_import
from tests.integration.test_payroll_validation import (
    add_employee,
    make_snapshot,
    review_input_state,
)


def authoritative_counts(sync: Session):
    models = (
        Payroll, PayrollVersion, PayrollEarning, PayrollDeduction, PayrollAbsence,
        TaxCalculationRun, TaxCumulativeRecord,
    )
    return tuple(sync.scalar(select(func.count()).select_from(model)) for model in models)


def immutable_validation_state(sync: Session, run_id):
    run = sync.get(PayrollImportValidationRun, run_id)
    results = sync.scalars(select(PayrollImportValidationResult).where(
        PayrollImportValidationResult.validation_run_id == run_id,
    ).order_by(PayrollImportValidationResult.result_order)).all()
    return (
        run.status, run.snapshot_checksum, run.result_checksum,
        run.info_count, run.warning_count, run.error_count, run.blocking_count,
        tuple((row.id, row.validation_code, row.severity, row.message,
               row.expected_value, row.actual_value, row.details) for row in results),
    )


def immutable_upstream_state(sync: Session, import_id, snapshot_id):
    snapshot_fields = sync.scalars(select(
        PayrollImportReviewSnapshotField,
    ).where(
        PayrollImportReviewSnapshotField.snapshot_id == snapshot_id,
    ).order_by(PayrollImportReviewSnapshotField.id)).all()
    return review_input_state(sync, import_id, snapshot_id), tuple((
        row.id, row.source_import_field_id, row.source_mapped_field_id,
        row.effective_canonical_key, row.section_key, row.value_type,
        row.value_text, row.value_decimal, row.value_integer, row.value_date,
        row.provenance, row.correction_id, row.adapter_fingerprint,
    ) for row in snapshot_fields)


async def ready_run(session, *, warning=False):
    user, item, _ = await session.run_sync(seed_review_import)
    snapshot = await make_snapshot(session, user, item)
    employee = await session.run_sync(lambda sync: add_employee(sync, user.organization_id))
    if warning:
        await session.run_sync(
            lambda sync: add_existing_payroll(sync, user.organization_id, employee.id)
        )
    run = await PayrollValidationService(session).validate_snapshot(user, item.id, snapshot.id)
    return user, item, snapshot, run


def add_existing_payroll(sync: Session, organization_id, employee_id):
    from app.models.enums import CalculationMode, PayrollSourceType, PayrollVersionStatus

    row = Payroll(
        id=uuid4(), organization_id=organization_id, employee_id=employee_id,
        period_year=2026, period_month=9,
    )
    sync.add(row)
    sync.flush()
    sync.add(PayrollVersion(
        id=uuid4(), payroll_id=row.id, revision_no=1,
        status=PayrollVersionStatus.ACTIVE,
        source_type=PayrollSourceType.MANUAL,
        calculation_mode=CalculationMode.IMPORTED, is_current=True,
    ))
    sync.flush()


def add_completed_run_with_bad_result_checksum(
    sync: Session, user, item_id, snapshot, source_result,
):
    now = datetime.now(timezone.utc)
    run = PayrollImportValidationRun(
        id=uuid4(), organization_id=user.organization_id,
        payroll_import_id=item_id, review_snapshot_id=snapshot.id,
        validation_version=99, ruleset_version=99,
        status=PayrollValidationRunStatus.RUNNING,
        snapshot_checksum=snapshot.snapshot_checksum,
        result_checksum=None, started_at=now, completed_at=None,
        created_by_user_id=user.id,
        info_count=int(source_result.severity == PayrollValidationSeverity.INFO),
        warning_count=int(source_result.severity == PayrollValidationSeverity.WARNING),
        error_count=int(source_result.severity == PayrollValidationSeverity.ERROR),
        blocking_count=int(source_result.severity == PayrollValidationSeverity.BLOCKING),
        created_at=now,
    )
    sync.add(run)
    sync.flush()
    sync.add(PayrollImportValidationResult(
        id=uuid4(), organization_id=user.organization_id,
        validation_run_id=run.id, review_snapshot_id=snapshot.id,
        result_order=1, validation_code=source_result.validation_code,
        validation_version=source_result.validation_version,
        category=source_result.category, severity=source_result.severity,
        message=source_result.message, canonical_key=source_result.canonical_key,
        related_snapshot_field_ids=[
            str(value) for value in source_result.related_snapshot_field_ids
        ],
        expected_value=source_result.expected_value,
        actual_value=source_result.actual_value, details=source_result.details,
        blocks_future_approval=source_result.blocks_future_approval,
        created_at=now,
    ))
    sync.flush()
    run.status = PayrollValidationRunStatus.COMPLETED
    run.result_checksum = "0" * 64
    run.completed_at = now
    sync.flush()
    return run.id


@pytest.mark.asyncio
async def test_ready_without_warnings_requires_explicit_human_approval(async_db_session):
    user, item, snapshot, run = await ready_run(async_db_session)
    service = PayrollApprovalService(async_db_session)
    before = await service.current(user, item.id)
    assert before.approval_status == PayrollApprovalStatus.NOT_DECIDED
    approved = await service.approve(user, item.id, run.id, "Reviewed and validated")
    assert approved.approval_status == PayrollApprovalStatus.APPROVED
    assert approved.decision.validation_run_id == run.id
    assert approved.decision.snapshot_id == snapshot.id
    assert approved.decision.snapshot_checksum == snapshot.snapshot_checksum
    assert approved.decision.validation_result_checksum == run.result_checksum
    assert approved.decision.decided_by_user_id == user.id
    with pytest.raises(PayrollApprovalAlreadyDecidedError):
        await service.reject(user, item.id, run.id, "Changed mind")


@pytest.mark.asyncio
async def test_warning_acknowledgement_is_exact_required_and_append_only(async_db_session):
    user, item, snapshot, run = await ready_run(async_db_session, warning=True)
    item_id = item.id
    warning = next(row for row in run.results
                   if row.severity == PayrollValidationSeverity.WARNING)
    info = next(row for row in run.results if row.severity == PayrollValidationSeverity.INFO)
    service = PayrollApprovalService(async_db_session)
    with pytest.raises(PayrollApprovalWarningsUnacknowledgedError):
        await service.approve(user, item_id, run.id, None)
    with pytest.raises(InvalidWarningAcknowledgementError):
        await service.acknowledge_warning(user, item_id, run.id, info.id, None)

    newer_run = await PayrollValidationService(async_db_session).validate_snapshot(
        user, item_id, snapshot.id, ruleset_version=2,
    )
    with pytest.raises(InvalidWarningAcknowledgementError):
        await service.acknowledge_warning(
            user, item_id, newer_run.id, warning.id, "Wrong validation run",
        )
    acknowledged = await service.acknowledge_warning(
        user, item_id, run.id, warning.id, "Existing payroll warning reviewed",
    )
    assert acknowledged.warnings.model_dump() == {
        "total": 1, "acknowledged": 1, "remaining": 0,
    }
    with pytest.raises(WarningAlreadyAcknowledgedError):
        await service.acknowledge_warning(user, item_id, run.id, warning.id, None)
    approved = await service.approve(user, item_id, run.id, None)
    assert approved.decision.acknowledged_warning_result_ids == [warning.id]

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="acknowledgements are immutable"):
        await async_db_session.execute(update(PayrollImportValidationAcknowledgement).where(
            PayrollImportValidationAcknowledgement.validation_result_id == warning.id,
        ).values(note="tampered"))
    await nested.rollback()

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="acknowledgements are immutable"):
        await async_db_session.execute(delete(
            PayrollImportValidationAcknowledgement,
        ).where(
            PayrollImportValidationAcknowledgement.validation_result_id == warning.id,
        ))
    await nested.rollback()


@pytest.mark.asyncio
async def test_error_and_blocking_results_cannot_be_acknowledged(async_db_session):
    service = PayrollApprovalService(async_db_session)

    error_user, error_item, _ = await async_db_session.run_sync(seed_review_import)
    error_item_id = error_item.id
    error_snapshot = await make_snapshot(
        async_db_session, error_user, error_item, net="74399.99",
    )
    await async_db_session.run_sync(
        lambda sync: add_employee(sync, error_user.organization_id)
    )
    error_run = await PayrollValidationService(async_db_session).validate_snapshot(
        error_user, error_item_id, error_snapshot.id,
    )
    error = next(row for row in error_run.results
                 if row.severity == PayrollValidationSeverity.ERROR)
    with pytest.raises(InvalidWarningAcknowledgementError):
        await service.acknowledge_warning(
            error_user, error_item_id, error_run.id, error.id, None,
        )

    blocking_user, blocking_item, _ = await async_db_session.run_sync(seed_review_import)
    blocking_item_id = blocking_item.id
    blocking_snapshot = await make_snapshot(
        async_db_session, blocking_user, blocking_item,
    )
    blocking_run = await PayrollValidationService(async_db_session).validate_snapshot(
        blocking_user, blocking_item_id, blocking_snapshot.id,
    )
    blocking = next(row for row in blocking_run.results
                    if row.severity == PayrollValidationSeverity.BLOCKING)
    with pytest.raises(InvalidWarningAcknowledgementError):
        await service.acknowledge_warning(
            blocking_user, blocking_item_id, blocking_run.id, blocking.id, None,
        )


@pytest.mark.asyncio
async def test_error_blocking_and_incomplete_runs_cannot_be_approved(async_db_session):
    service = PayrollApprovalService(async_db_session)

    error_user, error_item, _ = await async_db_session.run_sync(seed_review_import)
    error_item_id = error_item.id
    error_snapshot = await make_snapshot(async_db_session, error_user, error_item, net="74399.99")
    await async_db_session.run_sync(lambda sync: add_employee(sync, error_user.organization_id))
    error_run = await PayrollValidationService(async_db_session).validate_snapshot(
        error_user, error_item_id, error_snapshot.id,
    )
    with pytest.raises(PayrollApprovalValidationNotReadyError):
        await service.approve(error_user, error_item_id, error_run.id, None)

    blocking_user, blocking_item, _ = await async_db_session.run_sync(seed_review_import)
    blocking_item_id = blocking_item.id
    blocking_snapshot = await make_snapshot(async_db_session, blocking_user, blocking_item)
    blocking_run = await PayrollValidationService(async_db_session).validate_snapshot(
        blocking_user, blocking_item_id, blocking_snapshot.id,
    )
    with pytest.raises(PayrollApprovalValidationNotReadyError):
        await service.approve(blocking_user, blocking_item_id, blocking_run.id, None)

    def incomplete(sync, user, item, snapshot, status, ruleset):
        row = PayrollImportValidationRun(
            id=uuid4(), organization_id=user.organization_id,
            payroll_import_id=item.id, review_snapshot_id=snapshot.id,
            validation_version=ruleset, ruleset_version=ruleset,
            status=status, snapshot_checksum=snapshot.snapshot_checksum,
            result_checksum=None, started_at=datetime.now(timezone.utc),
            completed_at=(datetime.now(timezone.utc)
                          if status == PayrollValidationRunStatus.FAILED else None),
            created_by_user_id=user.id, info_count=0, warning_count=0,
            error_count=0, blocking_count=0,
        )
        sync.add(row)
        sync.flush()
        return row.id

    for status, ruleset in ((PayrollValidationRunStatus.RUNNING, 20),
                            (PayrollValidationRunStatus.FAILED, 21)):
        run_id = await async_db_session.run_sync(
            lambda sync, s=status, r=ruleset: incomplete(
                sync, error_user, error_item, error_snapshot, s, r,
            )
        )
        with pytest.raises(PayrollApprovalValidationNotCompletedError):
            await service.approve(error_user, error_item_id, run_id, None)


@pytest.mark.asyncio
async def test_approval_recomputes_and_verifies_stored_validation_checksum(async_db_session):
    user, item, snapshot, valid_run = await ready_run(async_db_session)
    item_id = item.id
    bad_run_id = await async_db_session.run_sync(
        lambda sync: add_completed_run_with_bad_result_checksum(
            sync, user, item_id, snapshot, valid_run.results[0],
        )
    )
    await async_db_session.commit()

    with pytest.raises(PayrollApprovalContextStaleError):
        await PayrollApprovalService(async_db_session).approve(
            user, item_id, bad_run_id, None,
        )


@pytest.mark.asyncio
async def test_rejection_of_not_ready_is_terminal_and_reason_is_preserved(async_db_session):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    snapshot = await make_snapshot(async_db_session, user, item, net="74399.99")
    run = await PayrollValidationService(async_db_session).validate_snapshot(
        user, item.id, snapshot.id,
    )
    service = PayrollApprovalService(async_db_session)
    rejected = await service.reject(user, item.id, run.id, "Document is unusable")
    assert rejected.approval_status == PayrollApprovalStatus.REJECTED
    assert rejected.decision.decision_reason == "Document is unusable"
    with pytest.raises(PayrollApprovalAlreadyDecidedError):
        await service.approve(user, item.id, run.id, None)
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="approval decisions are immutable"):
        await async_db_session.execute(update(PayrollImportApproval).where(
            PayrollImportApproval.id == rejected.decision.id,
        ).values(decision=PayrollApprovalDecision.APPROVED))
    await nested.rollback()

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="approval decisions are immutable"):
        await async_db_session.execute(delete(PayrollImportApproval).where(
            PayrollImportApproval.id == rejected.decision.id,
        ))
    await nested.rollback()


@pytest.mark.asyncio
async def test_database_uniqueness_prevents_competing_terminal_decisions(async_db_session):
    user, item, snapshot, run = await ready_run(async_db_session)
    item_id = item.id
    approved = await PayrollApprovalService(async_db_session).approve(
        user, item_id, run.id, "First terminal decision",
    )

    duplicate = PayrollImportApproval(
        id=uuid4(), organization_id=user.organization_id,
        payroll_import_id=item_id, review_snapshot_id=snapshot.id,
        validation_run_id=run.id, snapshot_checksum=snapshot.snapshot_checksum,
        validation_result_checksum=run.result_checksum,
        validation_ruleset_version=run.ruleset_version,
        decision=PayrollApprovalDecision.REJECTED,
        decision_reason="Competing terminal decision",
        acknowledged_warning_result_ids=[], approval_checksum="f" * 64,
        decided_by_user_id=user.id, decided_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    nested = await async_db_session.begin_nested()
    with pytest.raises(IntegrityError, match="uq_import_approval_validation_run"):
        async_db_session.add(duplicate)
        await async_db_session.flush()
    await nested.rollback()

    decisions = await async_db_session.scalars(select(PayrollImportApproval).where(
        PayrollImportApproval.validation_run_id == run.id,
    ))
    persisted = list(decisions)
    assert len(persisted) == 1
    assert persisted[0].id == approved.decision.id
    assert persisted[0].decision == PayrollApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_new_snapshot_and_ruleset_do_not_inherit_historical_approval(async_db_session):
    user, item, snapshot, run = await ready_run(async_db_session)
    approval = PayrollApprovalService(async_db_session)
    await approval.approve(user, item.id, run.id, None)

    ruleset_two = await PayrollValidationService(async_db_session).validate_snapshot(
        user, item.id, snapshot.id, ruleset_version=2,
    )
    current = await approval.current(user, item.id)
    assert current.validation_run_id == ruleset_two.id
    assert current.approval_status == PayrollApprovalStatus.NOT_DECIDED

    await approval.approve(user, item.id, ruleset_two.id, None)
    review = await PayrollReviewService(async_db_session).get(user, item.id)
    rows = await mapped_by_source(async_db_session, user, item.id)
    review = await PayrollReviewService(async_db_session).correct(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version, value="74400.01",
            reason="Create second snapshot",
        ),
    )
    snapshot_two = await PayrollReviewService(async_db_session).finalize(
        user, item.id, PayrollReviewFinalizeRequest(expected_review_version=review.version),
    )
    run_two = await PayrollValidationService(async_db_session).validate_snapshot(
        user, item.id, snapshot_two.id,
    )
    current = await approval.current(user, item.id)
    assert current.snapshot_id == snapshot_two.id
    assert current.validation_run_id == run_two.id
    assert current.approval_status == PayrollApprovalStatus.NOT_DECIDED
    history = await approval.history(user, item.id)
    assert history.approval_count == 2
    assert {row.snapshot_id for row in history.approvals} == {snapshot.id}


@pytest.mark.asyncio
async def test_decisions_and_acknowledgements_have_no_authoritative_side_effects(async_db_session):
    user, item, snapshot, run = await ready_run(async_db_session, warning=True)
    warning = next(row for row in run.results
                   if row.severity == PayrollValidationSeverity.WARNING)
    before_counts = await async_db_session.run_sync(authoritative_counts)
    before_review = await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item.id, snapshot.id)
    )
    before_validation = await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    service = PayrollApprovalService(async_db_session)
    await service.acknowledge_warning(user, item.id, run.id, warning.id, None)
    assert before_counts == await async_db_session.run_sync(authoritative_counts)
    assert before_review == await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item.id, snapshot.id)
    )
    assert before_validation == await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    await service.approve(user, item.id, run.id, None)
    assert before_counts == await async_db_session.run_sync(authoritative_counts)
    assert before_review == await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item.id, snapshot.id)
    )
    assert before_validation == await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )

    reject_user, reject_item, reject_snapshot, reject_run = await ready_run(
        async_db_session,
    )
    reject_item_id = reject_item.id
    before_reject_counts = await async_db_session.run_sync(authoritative_counts)
    before_reject_review = await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(
            sync, reject_item_id, reject_snapshot.id,
        )
    )
    before_reject_validation = await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, reject_run.id)
    )
    await service.reject(
        reject_user, reject_item_id, reject_run.id, "Human rejected evidence",
    )
    assert before_reject_counts == await async_db_session.run_sync(authoritative_counts)
    assert before_reject_review == await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(
            sync, reject_item_id, reject_snapshot.id,
        )
    )
    assert before_reject_validation == await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, reject_run.id)
    )


@pytest.mark.asyncio
async def test_approval_api_rbac_actor_validation_and_cross_tenant_isolation(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    owner = users[UserRoleType.PAYROLL_ADMIN]
    item_id = item.id
    snapshot = await make_snapshot(async_db_session, owner, item)
    employee = await async_db_session.run_sync(
        lambda sync: add_employee(sync, owner.organization_id)
    )
    await async_db_session.run_sync(
        lambda sync: add_existing_payroll(sync, owner.organization_id, employee.id)
    )
    run = await PayrollValidationService(async_db_session).validate_snapshot(
        owner, item_id, snapshot.id,
    )
    warning = next(row for row in run.results
                   if row.severity == PayrollValidationSeverity.WARNING)
    headers = {role: bearer(user) for role, user in users.items()}
    current_route = f"/api/v1/payroll-imports/{item_id}/approval"
    history_route = f"/api/v1/payroll-imports/{item_id}/approvals"
    approve_route = f"/api/v1/payroll-imports/{item_id}/validations/{run.id}/approve"
    reject_route = f"/api/v1/payroll-imports/{item_id}/validations/{run.id}/reject"
    acknowledge_route = (
        f"/api/v1/payroll-imports/{item_id}/validations/{run.id}"
        f"/warnings/{warning.id}/acknowledge"
    )
    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN, UserRoleType.AUDITOR):
        assert (await api_client.get(current_route, headers=headers[role])).status_code == 200
        assert (await api_client.get(history_route, headers=headers[role])).status_code == 200
    for role in (UserRoleType.HR_ADMIN, UserRoleType.AUDITOR,
                 UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.post(
            acknowledge_route, headers=headers[role], json={"note": "Denied"},
        )).status_code == 403
        assert (await api_client.post(
            approve_route, headers=headers[role], json={"note": "Denied"},
        )).status_code == 403
        assert (await api_client.post(
            reject_route, headers=headers[role], json={"reason": "Denied"},
        )).status_code == 403
    spoofed_ack = await api_client.post(
        acknowledge_route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"note": "Reviewed", "acknowledged_by_user_id": str(uuid4())},
    )
    assert spoofed_ack.status_code == 422
    acknowledged = await api_client.post(
        acknowledge_route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"note": "Reviewed"},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    history = await api_client.get(
        history_route, headers=headers[UserRoleType.PAYROLL_ADMIN],
    )
    assert history.json()["acknowledgements"][0]["acknowledged_by_user_id"] == str(owner.id)
    approved = await api_client.post(
        approve_route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"note": "Approved", "decided_by_user_id": str(uuid4())},
    )
    assert approved.status_code == 422
    approved = await api_client.post(
        approve_route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"note": "Approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["decision"]["decided_by_user_id"] == str(owner.id)

    outsiders, _ = await async_db_session.run_sync(seed_users_and_import)
    outsider = outsiders[UserRoleType.PAYROLL_ADMIN]
    await async_db_session.commit()
    assert (await api_client.get(current_route, headers=bearer(outsider))).status_code == 404
    assert (await api_client.get(history_route, headers=bearer(outsider))).status_code == 404
    assert (await api_client.post(
        acknowledge_route, headers=bearer(outsider), json={},
    )).status_code == 404
    assert (await api_client.post(
        approve_route, headers=bearer(outsider), json={},
    )).status_code == 404
    assert (await api_client.post(
        reject_route, headers=bearer(outsider), json={"reason": "Denied"},
    )).status_code == 404


@pytest.mark.asyncio
async def test_payroll_admin_rejection_api_requires_reason_and_uses_server_actor(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    owner = users[UserRoleType.PAYROLL_ADMIN]
    item_id = item.id
    snapshot = await make_snapshot(async_db_session, owner, item, net="74399.99")
    await async_db_session.run_sync(lambda sync: add_employee(sync, owner.organization_id))
    run = await PayrollValidationService(async_db_session).validate_snapshot(
        owner, item_id, snapshot.id,
    )
    route = f"/api/v1/payroll-imports/{item_id}/validations/{run.id}/reject"
    headers = bearer(owner)
    assert (await api_client.post(route, headers=headers, json={})).status_code == 422
    assert (await api_client.post(
        route, headers=headers, json={"reason": "   "},
    )).status_code == 422
    spoofed = await api_client.post(
        route, headers=headers,
        json={"reason": "Rejected", "decided_by_user_id": str(uuid4())},
    )
    assert spoofed.status_code == 422

    rejected = await api_client.post(
        route, headers=headers, json={"reason": "  Human rejected evidence  "},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()["decision"]
    assert body["decision"] == "REJECTED"
    assert body["decision_reason"] == "Human rejected evidence"
    assert body["decided_by_user_id"] == str(owner.id)
    assert (await api_client.post(
        route, headers=headers, json={"reason": "Second decision"},
    )).status_code == 409
    approve_route = f"/api/v1/payroll-imports/{item_id}/validations/{run.id}/approve"
    assert (await api_client.post(
        approve_route, headers=headers, json={},
    )).status_code == 409
