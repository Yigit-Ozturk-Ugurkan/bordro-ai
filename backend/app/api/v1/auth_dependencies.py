"""Reusable FastAPI authentication and authorization dependencies."""

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import UserRoleType
from app.services.auth.authentication import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationService,
)
from app.services.auth.authorization import PayrollAuthorizationPolicy

bearer_scheme = HTTPBearer(auto_error=False)


def authentication_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise authentication_failed()

    service = AuthenticationService()
    try:
        claims = service.decode_token(credentials.credentials, "access")
    except AuthenticationError:
        raise authentication_failed() from None

    def load(sync_session: Session) -> AuthenticatedUser | None:
        return service.load_current_user(sync_session, claims)

    user = await session.run_sync(load)
    if user is None:
        raise authentication_failed()
    return user


def require_roles(
    *allowed_roles: UserRoleType,
) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    async def dependency(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if not user.roles.intersection(allowed_roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency


async def require_payroll_read_access(
    employee_id: UUID = Path(..., description="Employee UUID"),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UUID:
    def authorize(sync_session: Session) -> None:
        PayrollAuthorizationPolicy().require_employee_read(
            sync_session, user, employee_id
        )

    await session.run_sync(authorize)
    return employee_id


async def get_current_employee(
    user: AuthenticatedUser = Depends(get_current_user),
) -> UUID:
    if (
        UserRoleType.EMPLOYEE not in user.roles
        or user.employee_id is None
        or user.employee_organization_id != user.organization_id
    ):
        raise HTTPException(status_code=403, detail="Employee account is not linked")
    return user.employee_id
