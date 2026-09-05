from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus, UserRoleType
from app.models.organization import Organization
from app.models.payroll_import import PayrollImport, PayrollImportDocument, PayrollImportField
from app.models.user import User, UserRole
from app.seeds.demo_payroll_seed import DEMO_USER_EMAILS
from app.services.auth.authentication import AuthenticatedUser, AuthenticationService

settings = get_settings()


async def login_as(client: AsyncClient, role: UserRoleType) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={
        "email": DEMO_USER_EMAILS[role],
        "password": settings.demo_auth_password.get_secret_value(),
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_import(sync: Session):
    user = sync.query(User).filter(User.email == DEMO_USER_EMAILS[UserRoleType.PAYROLL_ADMIN]).one()
    import_id, document_id = uuid4(), uuid4()
    digest = uuid4().hex * 2
    item = PayrollImport(
        id=import_id, organization_id=user.organization_id, uploaded_by_user_id=user.id,
        status=PayrollImportStatus.EXTRACTED, source_type="DOCUMENT_UPLOAD",
        reader_provider="GENERAL_READER", source_document_id=document_id,
        content_sha256=digest, reader_table_count=0, reader_warnings=[], processing_attempt=1,
    )
    document = PayrollImportDocument(
        id=document_id, organization_id=user.organization_id, payroll_import_id=import_id,
        file_id=uuid4(), original_filename="mapped.png", declared_mime_type="image/png",
        detected_mime_type="image/png", size_bytes=10, sha256=digest,
        storage_provider="LOCAL", storage_key=f"api-map/{uuid4().hex}",
    )
    field = PayrollImportField(
        id=uuid4(), organization_id=user.organization_id, payroll_import_id=import_id,
        payroll_import_document_id=document_id, source_field_id="net-pay",
        source_label="Net Ücret", raw_value="4.250,75", normalized_value="4250.75",
        value_type="money", confidence="0.99", page_number=1, extraction_source="rule",
        review_status=PayrollImportFieldReviewStatus.UNREVIEWED,
    )
    sync.add_all([item, document, field]); sync.flush()
    return item


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN])
async def test_admins_run_and_read_review_mapping(
    api_client: AsyncClient, seeded_async_session: AsyncSession, role: UserRoleType,
):
    item = await seeded_async_session.run_sync(seed_import)
    import_id = item.id
    headers = await login_as(api_client, role)
    response = await api_client.post(f"/api/v1/payroll-imports/{item.id}/map", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["mapped_count"] == 1
    mapped = await api_client.get(
        f"/api/v1/payroll-imports/{item.id}/mapped-fields", headers=headers
    )
    assert mapped.status_code == 200
    row = mapped.json()["items"][0]
    assert row["canonical_key"] == "net_pay"
    assert row["typed_value"] == {"type": "DECIMAL", "value": "4250.75"}
    assert row["review_status"] == "UNREVIEWED"
    summary = await api_client.get(
        f"/api/v1/payroll-imports/{item.id}/mapping-summary", headers=headers
    )
    assert summary.status_code == 200
    assert summary.json()["missing_count"] == 15


@pytest.mark.asyncio
async def test_auditor_reads_but_cannot_run_mapping(
    api_client: AsyncClient, seeded_async_session: AsyncSession,
):
    item = await seeded_async_session.run_sync(seed_import)
    writer = await login_as(api_client, UserRoleType.PAYROLL_ADMIN)
    auditor = await login_as(api_client, UserRoleType.AUDITOR)
    assert (await api_client.post(
        f"/api/v1/payroll-imports/{item.id}/map", headers=writer
    )).status_code == 200
    assert (await api_client.post(
        f"/api/v1/payroll-imports/{item.id}/map", headers=auditor
    )).status_code == 403
    assert (await api_client.get(
        f"/api/v1/payroll-imports/{item.id}/mapped-fields", headers=auditor
    )).status_code == 200
    assert (await api_client.get(
        f"/api/v1/payroll-imports/{item.id}/mapping-summary", headers=auditor
    )).status_code == 200


@pytest.mark.asyncio
async def test_employee_system_admin_and_other_tenant_are_blocked(
    api_client: AsyncClient, seeded_async_session: AsyncSession,
):
    item = await seeded_async_session.run_sync(seed_import)
    import_id = item.id
    employee = await login_as(api_client, UserRoleType.EMPLOYEE)

    def make_users(sync: Session):
        demo_org = item.organization_id
        sys_user = User(
            id=uuid4(), organization_id=demo_org, email=f"sys-{uuid4().hex}@test.invalid",
            password_hash="unused", is_active=True,
        )
        other_org = Organization(
            id=uuid4(), name="Mapping Other", code=f"MAP-{uuid4().hex[:8]}",
            timezone="Europe/Istanbul", is_active=True,
        )
        other_user = User(
            id=uuid4(), organization_id=other_org.id,
            email=f"other-{uuid4().hex}@test.invalid", password_hash="unused", is_active=True,
        )
        sync.add_all([sys_user, other_org, other_user]); sync.flush()
        sync.add_all([
            UserRole(id=uuid4(), user_id=sys_user.id, role=UserRoleType.SYSTEM_ADMIN),
            UserRole(id=uuid4(), user_id=other_user.id, role=UserRoleType.HR_ADMIN),
        ]); sync.flush()
        return (
            AuthenticatedUser(id=sys_user.id, organization_id=demo_org,
                              roles=frozenset({UserRoleType.SYSTEM_ADMIN}), employee_id=None),
            AuthenticatedUser(id=other_user.id, organization_id=other_org.id,
                              roles=frozenset({UserRoleType.HR_ADMIN}), employee_id=None),
        )

    system_user, outsider = await seeded_async_session.run_sync(make_users)
    await seeded_async_session.commit()
    auth = AuthenticationService()
    system = {"Authorization": f"Bearer {auth.create_access_token(system_user)}"}
    other = {"Authorization": f"Bearer {auth.create_access_token(outsider)}"}
    for headers in (employee, system):
        assert (await api_client.post(
            f"/api/v1/payroll-imports/{import_id}/map", headers=headers
        )).status_code == 403
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/mapped-fields", headers=headers
        )).status_code == 403
    assert (await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/map", headers=other
    )).status_code == 404
    assert (await api_client.get(
        f"/api/v1/payroll-imports/{import_id}/mapped-fields", headers=other
    )).status_code == 404
    assert (await api_client.get(
        f"/api/v1/payroll-imports/{import_id}/mapping-summary", headers=other
    )).status_code == 404
