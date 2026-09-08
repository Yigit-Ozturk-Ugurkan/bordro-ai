from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import (
    PayrollDetailNotReadyError,
    PayrollDetailStateConflictError,
    PayrollImportNotFoundError,
)
from app.models.enums import (
    PayrollDetailMappingStatus,
    PayrollDetailType,
    PayrollFieldMappingScope,
    UserRoleType,
)
from app.models.organization import Organization
from app.models.payroll import PayrollVersion
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_detail_mapping import (
    PayrollDetailMapping,
    PayrollImportDetailCorrection,
    PayrollImportDetailMaterialization,
    PayrollImportDetailSnapshot,
)
from app.models.payroll_import import (
    PayrollImportTable,
    PayrollImportTableCell,
    PayrollImportTableRow,
)
from app.schemas.payroll_detail_mapping import PayrollDetailCorrectionRequest
from app.models.user import User, UserRole
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.label_normalization import normalize_source_label
from app.services.imports.payroll_approval_service import PayrollApprovalService
from app.services.imports.payroll_detail_mapping_service import PayrollDetailMappingService
from app.services.imports.payroll_materialization_service import PayrollMaterializationService
from app.services.imports.payroll_validation_service import PayrollValidationService
from tests.integration.test_payroll_approval import ready_run
from tests.integration.test_payroll_materialization import seed_additional_review_import
from tests.integration.test_payroll_validation import make_snapshot
from tests.integration.test_payroll_review_api import bearer, seed_users_and_import


DETAIL_ROWS = (
    ("Normal Kazanç", "1.234,56", "1,00"),
    ("Kesinti", "234,56", None),
    ("Ücretsiz İzin", "-100,00", "2,50"),
    ("Açıklama Satırı", None, None),
)


def add_detail_evidence(sync: Session, item, *, bad_amount: bool = False,
                        ambiguous: bool = False, add_mappings: bool = True):
    table = PayrollImportTable(
        id=uuid4(), organization_id=item.organization_id,
        payroll_import_id=item.id, payroll_import_document_id=item.source_document_id,
        source_table_index=0, source_table_id="detail-table", source_label="Details",
        page_numbers=[1], source_columns=[
            {"column_id": "description", "source_label": "Description"},
            {"column_id": "amount", "source_label": "Amount"},
            {"column_id": "quantity", "source_label": "Quantity"},
        ], warnings=[], row_count=len(DETAIL_ROWS), column_count=3,
        source_checksum="a" * 64,
    )
    sync.add(table)
    sync.flush()
    source_rows = []
    for index, (label, amount, quantity) in enumerate(DETAIL_ROWS):
        if bad_amount and index == 1:
            amount = "1.234"
        row = PayrollImportTableRow(
            id=uuid4(), organization_id=item.organization_id, table_id=table.id,
            row_index=index, page_number=1, bbox=None,
            coordinate_space="normalized_xyxy", extraction_source="rule",
        )
        sync.add(row)
        sync.flush()
        for column_index, (column_id, value) in enumerate((
            ("description", label), ("amount", amount), ("quantity", quantity),
        )):
            sync.add(PayrollImportTableCell(
                id=uuid4(), organization_id=item.organization_id, row_id=row.id,
                column_index=column_index, source_column_id=column_id,
                column_label=column_id.title(), raw_value=value, value_type="text",
                confidence=Decimal("0.99"), bbox=None,
                coordinate_space="normalized_xyxy", extraction_source="rule",
            ))
        source_rows.append(row)
    item.reader_table_count = 1

    definitions = (
        ("Normal Kazanç", PayrollDetailType.EARNING, "BASE", "Base salary", "REGULAR",
         {"sgk_subject_amount": "1234.56", "income_tax_subject_amount": "1234.56",
          "stamp_tax_subject_amount": "1234.56"}),
        ("Kesinti", PayrollDetailType.DEDUCTION, "OTHER_DED", "Other deduction", "OTHER",
         {"is_statutory": False, "is_sensitive": False}),
        ("Ücretsiz İzin", PayrollDetailType.ABSENCE, "UNPAID", "Unpaid leave", "LEAVE",
         {"is_paid": False}),
    )
    for label, detail_type, code, name, category, target_values in definitions if add_mappings else ():
        mapping = PayrollDetailMapping(
            id=uuid4(), organization_id=item.organization_id,
            scope=PayrollFieldMappingScope.ORGANIZATION,
            source_label_normalized=normalize_source_label(label),
            label_column_id="description", amount_column_id="amount",
            quantity_column_id=("quantity" if detail_type != PayrollDetailType.DEDUCTION else None),
            rate_column_id=None, detail_type=detail_type, canonical_code=code,
            canonical_name=name, category=category, target_values=target_values,
            priority=10, version=1, is_active=True,
        )
        sync.add(mapping)
        if ambiguous and detail_type == PayrollDetailType.EARNING:
            sync.add(PayrollDetailMapping(
                id=uuid4(), organization_id=item.organization_id,
                scope=PayrollFieldMappingScope.ORGANIZATION,
                source_label_normalized=normalize_source_label(label),
                label_column_id="description", amount_column_id="amount",
                quantity_column_id="quantity", rate_column_id=None,
                detail_type=PayrollDetailType.DEDUCTION, canonical_code="TIE",
                canonical_name="Equal priority", category="OTHER",
                target_values={"is_statutory": False, "is_sensitive": False},
                priority=10, version=1, is_active=True,
            ))
    sync.flush()
    return table, source_rows


