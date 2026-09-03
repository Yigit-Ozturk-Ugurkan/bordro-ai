from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.event_loop import install_windows_event_loop_policy

# psycopg's async driver refuses to run on Windows' default
# ProactorEventLoop. Install the selector policy before the async engine is
# created so the FastAPI runtime keeps its intended async stack:
#   FastAPI -> SQLAlchemy Async -> psycopg -> PostgreSQL
install_windows_event_loop_policy()

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
