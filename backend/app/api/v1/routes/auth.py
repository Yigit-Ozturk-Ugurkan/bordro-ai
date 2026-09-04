"""Authentication endpoints: login, refresh, logout, and current principal."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.v1.auth_dependencies import authentication_failed, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse
from app.services.auth.authentication import AuthenticatedUser, AuthenticationService
from app.services.auth.login_throttle import login_throttle
from app.services.auth.refresh_sessions import (
    RefreshSessionError,
    RefreshSessionService,
    RefreshTokenReuseDetected,
    SessionTokens,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _token_response(tokens: SessionTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.access_expires_in,
    )


def _set_refresh_cookie(response: Response, tokens: SessionTokens) -> None:
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        expires=tokens.refresh_expires_at,
        path=settings.auth_cookie_path,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        path=settings.auth_cookie_path,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


def _authentication_failed_with_cookie_clear() -> HTTPException:
    response = Response()
    _clear_refresh_cookie(response)
    error = authentication_failed()
    return HTTPException(
        status_code=error.status_code,
        detail=error.detail,
        headers={**(error.headers or {}), "Set-Cookie": response.headers["set-cookie"]},
    )


def _require_trusted_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_cors_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def _request_source(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    _require_trusted_browser_origin(request)
    source = _request_source(request)
    if login_throttle.is_blocked(source, credentials.email):
        logger.warning("security_event=LOGIN_THROTTLED")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={
                "Retry-After": str(settings.login_rate_limit_cooldown_seconds)
            },
        )

    authentication = AuthenticationService()

    def authenticate(sync_session: Session) -> AuthenticatedUser | None:
        return authentication.authenticate_user(
            sync_session, credentials.email, credentials.password
        )

    user = await session.run_sync(authenticate)
    if user is None:
        login_throttle.record_failure(source, credentials.email)
        logger.warning("security_event=LOGIN_FAILED")
        raise authentication_failed()

    login_throttle.record_success(source, credentials.email)
    session_service = RefreshSessionService(authentication=authentication)
    tokens = await session.run_sync(session_service.create_session, user)
    await session.commit()
    _set_refresh_cookie(response, tokens)
    logger.info("security_event=LOGIN_SUCCESS")
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    _require_trusted_browser_origin(request)
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not refresh_token:
        raise _authentication_failed_with_cookie_clear()

    service = RefreshSessionService()
    try:
        tokens = await session.run_sync(service.rotate_session, refresh_token)
    except RefreshTokenReuseDetected:
        await session.commit()
        logger.warning("security_event=TOKEN_REUSE_DETECTED")
        raise _authentication_failed_with_cookie_clear() from None
    except RefreshSessionError:
        await session.commit()
        logger.warning("security_event=TOKEN_REFRESH_REJECTED")
        raise _authentication_failed_with_cookie_clear() from None

    await session.commit()
    _set_refresh_cookie(response, tokens)
    logger.info("security_event=TOKEN_REFRESH")
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> None:
    _require_trusted_browser_origin(request)
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if refresh_token:
        service = RefreshSessionService()
        await session.run_sync(service.revoke_session, refresh_token)
        await session.commit()
    _clear_refresh_cookie(response)
    logger.info("security_event=LOGOUT")


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