def correction_for(row, row_version: int, *, change_first: bool = False):
    detail_type = row.detail_type
    code, name, category = row.canonical_code, row.canonical_name, row.category
    amount = str(row.amount) if row.amount is not None else None
    quantity = str(row.quantity) if row.quantity is not None else None
    rate = str(row.rate) if row.rate is not None else None
    target_values = dict(row.target_values)
    ignored = row.mapping_status == PayrollDetailMappingStatus.UNMAPPED
    if ignored:
        detail_type, code, name, category = PayrollDetailType.UNMAPPED, None, None, None
    if change_first and row.source_row_index == 0:
        detail_type, code, name, category = (
            PayrollDetailType.DEDUCTION, "REVIEWED_DED", "Reviewed deduction", "OTHER"
        )
        amount, quantity = "1200.01", None
        target_values = {"is_statutory": False, "is_sensitive": True}
    return PayrollDetailCorrectionRequest(
        expected_row_version=row_version,
        expected_source_checksum=row.source_checksum,
        detail_type=detail_type, canonical_code=code, canonical_name=name,
        category=category, amount=amount, quantity=quantity, rate=rate,
        target_values=target_values, ignored=ignored, reason="Human verified source row",
    )


async def review_all(service, user, item_id, mapped, *, change_first=False):
    review = await service.review(user, item_id)
    for row in mapped.items:
        await service.correct(
            user, item_id, row.id,
            correction_for(row, review.row_version, change_first=change_first),
        )
        review = await service.review(user, item_id)
    return review


@pytest.mark.asyncio
async def test_mapping_review_approval_materializes_exact_details_idempotently(
    async_db_session: AsyncSession,
):
    user, item, scalar_snapshot, run = await ready_run(async_db_session)
    table, source_rows = await async_db_session.run_sync(
        lambda sync: add_detail_evidence(sync, item)
    )
    raw_before = await async_db_session.run_sync(lambda sync: tuple(
        (cell.id, cell.raw_value) for row in source_rows
        for cell in sync.get(PayrollImportTableRow, row.id).cells
    ))
    service = PayrollDetailMappingService(async_db_session)
    mapped = await service.run(user, item.id)
    assert [row.mapping_status for row in mapped.items] == [
        PayrollDetailMappingStatus.MAPPED,
        PayrollDetailMappingStatus.MAPPED,
        PayrollDetailMappingStatus.MAPPED,
        PayrollDetailMappingStatus.UNMAPPED,
    ]
    assert mapped.items[0].amount == Decimal("1234.56")
    assert mapped.items[2].quantity == Decimal("2.50")

    review = await review_all(service, user, item.id, mapped)
    assert review.status.value == "READY_FOR_SNAPSHOT"
    detail_snapshot = await service.finalize(user, item.id, review.row_version)
    assert detail_snapshot.row_count == 4
    assert detail_snapshot.rows[-1].ignored is True
    assert detail_snapshot.rows[-1].detail_type == PayrollDetailType.UNMAPPED

    approved = await PayrollApprovalService(async_db_session).approve(
        user, item.id, run.id, "Scalar and detail evidence reviewed",
    )
    assert approved.decision.detail_snapshot_id == detail_snapshot.id
    scalar_result = await PayrollMaterializationService(async_db_session).materialize(
        user, item.id, approved.decision.id,
    )
    version = await async_db_session.get(PayrollVersion, scalar_result.payroll_version_id)
    scalar_truth = (
        version.gross_earnings, version.total_earnings, version.total_deductions,
        version.net_pay, version.income_tax, version.employee_sgk, version.stamp_tax,
    )
    result = await service.materialize(user, item.id)
    repeated = await service.materialize(user, item.id)
    assert repeated == result
    assert (result.earning_count, result.deduction_count, result.absence_count) == (1, 1, 1)

    earnings = list(await async_db_session.scalars(select(PayrollEarning).where(
        PayrollEarning.payroll_version_id == version.id,
    )))
    deductions = list(await async_db_session.scalars(select(PayrollDeduction).where(
        PayrollDeduction.payroll_version_id == version.id,
    )))
    absences = list(await async_db_session.scalars(select(PayrollAbsence).where(
        PayrollAbsence.payroll_version_id == version.id,
    )))
    assert earnings[0].amount == Decimal("1234.56")
    assert deductions[0].amount == Decimal("234.56")
    assert absences[0].day_count == Decimal("2.50")
    for row in (*earnings, *deductions, *absences):
        assert row.organization_id == user.organization_id
        assert row.source_import_id == item.id
        assert row.source_table_id == table.id
        assert row.source_row_id in {value.id for value in source_rows}
        assert row.detail_snapshot_row_id is not None
        assert row.detail_materialization_id == result.id
        assert row.payroll_version_id == version.id
    assert scalar_truth == (
        version.gross_earnings, version.total_earnings, version.total_deductions,
        version.net_pay, version.income_tax, version.employee_sgk, version.stamp_tax,
    )
    assert raw_before == await async_db_session.run_sync(lambda sync: tuple(
        (cell.id, cell.raw_value) for row in source_rows
        for cell in sync.get(PayrollImportTableRow, row.id).cells
    ))
    assert await async_db_session.scalar(select(func.count()).select_from(
        PayrollImportDetailMaterialization
    )) == 1

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="materialized payroll detail is immutable"):
        await async_db_session.execute(update(PayrollEarning).where(
            PayrollEarning.id == earnings[0].id,
        ).values(amount=Decimal("999.99")))
    await nested.rollback()
    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="payroll detail review evidence is immutable"):
        await async_db_session.execute(update(PayrollImportDetailSnapshot).where(
            PayrollImportDetailSnapshot.id == detail_snapshot.id,
        ).values(snapshot_checksum="0" * 64))
    await nested.rollback()


