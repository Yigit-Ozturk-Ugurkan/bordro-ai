"""Focused password, JWT, and future-write policy tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.enums import UserRoleType
from app.services.auth.authentication import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationService,
)
from app.services.auth.authorization import PayrollAuthorizationPolicy


@pytest.fixture()
def principal() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        organization_id=uuid4(),
        roles=frozenset({UserRoleType.EMPLOYEE}),
        employee_id=uuid4(),
    )


def test_argon2id_password_hash_is_not_plaintext_and_verifies() -> None:
    password = "correct horse battery staple"
    password_hash = AuthenticationService.hash_password(password)

    assert password_hash != password
    assert password_hash.startswith("$argon2id$")
    assert AuthenticationService.verify_password(password, password_hash)
    assert not AuthenticationService.verify_password("incorrect", password_hash)


def test_password_hashes_are_independently_salted() -> None:
    password = "same password"

    first = AuthenticationService.hash_password(password)
    second = AuthenticationService.hash_password(password)

    assert first != second
    assert AuthenticationService.verify_password(password, first)
    assert AuthenticationService.verify_password(password, second)


def test_valid_access_token_has_minimal_identity_claims(
    principal: AuthenticatedUser,
) -> None:
    service = AuthenticationService()
    token = service.create_access_token(principal)

    claims = service.decode_token(token, "access")

    assert claims.subject == principal.id
    assert claims.organization_id == principal.organization_id
    assert claims.token_type == "access"
    assert claims.jti
    assert claims.expires_at > datetime.now(timezone.utc)


def test_expired_token_is_rejected(principal: AuthenticatedUser) -> None:
    service = AuthenticationService()
    token = service.create_access_token(
        principal, expires_delta=timedelta(seconds=-1)
    )

    with pytest.raises(AuthenticationError):
        service.decode_token(token, "access")


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        AuthenticationService().decode_token("not.a.jwt", "access")


def test_wrong_token_type_is_rejected(principal: AuthenticatedUser) -> None:
    service = AuthenticationService()
    refresh_token = service.create_refresh_token(principal)

    with pytest.raises(AuthenticationError):
        service.decode_token(refresh_token, "access")


def test_auditor_has_no_future_payroll_write_permission(
    principal: AuthenticatedUser,
) -> None:
    auditor = AuthenticatedUser(
        id=principal.id,
        organization_id=principal.organization_id,
        roles=frozenset({UserRoleType.AUDITOR}),
        employee_id=None,
    )

    assert not PayrollAuthorizationPolicy.can_write_payroll(
        auditor, principal.organization_id
    )


def test_payroll_admin_future_write_permission_is_tenant_scoped(
    principal: AuthenticatedUser,
) -> None:
    payroll_admin = AuthenticatedUser(
        id=principal.id,
        organization_id=principal.organization_id,
        roles=frozenset({UserRoleType.PAYROLL_ADMIN}),
        employee_id=None,
    )

    assert PayrollAuthorizationPolicy.can_write_payroll(
        payroll_admin, principal.organization_id
    )
    assert not PayrollAuthorizationPolicy.can_write_payroll(
        payroll_admin, uuid4()
    )
