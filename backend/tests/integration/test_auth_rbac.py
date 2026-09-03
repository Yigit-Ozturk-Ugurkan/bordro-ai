"""End-to-end authentication, RBAC, and organization-isolation tests."""

import uuid
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.employee import Employee
from app.models.enums import EmployeeStatus, UserRoleType
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.seeds.demo_payroll_seed import (
    DEMO_EMPLOYEE_NO,
    DEMO_USER_EMAILS,
)
from app.services.auth.authentication import (
    AuthenticatedUser,
    AuthenticationService,
)

settings = get_settings()
assert settings.demo_auth_password is not None


async def login_as(client: AsyncClient, role: UserRoleType) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": DEMO_USER_EMAILS[role],
            "password": settings.demo_auth_password.get_secret_value(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture()
async def role_tokens(
    api_client: AsyncClient, seeded_async_session: AsyncSession
) -> dict[UserRoleType, dict[str, str]]:
    return {
        role: await login_as(api_client, role)
        for role in DEMO_USER_EMAILS
    }


@pytest_asyncio.fixture()
async def same_org_other_employee_id(
    seeded_async_session: AsyncSession,
) -> UUID:
    def create(session: Session) -> UUID:
        demo_employee = session.execute(
            select(Employee).where(Employee.employee_no == DEMO_EMPLOYEE_NO)
        ).scalar_one()
        employee = Employee(
            id=uuid4(),
            organization_id=demo_employee.organization_id,
            employee_no=f"SAME-{uuid4().hex[:8]}",
            first_name="Other",
            last_name="Employee",
            hire_date=date(2026, 1, 1),
            status=EmployeeStatus.ACTIVE,
        )
        session.add(employee)
        session.flush()
        return employee.id

    return await seeded_async_session.run_sync(create)


@pytest_asyncio.fixture()
async def other_org_employee_id(
    seeded_async_session: AsyncSession,
) -> UUID:
    def create(session: Session) -> UUID:
        organization = Organization(
            id=uuid4(),
            name="Other Fictitious Company",
            code=f"OTHER-{uuid4().hex[:8]}",
            timezone="Europe/Istanbul",
            is_active=True,
        )
        employee = Employee(
            id=uuid4(),
            organization_id=organization.id,
            employee_no=f"OTHER-{uuid4().hex[:8]}",
            first_name="Cross",
            last_name="Tenant",
            hire_date=date(2026, 1, 1),
            status=EmployeeStatus.ACTIVE,
        )
        session.add_all([organization, employee])
        session.flush()
        return employee.id

    return await seeded_async_session.run_sync(create)


class TestAuthenticationAPI:
    async def test_login_returns_access_and_refresh_tokens(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        tokens = await login_as(api_client, UserRoleType.EMPLOYEE)

        assert tokens["token_type"] == "bearer"
        assert tokens["access_token"] != tokens["refresh_token"]
        assert tokens["expires_in"] == settings.access_token_expire_minutes * 60

    async def test_login_rejects_bad_password_without_account_leak(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        response = await api_client.post(
            "/api/v1/auth/login",
            json={
                "email": DEMO_USER_EMAILS[UserRoleType.EMPLOYEE],
                "password": "incorrect-password",
            },
        )

        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}

    async def test_login_rejects_cross_tenant_email_ambiguity(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        other_org_employee_id: UUID,
    ) -> None:
        def create_duplicate(session: Session) -> None:
            employee = session.get(Employee, other_org_employee_id)
            assert employee is not None
            user = User(
                id=uuid4(),
                organization_id=employee.organization_id,
                email=DEMO_USER_EMAILS[UserRoleType.EMPLOYEE],
                password_hash=AuthenticationService.hash_password(
                    settings.demo_auth_password.get_secret_value()
                ),
                is_active=True,
            )
            session.add(user)
            session.flush()

        await seeded_async_session.run_sync(create_duplicate)
        response = await api_client.post(
            "/api/v1/auth/login",
            json={
                "email": DEMO_USER_EMAILS[UserRoleType.EMPLOYEE],
                "password": settings.demo_auth_password.get_secret_value(),
            },
        )

        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}

    async def test_current_user_has_db_roles_and_linked_employee_only(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        role_tokens: dict[UserRoleType, dict[str, str]],
        demo_employee_id: UUID,
    ) -> None:
        response = await api_client.get(
            "/api/v1/auth/me",
            headers=bearer(role_tokens[UserRoleType.EMPLOYEE]["access_token"]),
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"id", "organization_id", "roles", "employee_id"}
        assert body["roles"] == [UserRoleType.EMPLOYEE]
        assert body["employee_id"] == str(demo_employee_id)
        assert "password_hash" not in body

    async def test_refresh_rotates_both_tokens(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
    ) -> None:
        original = await login_as(api_client, UserRoleType.EMPLOYEE)
        response = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original["refresh_token"]},
        )

        assert response.status_code == 200
        refreshed = response.json()
        assert refreshed["access_token"] != original["access_token"]
        assert refreshed["refresh_token"] != original["refresh_token"]

    async def test_access_token_cannot_be_used_as_refresh_token(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        tokens = await login_as(api_client, UserRoleType.EMPLOYEE)

        response = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["access_token"]},
        )

        assert response.status_code == 401

    async def test_refresh_token_cannot_access_protected_route(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
    ) -> None:
        tokens = await login_as(api_client, UserRoleType.EMPLOYEE)

        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1",
            headers=bearer(tokens["refresh_token"]),
        )

        assert response.status_code == 401

    @pytest.mark.parametrize("token", ["garbage", "a.b.c"])
    async def test_malformed_token_is_rejected(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
        token: str,
    ) -> None:
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls",
            headers=bearer(token),
        )

        assert response.status_code == 401

    async def test_expired_token_is_rejected(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
    ) -> None:
        tokens = await login_as(api_client, UserRoleType.EMPLOYEE)
        service = AuthenticationService()
        claims = service.decode_token(tokens["access_token"], "access")

        def load(session: Session) -> AuthenticatedUser:
            user = service.load_current_user(session, claims)
            assert user is not None
            return user

        user = await seeded_async_session.run_sync(load)
        expired = service.create_access_token(
            user, expires_delta=timedelta(seconds=-1)
        )
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls",
            headers=bearer(expired),
        )

        assert response.status_code == 401

    async def test_unknown_token_subject_is_rejected(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
    ) -> None:
        principal = AuthenticatedUser(
            id=uuid4(),
            organization_id=uuid4(),
            roles=frozenset({UserRoleType.EMPLOYEE}),
            employee_id=demo_employee_id,
        )
        token = AuthenticationService().create_access_token(principal)

        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls",
            headers=bearer(token),
        )

        assert response.status_code == 401

    async def test_inactive_user_token_is_rejected(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
    ) -> None:
        tokens = await login_as(api_client, UserRoleType.EMPLOYEE)

        def deactivate(session: Session) -> None:
            user = session.execute(
                select(User).where(
                    User.email == DEMO_USER_EMAILS[UserRoleType.EMPLOYEE]
                )
            ).scalar_one()
            user.is_active = False
            session.flush()

        await seeded_async_session.run_sync(deactivate)
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 401

    async def test_employee_role_without_link_fails_safely(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
    ) -> None:
        service = AuthenticationService()

        def create(session: Session) -> AuthenticatedUser:
            org_id = session.execute(
                select(Employee.organization_id).where(
                    Employee.employee_no == DEMO_EMPLOYEE_NO
                )
            ).scalar_one()
            user = User(
                id=uuid4(),
                organization_id=org_id,
                email=f"unlinked-{uuid4().hex}@demo.local",
                password_hash=service.hash_password("test-only-password"),
                is_active=True,
            )
            session.add(user)
            session.flush()
            session.add(
                UserRole(id=uuid4(), user_id=user.id, role=UserRoleType.EMPLOYEE)
            )
            session.flush()
            return AuthenticatedUser(
                id=user.id,
                organization_id=org_id,
                roles=frozenset({UserRoleType.EMPLOYEE}),
                employee_id=None,
            )

        principal = await seeded_async_session.run_sync(create)
        response = await api_client.get(
            "/api/v1/me/payrolls",
            headers=bearer(service.create_access_token(principal)),
        )

        assert response.status_code == 403

    async def test_cross_tenant_employee_link_fails_safely(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        other_org_employee_id: UUID,
    ) -> None:
        service = AuthenticationService()

        def create(session: Session) -> AuthenticatedUser:
            demo_org_id = session.execute(
                select(Employee.organization_id).where(
                    Employee.employee_no == DEMO_EMPLOYEE_NO
                )
            ).scalar_one()
            other_employee = session.get(Employee, other_org_employee_id)
            assert other_employee is not None
            user = User(
                id=uuid4(),
                organization_id=demo_org_id,
                email=f"mislinked-{uuid4().hex}@demo.local",
                password_hash=service.hash_password("test-only-password"),
                is_active=True,
            )
            session.add(user)
            session.flush()
            session.add(
                UserRole(id=uuid4(), user_id=user.id, role=UserRoleType.EMPLOYEE)
            )
            other_employee.user_id = user.id
            session.flush()
            return AuthenticatedUser(
                id=user.id,
                organization_id=demo_org_id,
                roles=frozenset({UserRoleType.EMPLOYEE}),
                employee_id=other_employee.id,
                employee_organization_id=other_employee.organization_id,
            )

        principal = await seeded_async_session.run_sync(create)
        response = await api_client.get(
            "/api/v1/me/payrolls",
            headers=bearer(service.create_access_token(principal)),
        )

        assert response.status_code == 403


