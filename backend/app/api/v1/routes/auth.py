"""Authentication endpoints: login, refresh, and current principal."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.v1.auth_dependencies import authentication_failed, get_current_user
from app.db.session import get_db
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth.authentication import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationService,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _token_response(
    service: AuthenticationService, user: AuthenticatedUser
) -> TokenResponse:
    pair = service.create_token_pair(user)
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = AuthenticationService()

    def authenticate(sync_session: Session) -> AuthenticatedUser | None:
        return service.authenticate_user(
            sync_session, credentials.email, credentials.password
        )

    user = await session.run_sync(authenticate)
    if user is None:
        raise authentication_failed()
    return _token_response(service, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = AuthenticationService()
    try:
        claims = service.decode_token(request.refresh_token, "refresh")
    except AuthenticationError:
        raise authentication_failed() from None

    def load(sync_session: Session) -> AuthenticatedUser | None:
        return service.load_current_user(sync_session, claims)

    user = await session.run_sync(load)
    if user is None:
        raise authentication_failed()
    return _token_response(service, user)


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        roles=sorted(user.roles, key=lambda role: role.value),
        employee_id=user.employee_id,
    )
