from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import (
    PayrollMaterializationContextStaleError,
    PayrollMaterializationIntegrityFailedError,
    PayrollMaterializationNotApprovedError,
)
from app.models.enums import (
    PayrollApprovalDecision,
    PayrollImportFieldReviewStatus,
    PayrollImportStatus,
    PayrollSourceType,
    PayrollValidationSeverity,
    PayrollVersionStatus,
    UserRoleType,
)
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_approval import (
    PayrollImportApproval,
    PayrollImportValidationAcknowledgement,
)
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_import import (
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
)
from app.models.payroll_materialization import PayrollImportMaterialization
from app.models.payroll_review import PayrollImportReviewSnapshot
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.schemas.payroll_import import PayrollReviewCorrectionRequest, PayrollReviewFinalizeRequest
from app.services.imports.payroll_approval_service import PayrollApprovalService
from app.services.imports.payroll_materialization_service import (
    PAYROLL_VERSION_FIELD_SPECS,
    PayrollMaterializationService,
)
from app.services.imports.canonical_fields import REQUIRED_CANONICAL_FIELDS
from app.services.imports.payroll_review_service import PayrollReviewService
from app.services.imports.payroll_validation_service import PayrollValidationService
from tests.integration.test_payroll_approval import (
    authoritative_counts,
    immutable_upstream_state,
    immutable_validation_state,
    ready_run,
)
from tests.integration.test_payroll_review import _raw_for, mapped_by_source
from tests.integration.test_payroll_review_api import bearer, seed_users_and_import
from tests.integration.test_payroll_validation import add_employee, make_snapshot


def materialization_count(sync: Session):
    return sync.scalar(select(func.count()).select_from(PayrollImportMaterialization))


def approval_evidence_state(sync: Session, import_id):
    approvals = sync.scalars(select(PayrollImportApproval).where(
        PayrollImportApproval.payroll_import_id == import_id,
    ).order_by(PayrollImportApproval.id)).all()
    acknowledgements = sync.scalars(select(
        PayrollImportValidationAcknowledgement,
    ).where(
        PayrollImportValidationAcknowledgement.payroll_import_id == import_id,
    ).order_by(PayrollImportValidationAcknowledgement.id)).all()
    return (
        tuple((
            row.id, row.review_snapshot_id, row.validation_run_id,
            row.snapshot_checksum, row.validation_result_checksum,
            row.validation_ruleset_version, row.decision,
            row.decision_reason, tuple(row.acknowledged_warning_result_ids),
            row.approval_checksum, row.decided_by_user_id, row.decided_at,
        ) for row in approvals),
        tuple((
            row.id, row.validation_run_id, row.validation_result_id,
            row.acknowledged_by_user_id, row.note, row.acknowledged_at,
        ) for row in acknowledgements),
    )


def seed_additional_review_import(sync: Session, user):
    import_id, document_id = uuid4(), uuid4()
    item = PayrollImport(
        id=import_id, organization_id=user.organization_id,
        uploaded_by_user_id=user.id, status=PayrollImportStatus.REVIEW_REQUIRED,
        source_type="DOCUMENT_UPLOAD", reader_provider="GENERAL_READER",
        source_document_id=document_id, content_sha256=uuid4().hex * 2,
        reader_table_count=0, reader_warnings=[], processing_attempt=1,
    )
    document = PayrollImportDocument(
        id=document_id, organization_id=user.organization_id,
        payroll_import_id=import_id, file_id=uuid4(),
        original_filename="second-review.png",
        declared_mime_type="image/png", detected_mime_type="image/png",
        size_bytes=10, sha256=item.content_sha256, storage_provider="LOCAL",
        storage_key=f"review/{uuid4().hex}",
    )
    sync.add_all([item, document])
    sync.flush()
    for definition in REQUIRED_CANONICAL_FIELDS:
        label = f"Second {definition.canonical_key} {uuid4().hex}"
        field = PayrollImportField(
            id=uuid4(), organization_id=user.organization_id,
            payroll_import_id=import_id, payroll_import_document_id=document_id,
            source_field_id=f"source-{definition.canonical_key}",
            source_label=label, raw_value=_raw_for(definition),
            normalized_value=_raw_for(definition),
            value_type=definition.value_type.value.casefold(),
            confidence=Decimal("0.99"), page_number=1,
            extraction_source="rule",
            review_status=PayrollImportFieldReviewStatus.UNREVIEWED,
        )
        sync.add(field)
        sync.flush()
    sync.flush()
    return item