@pytest.mark.asyncio
async def test_ambiguous_parse_and_unreviewed_rows_fail_closed(async_db_session):
    user, item, _, _ = await ready_run(async_db_session)
    item_id = item.id
    await async_db_session.run_sync(
        lambda sync: add_detail_evidence(sync, item, bad_amount=True, ambiguous=True)
    )
    service = PayrollDetailMappingService(async_db_session)
    mapped = await service.run(user, item_id)
    assert mapped.items[0].mapping_status == PayrollDetailMappingStatus.AMBIGUOUS
    assert mapped.items[1].mapping_status == PayrollDetailMappingStatus.PARSE_FAILED
    review = await service.review(user, item_id)
    with pytest.raises(PayrollDetailNotReadyError):
        await service.finalize(user, item.id, review.row_version)

    ambiguous = mapped.items[0]
    with pytest.raises(PayrollDetailNotReadyError):
        await service.correct(
            user, item_id, ambiguous.id,
            PayrollDetailCorrectionRequest(
                expected_row_version=review.row_version,
                expected_source_checksum=ambiguous.source_checksum,
                detail_type=PayrollDetailType.EARNING, canonical_code="BASE",
                canonical_name="Base", category="REGULAR", amount="1.234",
                target_values={"sgk_subject_amount": "1", "income_tax_subject_amount": "1",
                               "stamp_tax_subject_amount": "1"},
                reason="Ambiguous number must not be guessed",
            ),
        )
    mapped = await service.mapped(user, item_id)
    review = await service.review(user, item_id)
    for row in mapped.items:
        request = correction_for(row, review.row_version)
        if row.source_row_index == 0:
            request = PayrollDetailCorrectionRequest(
                expected_row_version=review.row_version,
                expected_source_checksum=row.source_checksum,
                detail_type=PayrollDetailType.EARNING, canonical_code="BASE",
                canonical_name="Base", category="REGULAR", amount="1234.56",
                quantity="1.00", target_values={
                    "sgk_subject_amount": "1234.56",
                    "income_tax_subject_amount": "1234.56",
                    "stamp_tax_subject_amount": "1234.56",
                }, reason="Reviewer resolves equal-priority candidates",
            )
        elif row.source_row_index == 1:
            request = PayrollDetailCorrectionRequest(
                expected_row_version=review.row_version,
                expected_source_checksum=row.source_checksum,
                detail_type=PayrollDetailType.DEDUCTION, canonical_code="OTHER_DED",
                canonical_name="Other deduction", category="OTHER", amount="234.56",
                target_values={"is_statutory": False, "is_sensitive": False},
                reason="Reviewer resolves ambiguous source number",
            )
        await service.correct(user, item_id, row.id, request)
        review = await service.review(user, item_id)
    resolved = await service.finalize(user, item_id, review.row_version)
    assert resolved.row_count == 4