class TestPayrollRBAC:
    async def test_unauthenticated_payroll_is_401(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
    ) -> None:
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1"
        )

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/me/payrolls",
            "/api/v1/me/payrolls/2026/1",
            "/api/v1/me/payrolls/2026/2/comparison",
            "/api/v1/me/tax-status?year=2026&month=2",
            "/api/v1/me/dashboard/2026/2",
        ],
    )
    async def test_employee_self_service(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        role_tokens: dict[UserRoleType, dict[str, str]],
        path: str,
    ) -> None:
        response = await api_client.get(
            path,
            headers=bearer(role_tokens[UserRoleType.EMPLOYEE]["access_token"]),
        )

        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("resource", ["payrolls/2026/1", "dashboard/2026/1"])
    async def test_employee_cannot_read_another_employee(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        role_tokens: dict[UserRoleType, dict[str, str]],
        same_org_other_employee_id: UUID,
        resource: str,
    ) -> None:
        response = await api_client.get(
            f"/api/v1/employees/{same_org_other_employee_id}/{resource}",
            headers=bearer(role_tokens[UserRoleType.EMPLOYEE]["access_token"]),
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "role", [UserRoleType.HR_ADMIN, UserRoleType.PAYROLL_ADMIN, UserRoleType.AUDITOR]
    )
    async def test_org_roles_can_read_same_org_payroll(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        role_tokens: dict[UserRoleType, dict[str, str]],
        demo_employee_id: UUID,
        role: UserRoleType,
    ) -> None:
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1",
            headers=bearer(role_tokens[role]["access_token"]),
        )

        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("resource", ["payrolls/2026/1", "dashboard/2026/1"])
    @pytest.mark.parametrize(
        "role", [UserRoleType.HR_ADMIN, UserRoleType.PAYROLL_ADMIN, UserRoleType.AUDITOR]
    )
    async def test_org_roles_cannot_read_cross_tenant_data(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        role_tokens: dict[UserRoleType, dict[str, str]],
        other_org_employee_id: UUID,
        role: UserRoleType,
        resource: str,
    ) -> None:
        response = await api_client.get(
            f"/api/v1/employees/{other_org_employee_id}/{resource}",
            headers=bearer(role_tokens[role]["access_token"]),
        )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Not authorized to access this employee"
        }

    async def test_system_admin_is_not_implicitly_global_for_payroll_routes(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        demo_employee_id: UUID,
    ) -> None:
        service = AuthenticationService()

        def create(session: Session) -> AuthenticatedUser:
            org_id = session.execute(
                select(Employee.organization_id).where(
                    Employee.employee_no == DEMO_EMPLOYEE_NO
                )
            ).scalar_one()
            user = User(
                id=uuid4(),
                organization_id=org_id,
                email=f"system-{uuid4().hex}@demo.local",
                password_hash=service.hash_password("test-only-password"),
                is_active=True,
            )
            session.add(user)
            session.flush()
            session.add(
                UserRole(id=uuid4(), user_id=user.id, role=UserRoleType.SYSTEM_ADMIN)
            )
            session.flush()
            return AuthenticatedUser(
                id=user.id,
                organization_id=org_id,
                roles=frozenset({UserRoleType.SYSTEM_ADMIN}),
                employee_id=None,
            )

        principal = await seeded_async_session.run_sync(create)
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1",
            headers=bearer(service.create_access_token(principal)),
        )

        assert response.status_code == 403

    async def test_unknown_employee_remains_404_for_authorized_org_reader(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        role_tokens: dict[UserRoleType, dict[str, str]],
    ) -> None:
        response = await api_client.get(
            f"/api/v1/employees/{uuid.uuid4()}/payrolls",
            headers=bearer(role_tokens[UserRoleType.HR_ADMIN]["access_token"]),
        )

        assert response.status_code == 404