async def approved_evidence(
    session, *, existing_payroll=False, document_filename=None,
    document_mime_type=None,
):
    user, item, snapshot, run = await ready_run(session, warning=existing_payroll)
    item_id = item.id
    if document_filename is not None or document_mime_type is not None:
        document = await session.scalar(select(PayrollImportDocument).where(
            PayrollImportDocument.payroll_import_id == item_id,
        ))
        if document_filename is not None:
            document.original_filename = document_filename
        if document_mime_type is not None:
            document.declared_mime_type = document_mime_type
            document.detected_mime_type = document_mime_type
        await session.flush()
    approval_service = PayrollApprovalService(session)
    if existing_payroll:
        warning = next(row for row in run.results
                       if row.severity == PayrollValidationSeverity.WARNING)
        await approval_service.acknowledge_warning(
            user, item_id, run.id, warning.id, "Existing revision reviewed",
        )
    approved = await approval_service.approve(user, item_id, run.id, "Approved evidence")
    return user, item_id, snapshot, run, approved.decision


@pytest.mark.asyncio
async def test_new_payroll_materialization_is_exact_idempotent_and_source_immutable(
    async_db_session: AsyncSession,
):
    user, item_id, snapshot, run, approval = await approved_evidence(async_db_session)
    before_counts = await async_db_session.run_sync(authoritative_counts)
    before_materializations = await async_db_session.run_sync(materialization_count)
    before_upstream = await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item_id, snapshot.id)
    )
    before_validation = await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    before_approval = await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, item_id)
    )

    service = PayrollMaterializationService(async_db_session)
    result = await service.materialize(user, item_id, approval.id)
    assert result.revision_no == 1
    assert result.version_status == PayrollVersionStatus.ACTIVE
    assert result.period_year == 2026
    assert result.period_month == 9
    assert result.materialized_by_user_id == user.id

    payroll = await async_db_session.get(Payroll, result.payroll_id)
    version = await async_db_session.get(PayrollVersion, result.payroll_version_id)
    materialization = await async_db_session.get(
        PayrollImportMaterialization, result.id,
    )
    assert payroll.employee_id == result.employee_id
    assert version.payroll_id == payroll.id
    assert version.status == PayrollVersionStatus.ACTIVE
    assert version.is_current is True
    assert version.source_type == PayrollSourceType.DOCUMENT
    assert version.source_type != PayrollSourceType.PDF
    assert version.source_import_id == item_id
    assert version.source_checksum == snapshot.snapshot_checksum
    assert version.rule_set_id is None
    assert materialization.approval_checksum == approval.approval_checksum

    snapshot_values = await async_db_session.run_sync(lambda sync: {
        row.effective_canonical_key: row.value_decimal
        for row in sync.get(PayrollImportReviewSnapshot, snapshot.id).fields
        if row.effective_canonical_key in PAYROLL_VERSION_FIELD_SPECS
    })
    for key, (attribute, _, _, _) in PAYROLL_VERSION_FIELD_SPECS.items():
        assert getattr(version, attribute) == snapshot_values[key]

    after_counts = await async_db_session.run_sync(authoritative_counts)
    assert after_counts[0] == before_counts[0] + 1
    assert after_counts[1] == before_counts[1] + 1
    assert after_counts[2:] == before_counts[2:]
    assert await async_db_session.run_sync(materialization_count) == (
        before_materializations + 1
    )
    assert before_upstream == await async_db_session.run_sync(
        lambda sync: immutable_upstream_state(sync, item_id, snapshot.id)
    )
    assert before_validation == await async_db_session.run_sync(
        lambda sync: immutable_validation_state(sync, run.id)
    )
    assert before_approval == await async_db_session.run_sync(
        lambda sync: approval_evidence_state(sync, item_id)
    )

    repeated = await service.materialize(user, item_id, approval.id)
    assert repeated == result
    assert after_counts == await async_db_session.run_sync(authoritative_counts)
    assert await async_db_session.run_sync(materialization_count) == (
        before_materializations + 1
    )
    current = await service.current(user, item_id)
    assert current.materialized is True
    assert current.materialization == result

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="materialization evidence is immutable"):
        await async_db_session.execute(update(PayrollImportMaterialization).where(
            PayrollImportMaterialization.id == result.id,
        ).values(materialization_version=2))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="materialization evidence is immutable"):
        await async_db_session.execute(delete(PayrollImportMaterialization).where(
            PayrollImportMaterialization.id == result.id,
        ))
    await nested.rollback()


