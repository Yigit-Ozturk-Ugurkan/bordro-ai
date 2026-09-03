from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.event_loop import install_windows_event_loop_policy
from app.core.exceptions import BordroError
from app.db.session import engine
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.payroll import router as payroll_router

# psycopg's async driver cannot run on Windows' default ProactorEventLoop.
# Installing the selector policy at import time keeps the intended runtime
# stack intact: FastAPI -> SQLAlchemy Async -> psycopg -> PostgreSQL.
install_windows_event_loop_policy()

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

# Register API routes
app.include_router(auth_router)
app.include_router(payroll_router)


@app.exception_handler(BordroError)
async def handle_domain_error(request: Request, exc: BordroError) -> JSONResponse:
    """
    Translate a domain error into its HTTP response.

    Only messages the domain layer authored are rendered. Database and
    driver exceptions are not BordroError instances, so they never reach
    this handler and never leak into a response body; they surface as a
    generic 500 from Starlette instead.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.get("/health", tags=["System"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
    }


@app.get("/health/db", tags=["System"])
async def database_health() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }


@app.get("/api/v1/system/info", tags=["System"])
async def system_info() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
    }
