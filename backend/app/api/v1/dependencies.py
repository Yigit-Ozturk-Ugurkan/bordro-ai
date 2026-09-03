"""
Service construction for the V1 API.

The FastAPI runtime is async (FastAPI -> SQLAlchemy Async -> psycopg ->
PostgreSQL) while the payroll and taxation services are synchronous, and
deliberately so: they share their query style with Alembic and with the
test suite, and they are the code that will later be reused by batch jobs.

The two worlds are joined by ``AsyncSession.run_sync``, which hands the
callable a real synchronous ``Session`` backed by the same async
connection via SQLAlchemy's greenlet bridge. Every factory below therefore
takes a sync ``Session`` and is invoked inside ``run_sync``.
"""

from sqlalchemy.orm import Session

from app.services.payroll.comparison_service import PayrollComparisonService
from app.services.payroll.dashboard_service import DashboardService
from app.services.payroll.payroll_read_service import PayrollReadService
from app.services.taxation.cumulative_tax_service import CumulativeTaxService
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.tax_service import TaxService
from app.services.taxation.tax_status_service import TaxStatusService


def build_tax_service(session: Session) -> TaxService:
    """Rule-set and parameter resolution."""
    return TaxService(session)


def build_tax_engine(session: Session) -> TaxEngine:
    """Deterministic progressive tax engine."""
    return TaxEngine(session, build_tax_service(session))


def build_cumulative_tax_service(session: Session) -> CumulativeTaxService:
    """Annual cumulative tax ledger."""
    return CumulativeTaxService(session, build_tax_engine(session))


def build_tax_status_service(session: Session) -> TaxStatusService:
    """Progressive tax position reader."""
    return TaxStatusService(
        session,
        build_tax_engine(session),
        build_tax_service(session),
    )


def build_comparison_service(session: Session) -> PayrollComparisonService:
    """Factual payroll period comparison."""
    return PayrollComparisonService(session)


def build_payroll_read_service(session: Session) -> PayrollReadService:
    """Payroll period listing and detail."""
    return PayrollReadService(session)


def build_dashboard_service(session: Session) -> DashboardService:
    """Dashboard composition over the deterministic services."""
    return DashboardService(
        session,
        build_cumulative_tax_service(session),
        build_comparison_service(session),
        build_tax_status_service(session),
    )