@pytest.mark.parametrize(("filename", "mime_type"), [
    ("payroll.pdf", "application/pdf"),
    ("payroll.jpg", "image/jpeg"),
    ("payroll.png", "image/png"),
])
@pytest.mark.asyncio
async def test_document_format_is_preserved_without_becoming_pdf_source_type(
    async_db_session: AsyncSession, filename: str, mime_type: str,
):
    user, item_id, _, _, approval = await approved_evidence(
        async_db_session,
        document_filename=filename,
        document_mime_type=mime_type,
    )

    result = await PayrollMaterializationService(async_db_session).materialize(
        user, item_id, approval.id,
    )
    version = await async_db_session.get(
        PayrollVersion, result.payroll_version_id,
    )
    document = await async_db_session.scalar(select(PayrollImportDocument).where(
        PayrollImportDocument.payroll_import_id == item_id,
    ))

    assert document.original_filename == filename
    assert document.declared_mime_type == mime_type
    assert document.detected_mime_type == mime_type
    assert version.source_type == PayrollSourceType.DOCUMENT
    assert version.source_type != PayrollSourceType.PDF
    assert version.source_import_id == item_id


@pytest.mark.asyncio
async def test_existing_payroll_gets_new_revision_and_supersedes_active(
    async_db_session: AsyncSession,
):
    user, item_id, _, _, approval = await approved_evidence(
        async_db_session, existing_payroll=True,
    )
    existing = await async_db_session.scalar(select(PayrollVersion).join(
        Payroll, Payroll.id == PayrollVersion.payroll_id,
    ).where(
        Payroll.organization_id == user.organization_id,
        PayrollVersion.is_current.is_(True),
    ))
    payroll_id, version_id = existing.payroll_id, existing.id
    before_counts = await async_db_session.run_sync(authoritative_counts)

    result = await PayrollMaterializationService(async_db_session).materialize(
        user, item_id, approval.id,
    )
    assert result.payroll_id == payroll_id
    assert result.revision_no == 2
    old = await async_db_session.get(PayrollVersion, version_id)
    new = await async_db_session.get(PayrollVersion, result.payroll_version_id)
    assert old.status == PayrollVersionStatus.SUPERSEDED
    assert old.is_current is False
    assert new.status == PayrollVersionStatus.ACTIVE
    assert new.is_current is True
    after_counts = await async_db_session.run_sync(authoritative_counts)
    assert after_counts[0] == before_counts[0]
    assert after_counts[1] == before_counts[1] + 1
    assert after_counts[2:] == before_counts[2:]


