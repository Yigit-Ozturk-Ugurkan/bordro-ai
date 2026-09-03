"""
Root conftest for Bordro AI backend tests.

Uses SYNC SQLAlchemy engine for tests — consistent with the Alembic
approach on Windows where psycopg + ProactorEventLoop causes issues
with async connections.

The test session connects to the same bordro_db database and runs each
test inside a transaction that is rolled back after the test completes.
This keeps the database clean without needing a separate test database.
"""

import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.event_loop import install_windows_event_loop_policy

# psycopg's async driver cannot run on Windows' default ProactorEventLoop.
# Install the selector policy before pytest-asyncio builds an event loop,
# so the async API tests exercise the same stack the app runs on.
install_windows_event_loop_policy()
from app.models.employee import Employee
from app.models.enums import (
    CalculationMode,
    EmployeeStatus,
    PayrollSourceType,
    PayrollVersionStatus,
)
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

settings = get_settings()

# Build a sync URL from the async one.
# Replace 'postgresql+psycopg' with 'postgresql+psycopg' (sync psycopg3 driver)
# This should already be the correct sync driver string.
sync_url = settings.database_url

sync_engine = create_engine(sync_url, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """
    Provide a transactional database session for tests.

    Each test runs inside a SAVEPOINT. After the test, the SAVEPOINT is
    rolled back so that the database remains clean. The outer transaction
    is also rolled back.
    """
    connection = sync_engine.connect()
    transaction = connection.begin()
    session = SyncSessionLocal(bind=connection)

    # Start a nested (SAVEPOINT) transaction.
    nested = connection.begin_nested()

    # If application code calls session.commit(), restart the SAVEPOINT
    # instead of actually committing.
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess: Session, trans: object) -> None:
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def sample_organization(db_session: Session) -> Organization:
    """Create a test organization."""
    org = Organization(
        id=uuid.uuid4(),
        name="Test Company",
        code=f"TEST-{uuid.uuid4().hex[:8]}",
        timezone="Europe/Istanbul",
        is_active=True,
    )
    db_session.add(org)
    db_session.flush()
    return org


@pytest.fixture()
def sample_employee(
    db_session: Session,
    sample_organization: Organization,
) -> Employee:
    """Create a test employee."""
    emp = Employee(
        id=uuid.uuid4(),
        organization_id=sample_organization.id,
        employee_no=f"EMP-{uuid.uuid4().hex[:8]}",
        first_name="Ali",
        last_name="Yılmaz",
        hire_date=date(2024, 1, 15),
        status=EmployeeStatus.ACTIVE,
    )
    db_session.add(emp)
    db_session.flush()
    return emp


@pytest.fixture()
def sample_payroll(
    db_session: Session,
    sample_organization: Organization,
    sample_employee: Employee,
) -> Payroll:
    """Create a test payroll for August 2026."""
    payroll = Payroll(
        id=uuid.uuid4(),
        organization_id=sample_organization.id,
        employee_id=sample_employee.id,
        period_year=2026,
        period_month=8,
    )
    db_session.add(payroll)
    db_session.flush()
    return payroll


@pytest.fixture()
def sample_payroll_version(
    db_session: Session,
    sample_payroll: Payroll,
) -> PayrollVersion:
    """Create a draft PayrollVersion for testing."""
    version = PayrollVersion(
        id=uuid.uuid4(),
        payroll_id=sample_payroll.id,
        revision_no=1,
        status=PayrollVersionStatus.DRAFT,
        source_type=PayrollSourceType.MANUAL,
        currency="TRY",
        gross_earnings=Decimal("15000.00"),
        sgk_base=Decimal("15000.00"),
        income_tax_base=Decimal("12900.00"),
        stamp_tax_base=Decimal("15000.00"),
        employee_sgk=Decimal("2100.00"),
        employee_unemployment=Decimal("150.00"),
        income_tax=Decimal("1935.00"),
        stamp_tax=Decimal("113.85"),
        total_earnings=Decimal("15000.00"),
        total_deductions=Decimal("4298.85"),
        net_pay=Decimal("10701.15"),
        paid_days=Decimal("30.00"),
        missing_days=Decimal("0.00"),
        calculation_mode=CalculationMode.IMPORTED,
        is_current=True,
    )
    db_session.add(version)
    db_session.flush()
    return version


# ==========================================================================
# Async API test harness
#
# The API tests drive the real ASGI app through httpx's ASGITransport
# rather than starlette's TestClient. TestClient runs the app in a separate
# portal thread with its own event loop, which cannot share an AsyncSession
# with the test. ASGITransport runs the app inline in the test's own loop,
# so the app and the test genuinely share one database transaction and the
# seeded data is visible to the request without ever being committed.
# ==========================================================================


@pytest_asyncio.fixture()
async def async_db_session() -> AsyncGenerator["AsyncSession", None]:
    """
    Provide a transactional AsyncSession bound to a single connection.

    Mirrors the sync ``db_session`` fixture: work happens inside a
    SAVEPOINT that is rolled back afterwards, so the database is left
    untouched and tests stay order-independent.
    """
    from app.db.session import engine as async_engine

    connection = await async_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    nested = await connection.begin_nested()

    # Application code (the seeds) calls commit(); restart the SAVEPOINT
    # instead of letting it end the outer transaction.
    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(sess: Session, trans: object) -> None:
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            connection.sync_connection.begin_nested()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture()
async def seeded_async_session(
    async_db_session: "AsyncSession",
) -> AsyncGenerator["AsyncSession", None]:
    """
    An async session with the tax rules and demo payroll data loaded.

    Both seeds are synchronous, so they run through ``run_sync`` on the
    same connection the API request will use.
    """
    from app.seeds.demo_payroll_seed import seed_demo_payroll
    from app.seeds.tax_2026_seed import seed_tax_2026

    def load(sync_session: Session) -> None:
        seed_tax_2026(sync_session)
        seed_demo_payroll(sync_session)

    await async_db_session.run_sync(load)
    yield async_db_session


@pytest_asyncio.fixture()
async def api_client(
    async_db_session: "AsyncSession",
) -> AsyncGenerator["AsyncClient", None]:
    """
    An httpx client wired to the ASGI app, sharing the test transaction.

    ``get_db`` is overridden so route handlers receive the very session the
    test seeded on. The override is removed afterwards so app state does
    not leak between tests.
    """
    from app.db.session import get_db
    from app.main import app

    async def override_get_db() -> AsyncGenerator["AsyncSession", None]:
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def seeded_api_client(
    api_client: "AsyncClient",
    seeded_async_session: "AsyncSession",
) -> AsyncGenerator["AsyncClient", None]:
    """An API client whose shared transaction already holds the demo data."""
    yield api_client


@pytest_asyncio.fixture()
async def demo_employee_id(seeded_async_session: "AsyncSession") -> uuid.UUID:
    """The UUID of the seeded demo employee."""
    from app.seeds.demo_payroll_seed import DEMO_EMPLOYEE_NO

    def fetch(sync_session: Session) -> uuid.UUID:
        employee = (
            sync_session.query(Employee)
            .filter(Employee.employee_no == DEMO_EMPLOYEE_NO)
            .one()
        )
        return employee.id

    return await seeded_async_session.run_sync(fetch)