@pytest.mark.asyncio
async def test_human_correction_wins_and_stale_source_is_blocked(async_db_session):
    user, item, _, run = await ready_run(async_db_session)
    item_id = item.id
    _, source_rows = await async_db_session.run_sync(lambda sync: add_detail_evidence(sync, item))
    service = PayrollDetailMappingService(async_db_session)
    mapped = await service.run(user, item_id)
    review = await review_all(service, user, item_id, mapped, change_first=True)
    snapshot = await service.finalize(user, item_id, review.row_version)
    first = snapshot.rows[0]
    assert first.detail_type == PayrollDetailType.DEDUCTION
    assert first.canonical_code == "REVIEWED_DED"
    assert first.amount == Decimal("1200.01")

    cell = await async_db_session.scalar(select(PayrollImportTableCell).where(
        PayrollImportTableCell.row_id == source_rows[0].id,
        PayrollImportTableCell.source_column_id == "amount",
    ))
    cell.raw_value = "999,99"
    await async_db_session.flush()
    with pytest.raises(PayrollDetailNotReadyError):
        await PayrollApprovalService(async_db_session).approve(
            user, item_id, run.id, "stale",
        )


@pytest.mark.asyncio
async def test_correction_concurrency_and_database_tenant_ownership(async_db_session):
    user, item, _, _ = await ready_run(async_db_session)
    item_id = item.id
    await async_db_session.run_sync(lambda sync: add_detail_evidence(sync, item))
    service = PayrollDetailMappingService(async_db_session)
    mapped = await service.run(user, item_id)
    review = await service.review(user, item_id)
    request = correction_for(mapped.items[0], review.row_version)
    await service.correct(user, item_id, mapped.items[0].id, request)
    with pytest.raises(PayrollDetailStateConflictError):
        await service.correct(user, item_id, mapped.items[1].id,
                              correction_for(mapped.items[1], review.row_version))

    other_org_id = await async_db_session.run_sync(lambda sync: _other_org(sync))
    outsider = AuthenticatedUser(
        id=user.id, organization_id=other_org_id, roles=frozenset(), employee_id=None,
    )
    with pytest.raises(PayrollImportNotFoundError):
        await service.mapped(outsider, item_id)

    nested = await async_db_session.begin_nested()
    with pytest.raises(IntegrityError):
        async_db_session.add(PayrollImportDetailCorrection(
            id=uuid4(), organization_id=other_org_id, payroll_import_id=item_id,
            mapped_detail_id=mapped.items[1].id,
            source_checksum=mapped.items[1].source_checksum, revision=1,
            detail_type=PayrollDetailType.UNMAPPED, target_values={}, ignored=True,
            reason="cross tenant", reviewed_by_user_id=user.id,
        ))
        await async_db_session.flush()
    await nested.rollback()


@pytest.mark.asyncio
async def test_later_payroll_version_owns_new_details_without_mutating_history(
    async_db_session: AsyncSession,
):
    user, first_import, _, first_run = await ready_run(async_db_session)
    first_id = first_import.id
    await async_db_session.run_sync(lambda sync: add_detail_evidence(sync, first_import))
    detail_service = PayrollDetailMappingService(async_db_session)
    first_mapped = await detail_service.run(user, first_id)
    first_review = await review_all(detail_service, user, first_id, first_mapped)
    await detail_service.finalize(user, first_id, first_review.row_version)
    first_approval = await PayrollApprovalService(async_db_session).approve(
        user, first_id, first_run.id, "first approved revision",
    )
    first_scalar = await PayrollMaterializationService(async_db_session).materialize(
        user, first_id, first_approval.decision.id,
    )
    await detail_service.materialize(user, first_id)
    first_values = await async_db_session.run_sync(lambda sync: tuple(
        (row.id, row.payroll_version_id, row.amount)
        for row in sync.scalars(select(PayrollEarning).where(
            PayrollEarning.payroll_version_id == first_scalar.payroll_version_id,
        ))
    ))

    second_import = await async_db_session.run_sync(
        lambda sync: seed_additional_review_import(sync, user)
    )
    second_id = second_import.id
    scalar_snapshot = await make_snapshot(async_db_session, user, second_import)
    second_run = await PayrollValidationService(async_db_session).validate_snapshot(
        user, second_id, scalar_snapshot.id,
    )
    await async_db_session.run_sync(
        lambda sync: add_detail_evidence(sync, second_import, add_mappings=False)
    )
    second_mapped = await detail_service.run(user, second_id)
    second_review = await review_all(detail_service, user, second_id, second_mapped)
    await detail_service.finalize(user, second_id, second_review.row_version)
    warning = next(value for value in second_run.results if value.severity.value == "WARNING")
    approval_service = PayrollApprovalService(async_db_session)
    await approval_service.acknowledge_warning(
        user, second_id, second_run.id, warning.id, "revision warning reviewed",
    )
    second_approval = await approval_service.approve(
        user, second_id, second_run.id, "second approved revision",
    )
    second_scalar = await PayrollMaterializationService(async_db_session).materialize(
        user, second_id, second_approval.decision.id,
    )
    await detail_service.materialize(user, second_id)

    assert second_scalar.payroll_id == first_scalar.payroll_id
    assert second_scalar.payroll_version_id != first_scalar.payroll_version_id
    assert second_scalar.revision_no == 2
    assert first_values == await async_db_session.run_sync(lambda sync: tuple(
        (row.id, row.payroll_version_id, row.amount)
        for row in sync.scalars(select(PayrollEarning).where(
            PayrollEarning.payroll_version_id == first_scalar.payroll_version_id,
        ))
    ))
    assert await async_db_session.scalar(select(func.count()).select_from(
        PayrollEarning
    ).where(PayrollEarning.payroll_version_id == second_scalar.payroll_version_id)) == 1