@pytest.mark.asyncio
async def test_different_approved_imports_allocate_sequential_revisions(
    async_db_session: AsyncSession,
):
    user, item_id, _, _, first_approval = await approved_evidence(
        async_db_session,
    )
    service = PayrollMaterializationService(async_db_session)
    first = await service.materialize(user, item_id, first_approval.id)

    second_item = await async_db_session.run_sync(
        lambda sync: seed_additional_review_import(sync, user)
    )
    second_import_id = second_item.id
    second_snapshot = await make_snapshot(
        async_db_session, user, second_item,
    )
    second_run = await PayrollValidationService(async_db_session).validate_snapshot(
        user, second_import_id, second_snapshot.id,
    )
    warning = next(row for row in second_run.results
                   if row.severity == PayrollValidationSeverity.WARNING)
    approval_service = PayrollApprovalService(async_db_session)
    await approval_service.acknowledge_warning(
        user, second_import_id, second_run.id, warning.id,
        "Existing authoritative revision reviewed",
    )
    second_approval = await approval_service.approve(
        user, second_import_id, second_run.id, None,
    )
    second = await service.materialize(
        user, second_import_id, second_approval.decision.id,
    )

    assert second.payroll_id == first.payroll_id
    assert (first.revision_no, second.revision_no) == (1, 2)
    versions = list(await async_db_session.scalars(select(PayrollVersion).where(
        PayrollVersion.payroll_id == first.payroll_id,
    ).order_by(PayrollVersion.revision_no)))
    assert [(row.revision_no, row.status, row.is_current) for row in versions] == [
        (1, PayrollVersionStatus.SUPERSEDED, False),
        (2, PayrollVersionStatus.ACTIVE, True),
    ]
    assert len({row.revision_no for row in versions}) == 2
    assert {row.source_import_id for row in versions} == {item_id, second_import_id}


@pytest.mark.asyncio
async def test_no_approval_rejection_and_stale_ruleset_are_denied(
    async_db_session: AsyncSession,
):
    user, item, snapshot, run = await ready_run(async_db_session)
    item_id = item.id
    service = PayrollMaterializationService(async_db_session)
    with pytest.raises(PayrollMaterializationNotApprovedError):
        await service.materialize(user, item_id, uuid4())

    rejected = await PayrollApprovalService(async_db_session).reject(
        user, item_id, run.id, "Rejected evidence",
    )
    with pytest.raises(PayrollMaterializationNotApprovedError):
        await service.materialize(user, item_id, rejected.decision.id)

    fresh_user, fresh_item, fresh_snapshot, fresh_run = await ready_run(async_db_session)
    fresh_item_id = fresh_item.id
    approved = await PayrollApprovalService(async_db_session).approve(
        fresh_user, fresh_item_id, fresh_run.id, None,
    )
    await PayrollValidationService(async_db_session).validate_snapshot(
        fresh_user, fresh_item_id, fresh_snapshot.id, ruleset_version=2,
    )
    with pytest.raises(PayrollMaterializationContextStaleError):
        await service.materialize(
            fresh_user, fresh_item_id, approved.decision.id,
        )


@pytest.mark.asyncio
async def test_new_snapshot_makes_historical_approval_non_materializable(
    async_db_session: AsyncSession,
):
    user, item, snapshot, first_run = await ready_run(async_db_session)
    item_id = item.id
    approval_service = PayrollApprovalService(async_db_session)
    await approval_service.approve(user, item_id, first_run.id, None)
    current_run = await PayrollValidationService(async_db_session).validate_snapshot(
        user, item_id, snapshot.id, ruleset_version=2,
    )
    await approval_service.current(user, item_id)
    approval = await approval_service.approve(
        user, item_id, current_run.id, None,
    )
    review = await PayrollReviewService(async_db_session).get(user, item_id)
    rows = await mapped_by_source(async_db_session, user, item_id)
    review = await PayrollReviewService(async_db_session).correct(
        user, item_id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version, value="74400.01",
            reason="Create newer current snapshot",
        ),
    )
    assert review.complete, review.issues
    await PayrollReviewService(async_db_session).finalize(
        user, item_id,
        PayrollReviewFinalizeRequest(expected_review_version=review.version),
    )
    with pytest.raises(PayrollMaterializationContextStaleError):
        await PayrollMaterializationService(async_db_session).materialize(
            user, item_id, approval.decision.id,
        )
    assert await async_db_session.get(
        PayrollImportApproval, approval.decision.id,
    ) is not None
    assert await async_db_session.scalar(select(func.count()).select_from(
        PayrollImportMaterialization,
    ).where(
        PayrollImportMaterialization.approval_id == approval.decision.id,
    )) == 0


