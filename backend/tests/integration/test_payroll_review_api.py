from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.enums import UserRoleType
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.services.auth.authentication import AuthenticatedUser, AuthenticationService
from app.services.imports.payroll_adapter_service import PayrollAdapterService
from tests.integration.test_payroll_review import seed_review_import


def bearer(user: AuthenticatedUser) -> dict[str, str]:
    token = AuthenticationService().create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def seed_users_and_import(sync: Session):
    owner, item, _ = seed_review_import(sync)
    sync.add(UserRole(id=uuid4(), user_id=owner.id, role=UserRoleType.PAYROLL_ADMIN))
    users = {UserRoleType.PAYROLL_ADMIN: owner}
    for role in (
        UserRoleType.HR_ADMIN, UserRoleType.AUDITOR,
        UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN,
    ):
        row = User(
            id=uuid4(), organization_id=owner.organization_id,
            email=f"{role.value.casefold()}-{uuid4().hex}@test.invalid",
            password_hash="unused", is_active=True,
        )
        sync.add(row)
        sync.flush()
        sync.add(UserRole(id=uuid4(), user_id=row.id, role=role))
        users[role] = AuthenticatedUser(
            id=row.id, organization_id=row.organization_id,
            roles=frozenset({role}), employee_id=None,
        )
    sync.flush()
    owner = AuthenticatedUser(
        id=owner.id, organization_id=owner.organization_id,
        roles=frozenset({UserRoleType.PAYROLL_ADMIN}), employee_id=None,
    )
    users[UserRoleType.PAYROLL_ADMIN] = owner
    return users, item


@pytest.mark.asyncio
async def test_review_api_rbac_identity_concurrency_and_snapshot_reads(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    import_id = item.id
    await PayrollAdapterService(async_db_session).run(
        users[UserRoleType.PAYROLL_ADMIN], import_id,
    )
    headers = {role: bearer(user) for role, user in users.items()}

    started = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review",
        headers=headers[UserRoleType.PAYROLL_ADMIN],
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["version"] == 1
    assert body["status"] == "READY_FOR_SNAPSHOT"
    mapped_id = next(
        field["adapter"]["mapped_field_id"] for field in body["fields"]
        if field["source"]["external_field_id"] == "source-net_pay"
    )

    assert (await api_client.get(
        f"/api/v1/payroll-imports/{import_id}/review",
        headers=headers[UserRoleType.AUDITOR],
    )).status_code == 200
    for role in (UserRoleType.EMPLOYEE, UserRoleType.SYSTEM_ADMIN):
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/review", headers=headers[role],
        )).status_code == 403
    assert (await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review/fields/{mapped_id}",
        headers=headers[UserRoleType.AUDITOR],
        json={"expected_review_version": 1, "value": "1200.00", "reason": "Denied"},
    )).status_code == 403

    spoofed = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review/fields/{mapped_id}",
        headers=headers[UserRoleType.HR_ADMIN],
        json={
            "expected_review_version": 1, "value": "1200.00", "reason": "Spoofed",
            "organization_id": str(uuid4()), "reviewer_user_id": str(uuid4()),
        },
    )
    assert spoofed.status_code == 422

    corrected = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review/fields/{mapped_id}",
        headers=headers[UserRoleType.HR_ADMIN],
        json={
            "expected_review_version": 1,
            "value": "1200.00",
            "reason": "HR verified the OCR value",
        },
    )
    assert corrected.status_code == 200, corrected.text
    corrected_body = corrected.json()
    field = next(value for value in corrected_body["fields"]
                 if value["source"]["external_field_id"] == "source-net_pay")
    assert field["correction"]["reviewer_user_id"] == str(users[UserRoleType.HR_ADMIN].id)
    assert field["effective"] == {
        "canonical_key": "net_pay", "section_key": "TOTALS",
        "typed_value": {"type": "DECIMAL", "value": "1200.00"},
        "provenance": "REVIEWER_CORRECTION",
    }

    conflict = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review/fields/{mapped_id}",
        headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={
            "expected_review_version": 1,
            "value": "1300.00", "reason": "Stale browser tab",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "REVIEW_VERSION_CONFLICT"

    invalid_key = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review/fields/{mapped_id}",
        headers=headers[UserRoleType.PAYROLL_ADMIN],
        json={
            "expected_review_version": 2, "canonical_key": "made_up",
            "value": "1.00", "reason": "Invalid canonical key",
        },
    )
    assert invalid_key.status_code == 422
    assert invalid_key.json()["code"] == "INVALID_CANONICAL_OVERRIDE"

    finalized = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review/finalize",
        headers=headers[UserRoleType.HR_ADMIN],
        json={"expected_review_version": 2},
    )
    assert finalized.status_code == 200, finalized.text
    snapshot_id = finalized.json()["id"]
    for role in (UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN, UserRoleType.AUDITOR):
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/review/snapshots",
            headers=headers[role],
        )).status_code == 200
        assert (await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/review/snapshots/{snapshot_id}",
            headers=headers[role],
        )).status_code == 200


@pytest.mark.asyncio
async def test_review_api_cross_tenant_ids_are_non_disclosing(
    api_client: AsyncClient, async_db_session: AsyncSession,
):
    users, item = await async_db_session.run_sync(seed_users_and_import)
    import_id = item.id
    owner = users[UserRoleType.PAYROLL_ADMIN]
    await PayrollAdapterService(async_db_session).run(owner, import_id)
    started = await api_client.post(
        f"/api/v1/payroll-imports/{import_id}/review", headers=bearer(owner),
    )
    mapped_id = started.json()["fields"][0]["adapter"]["mapped_field_id"]

    def outsider(sync: Session) -> AuthenticatedUser:
        organization = Organization(
            id=uuid4(), name="Review Outsider", code=f"OUT-{uuid4().hex[:8]}",
            timezone="Europe/Istanbul", is_active=True,
        )
        row = User(
            id=uuid4(), organization_id=organization.id,
            email=f"outsider-{uuid4().hex}@test.invalid", password_hash="unused", is_active=True,
        )
        sync.add_all([organization, row])
        sync.flush()
        sync.add(UserRole(id=uuid4(), user_id=row.id, role=UserRoleType.PAYROLL_ADMIN))
        sync.flush()
        return AuthenticatedUser(
            id=row.id, organization_id=organization.id,
            roles=frozenset({UserRoleType.PAYROLL_ADMIN}), employee_id=None,
        )

    other = await async_db_session.run_sync(outsider)
    await async_db_session.commit()
    other_headers = bearer(other)
    requests = [
        await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/review", headers=other_headers,
        ),
        await api_client.post(
            f"/api/v1/payroll-imports/{import_id}/review/fields/{mapped_id}",
            headers=other_headers,
            json={"expected_review_version": 1, "value": "1.00", "reason": "Denied"},
        ),
        await api_client.post(
            f"/api/v1/payroll-imports/{import_id}/review/finalize",
            headers=other_headers, json={"expected_review_version": 1},
        ),
        await api_client.get(
            f"/api/v1/payroll-imports/{import_id}/review/snapshots", headers=other_headers,
        ),
    ]
    assert [response.status_code for response in requests] == [404, 404, 404, 404]