@pytest.mark.asyncio
async def test_detail_api_rbac_and_cross_tenant_reads_are_non_disclosing(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    import_id = item.id
    await async_db_session.run_sync(lambda sync: add_detail_evidence(sync, item))
    headers = {role: bearer(user) for role, user in users.items()}

    mapped = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/detail-mapping",
        headers=headers[UserRoleType.PAYROLL_ADMIN],
    )
    assert mapped.status_code == 200, mapped.text
    mapped_body = mapped.json()
    assert mapped_body["count"] == 4
    assert (await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/detail-mapping",
        headers=headers[UserRoleType.HR_ADMIN],
    )).status_code == 403
    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN,
                 UserRoleType.AUDITOR):
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/mapped-details",
            headers=headers[role],
        )).status_code == 200
    for role in (UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/mapped-details",
            headers=headers[role],
        )).status_code == 403

    first = mapped_body["items"][0]
    correction = {
        "expected_row_version": 1,
        "expected_source_checksum": first["source_checksum"],
        "detail_type": "EARNING", "canonical_code": "BASE",
        "canonical_name": "Base salary", "category": "REGULAR",
        "amount": "1234.56", "quantity": "1.00", "rate": None,
        "target_values": {
            "sgk_subject_amount": "1234.56",
            "income_tax_subject_amount": "1234.56",
            "stamp_tax_subject_amount": "1234.56",
        },
        "ignored": False, "reason": "HR verified",
    }
    path = f"/api/v1/payroll-imports/{import_id}/detail-review/rows/{first['id']}"
    assert (await api_client.post(
        path, headers=headers[UserRoleType.AUDITOR], json=correction,
    )).status_code == 403
    reviewed = await api_client.post(
        path, headers=headers[UserRoleType.HR_ADMIN], json=correction,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_by_user_id"] == str(users[UserRoleType.HR_ADMIN].id)

    def outsider(sync):
        organization = Organization(
            id=uuid4(), name="Other tenant", code=f"OTHER-{uuid4().hex[:8]}",
            timezone="Europe/Istanbul", is_active=True,
        )
        row = User(
            id=uuid4(), organization_id=organization.id,
            email=f"outside-{uuid4().hex}@test.invalid",
            password_hash="unused", is_active=True,
        )
        sync.add_all([organization, row])
        sync.flush()
        sync.add(UserRole(id=uuid4(), user_id=row.id, role=UserRoleType.AUDITOR))
        sync.flush()
        return AuthenticatedUser(
            id=row.id, organization_id=organization.id,
            roles=frozenset({UserRoleType.AUDITOR}), employee_id=None,
        )

    other = await async_db_session.run_sync(outsider)
    assert (await api_client.get(
        f"/api/v1/payroll-imports/{import_id}/mapped-details",
        headers=bearer(other),
    )).status_code == 404


def _other_org(sync: Session):
    row = Organization(
        id=uuid4(), name="Other detail tenant", code=f"OTHER-{uuid4().hex[:8]}",
        timezone="Europe/Istanbul", is_active=True,
    )
    sync.add(row)
    sync.flush()
    return row.id