@pytest.mark.asyncio
async def test_corrupted_approval_checksum_fails_closed(async_db_session: AsyncSession):
    user, item, snapshot, run = await ready_run(async_db_session)
    item_id = item.id
    bad_approval = PayrollImportApproval(
        id=uuid4(), organization_id=user.organization_id,
        payroll_import_id=item_id, review_snapshot_id=snapshot.id,
        validation_run_id=run.id, snapshot_checksum=snapshot.snapshot_checksum,
        validation_result_checksum=run.result_checksum,
        validation_ruleset_version=run.ruleset_version,
        decision=PayrollApprovalDecision.APPROVED, decision_reason=None,
        acknowledged_warning_result_ids=[], approval_checksum="0" * 64,
        decided_by_user_id=user.id,
    )
    async_db_session.add(bad_approval)
    await async_db_session.commit()
    before = await async_db_session.run_sync(authoritative_counts)
    with pytest.raises(PayrollMaterializationIntegrityFailedError):
        await PayrollMaterializationService(async_db_session).materialize(
            user, item_id, bad_approval.id,
        )
    assert before == await async_db_session.run_sync(authoritative_counts)


@pytest.mark.asyncio
async def test_materialization_api_rbac_actor_payload_and_tenant_isolation(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    owner = users[UserRoleType.PAYROLL_ADMIN]
    item_id = item.id
    snapshot = await make_snapshot(async_db_session, owner, item)
    await async_db_session.run_sync(lambda sync: add_employee(sync, owner.organization_id))
    run = await PayrollValidationService(async_db_session).validate_snapshot(
        owner, item_id, snapshot.id,
    )
    approval = await PayrollApprovalService(async_db_session).approve(
        owner, item_id, run.id, None,
    )
    approval_id = approval.decision.id
    route = f"/api/v1/payroll-imports/{item_id}/approvals/{approval_id}/materialize"
    state_route = f"/api/v1/payroll-imports/{item_id}/materialization"
    headers = {role: bearer(user) for role, user in users.items()}

    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN, UserRoleType.AUDITOR):
        response = await api_client.get(state_route, headers=headers[role])
        assert response.status_code == 200
        assert response.json()["materialized"] is False
    for role in (UserRoleType.HR_ADMIN, UserRoleType.AUDITOR,
                 UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.post(
            route, headers=headers[role], json={},
        )).status_code == 403
    assert (await api_client.post(
        route, headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={"employee_id": str(uuid4()), "net_pay": "1.00"},
    )).status_code == 422

    response = await api_client.post(
        route, headers=headers[UserRoleType.PAYROLL_ADMIN], json={},
    )
    assert response.status_code == 200, response.text
    assert response.json()["materialized_by_user_id"] == str(owner.id)
    state = await api_client.get(
        state_route, headers=headers[UserRoleType.AUDITOR],
    )
    assert state.status_code == 200
    assert state.json()["materialized"] is True

    outsiders, _ = await async_db_session.run_sync(seed_users_and_import)
    outsider = outsiders[UserRoleType.PAYROLL_ADMIN]
    await async_db_session.commit()
    assert (await api_client.get(
        state_route, headers=bearer(outsider),
    )).status_code == 404
    assert (await api_client.post(
        route, headers=bearer(outsider), json={},
    )).status_code == 404
