"""Refresh-cookie, rotation, revocation, replay, and throttling tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import UserRoleType
from app.models.refresh_session import RefreshSession
from app.models.user import User
from app.seeds.demo_payroll_seed import DEMO_USER_EMAILS
from app.services.auth.authentication import AuthenticationService
from app.services.auth.login_throttle import login_throttle
from app.services.auth.refresh_sessions import RefreshSessionService

settings = get_settings()
assert settings.demo_auth_password is not None
PASSWORD = settings.demo_auth_password.get_secret_value()
EMAIL = DEMO_USER_EMAILS[UserRoleType.EMPLOYEE]


@pytest.fixture(autouse=True)
def reset_login_throttle() -> None:
    login_throttle.clear()
    yield
    login_throttle.clear()


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD):
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


def cookie_header(token: str) -> dict[str, str]:
    return {"Cookie": f"{settings.auth_refresh_cookie_name}={token}"}


class TestLoginAndCookiePolicy:
    async def test_correct_login_issues_http_only_cookie_and_safe_json(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        response = await login(api_client)

        assert response.status_code == 200
        assert set(response.json()) == {"access_token", "token_type", "expires_in"}
        cookie = response.headers["set-cookie"]
        assert f"{settings.auth_refresh_cookie_name}=" in cookie
        assert "HttpOnly" in cookie
        assert f"Path={settings.auth_cookie_path}" in cookie
        assert f"SameSite={settings.auth_cookie_samesite}" in cookie
        assert ("Secure" in cookie) is settings.auth_cookie_secure

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            (EMAIL, "incorrect-password"),
            ("unknown-account@demo.local", "incorrect-password"),
        ],
    )
    async def test_invalid_logins_share_the_same_safe_response(
        self,
        api_client: AsyncClient,
        seeded_async_session: AsyncSession,
        email: str,
        password: str,
    ) -> None:
        response = await login(api_client, email, password)

        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}
        assert settings.auth_refresh_cookie_name not in response.cookies

    async def test_inactive_user_cannot_login(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        def deactivate(session: Session) -> None:
            user = session.execute(select(User).where(User.email == EMAIL)).scalar_one()
            user.is_active = False
            session.flush()

        await seeded_async_session.run_sync(deactivate)
        response = await login(api_client)

        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}

    async def test_repeated_failures_are_temporarily_throttled_without_account_leak(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        email = f"rate-limit-{uuid4().hex}@demo.local"
        for _ in range(settings.login_rate_limit_attempts):
            response = await login(api_client, email, "incorrect-password")
            assert response.status_code == 401

        response = await login(api_client, email, "incorrect-password")
        assert response.status_code == 429
        assert response.headers["retry-after"] == str(
            settings.login_rate_limit_cooldown_seconds
        )

    async def test_cookie_mutating_endpoint_rejects_untrusted_browser_origin(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        response = await api_client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"email": EMAIL, "password": PASSWORD},
        )

        assert response.status_code == 403
        assert settings.auth_refresh_cookie_name not in response.cookies

    async def test_cors_credentials_are_limited_to_configured_origin(
        self, api_client: AsyncClient
    ) -> None:
        origin = settings.allowed_cors_origins[0]
        response = await api_client.options(
            "/api/v1/auth/refresh",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"


class TestRefreshLifecycle:
    async def test_refresh_requires_cookie_and_ignores_legacy_json_body(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "legacy-value"}
        )

        assert response.status_code == 401

    async def test_rotated_token_reuse_revokes_the_replacement_family(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        response = await login(api_client)
        token_a = api_client.cookies.get(settings.auth_refresh_cookie_name)
        assert response.status_code == 200 and token_a is not None

        response = await api_client.post("/api/v1/auth/refresh")
        token_b = api_client.cookies.get(settings.auth_refresh_cookie_name)
        assert response.status_code == 200 and token_b is not None
        assert token_b != token_a

        replay = await api_client.post(
            "/api/v1/auth/refresh", headers=cookie_header(token_a)
        )
        assert replay.status_code == 401

        replacement = await api_client.post(
            "/api/v1/auth/refresh", headers=cookie_header(token_b)
        )
        assert replacement.status_code == 401

        def inspect(session: Session) -> list[RefreshSession]:
            hashes = {
                RefreshSessionService.token_hash(token_a),
                RefreshSessionService.token_hash(token_b),
            }
            return list(
                session.execute(
                    select(RefreshSession).where(RefreshSession.token_hash.in_(hashes))
                )
                .scalars()
                .all()
            )

        sessions = await seeded_async_session.run_sync(inspect)
        assert len(sessions) == 2
        assert len({item.family_id for item in sessions}) == 1
        assert all(item.revoked_at is not None for item in sessions)
        assert all(item.revocation_reason == "REUSE_DETECTED" for item in sessions)
        assert all(token_a not in item.token_hash for item in sessions)
        assert all(token_b not in item.token_hash for item in sessions)

    @pytest.mark.parametrize("malformed", ["garbage", "a.b.c"])
    async def test_malformed_refresh_cookie_is_rejected(
        self, api_client: AsyncClient, malformed: str
    ) -> None:
        response = await api_client.post(
            "/api/v1/auth/refresh", headers=cookie_header(malformed)
        )

        assert response.status_code == 401

    async def test_expired_refresh_cookie_is_rejected(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        authentication = AuthenticationService()

        def create_expired(session: Session) -> str:
            user = authentication.authenticate_user(session, EMAIL, PASSWORD)
            assert user is not None
            token = authentication.create_refresh_token(
                user, expires_delta=timedelta(seconds=-1)
            )
            now = datetime.now(timezone.utc)
            session.add(
                RefreshSession(
                    user_id=user.id,
                    organization_id=user.organization_id,
                    family_id=uuid4(),
                    token_hash=RefreshSessionService.token_hash(token),
                    created_at=now - timedelta(days=1),
                    expires_at=now - timedelta(seconds=1),
                )
            )
            session.flush()
            return token

        token = await seeded_async_session.run_sync(create_expired)
        response = await api_client.post(
            "/api/v1/auth/refresh", headers=cookie_header(token)
        )

        assert response.status_code == 401

    async def test_revoked_refresh_cookie_is_rejected(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        await login(api_client)
        token = api_client.cookies.get(settings.auth_refresh_cookie_name)
        assert token is not None
        service = RefreshSessionService()
        await seeded_async_session.run_sync(service.revoke_session, token)

        response = await api_client.post(
            "/api/v1/auth/refresh", headers=cookie_header(token)
        )

        assert response.status_code == 401

    async def test_inactive_user_refresh_revokes_family(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        await login(api_client)
        token = api_client.cookies.get(settings.auth_refresh_cookie_name)
        assert token is not None

        def deactivate(session: Session) -> None:
            user = session.execute(select(User).where(User.email == EMAIL)).scalar_one()
            user.is_active = False
            session.flush()

        await seeded_async_session.run_sync(deactivate)
        response = await api_client.post("/api/v1/auth/refresh")

        assert response.status_code == 401

    async def test_refresh_loads_current_roles_from_database(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        await login(api_client)

        def change_role(session: Session) -> None:
            user = session.execute(select(User).where(User.email == EMAIL)).scalar_one()
            assert len(user.roles) == 1
            user.roles[0].role = UserRoleType.AUDITOR
            session.flush()

        await seeded_async_session.run_sync(change_role)
        refreshed = await api_client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200
        me = await api_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
        )

        assert me.status_code == 200
        assert me.json()["roles"] == [UserRoleType.AUDITOR]

    async def test_deleted_user_refresh_is_rejected(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        await login(api_client)

        def delete_user(session: Session) -> None:
            user = session.execute(select(User).where(User.email == EMAIL)).scalar_one()
            session.delete(user)
            session.flush()

        await seeded_async_session.run_sync(delete_user)
        response = await api_client.post("/api/v1/auth/refresh")

        assert response.status_code == 401


class TestLogout:
    async def test_logout_revokes_session_clears_cookie_and_prevents_restore(
        self, api_client: AsyncClient, seeded_async_session: AsyncSession
    ) -> None:
        await login(api_client)
        token = api_client.cookies.get(settings.auth_refresh_cookie_name)
        assert token is not None

        response = await api_client.post("/api/v1/auth/logout")
        assert response.status_code == 204
        cookie = response.headers["set-cookie"]
        assert f'{settings.auth_refresh_cookie_name}="";' in cookie
        assert "Max-Age=0" in cookie
        assert "HttpOnly" in cookie

        refresh = await api_client.post(
            "/api/v1/auth/refresh", headers=cookie_header(token)
        )
        assert refresh.status_code == 401

    async def test_logout_is_safe_without_a_valid_cookie(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.post(
            "/api/v1/auth/logout", headers=cookie_header("malformed")
        )

        assert response.status_code == 204
