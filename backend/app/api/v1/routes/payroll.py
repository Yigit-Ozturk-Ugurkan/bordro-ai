"""
Payroll API routes V1 (read-only).

    GET /api/v1/employees/{employee_id}/payrolls
    GET /api/v1/employees/{employee_id}/payrolls/{year}/{month}
    GET /api/v1/employees/{employee_id}/payrolls/{year}/{month}/comparison
    GET /api/v1/employees/{employee_id}/tax-status
    GET /api/v1/employees/{employee_id}/dashboard/{year}/{month}

Handlers contain no business logic. Each one resolves path parameters,
delegates to a service inside ``AsyncSession.run_sync``, and validates the
result through a Pydantic response model. Domain errors propagate to the
application-wide handler registered in ``app.main``, so no handler builds
an error body or leaks a database exception.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    build_comparison_service,
    build_dashboard_service,
    build_payroll_read_service,
    build_tax_status_service,
)
from app.api.v1.auth_dependencies import (
    get_current_employee,
    require_payroll_read_access,
)
from app.core.exceptions import ComparisonNotAvailableError, PayrollNotFoundError
from app.db.session import get_db
from app.repositories.payroll_repository import PayrollReadRepository
from app.schemas.dashboard import PayrollDashboardReadSchema
from app.schemas.payroll_comparison import PayrollComparisonReadSchema
from app.schemas.payroll_read import (
    PayrollDetailSchema,
    PayrollPeriodListSchema,
    TaxStatusSchema,
)

router = APIRouter(prefix="/api/v1", tags=["payroll"])


@router.get(
    "/employees/{employee_id}/payrolls",
    response_model=PayrollPeriodListSchema,
    summary="List payroll periods",
    description="List every payroll period recorded for an employee, newest first.",
)
async def list_payrolls(
    employee_id: UUID = Depends(require_payroll_read_access),
    session: AsyncSession = Depends(get_db),
) -> PayrollPeriodListSchema:
    """List an employee's payroll periods."""

    def work(sync_session: Session) -> dict:
        return build_payroll_read_service(sync_session).list_payroll_periods(
            employee_id
        )

    return PayrollPeriodListSchema(**await session.run_sync(work))


@router.get(
    "/employees/{employee_id}/payrolls/{year}/{month}",
    response_model=PayrollDetailSchema,
    summary="Get payroll detail",
    description="Full detail of the current revision for one payroll period.",
)
async def get_payroll_detail(
    employee_id: UUID = Depends(require_payroll_read_access),
    year: int = Path(..., ge=2000, le=2999, description="Period year"),
    month: int = Path(..., ge=1, le=12, description="Month (1-12)"),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailSchema:
    """Get one period's payroll detail."""

    def work(sync_session: Session) -> dict:
        return build_payroll_read_service(sync_session).get_payroll_detail(
            employee_id, year, month
        )

    return PayrollDetailSchema(**await session.run_sync(work))


@router.get(
    "/employees/{employee_id}/payrolls/{year}/{month}/comparison",
    response_model=PayrollComparisonReadSchema,
    summary="Get payroll comparison",
    description=(
        "Compare a payroll period with the preceding month. Factual deltas "
        "only; the response makes no causal claims."
    ),
)
async def get_payroll_comparison(
    employee_id: UUID = Depends(require_payroll_read_access),
    year: int = Path(..., ge=2000, le=2999, description="Period year"),
    month: int = Path(..., ge=1, le=12, description="Month (1-12)"),
    session: AsyncSession = Depends(get_db),
) -> PayrollComparisonReadSchema:
    """Compare a period against the previous month."""

    def work(sync_session: Session) -> dict:
        # January has no predecessor inside the tax year. This is a
        # well-formed request for a comparison that cannot exist, so it is
        # a 400 rather than a 422 path-validation failure: the month itself
        # is a legal value.
        if month == 1:
            raise ComparisonNotAvailableError(
                "January has no previous month within the tax year; "
                "comparison is available for months 2-12"
            )

        repository = PayrollReadRepository(sync_session)
        comparison_service = build_comparison_service(sync_session)

        current = repository.get_current_version(employee_id, year, month)
        if current is None:
            raise PayrollNotFoundError(employee_id, year, month)

        previous = repository.get_current_version(employee_id, year, month - 1)
        if previous is None:
            raise PayrollNotFoundError(employee_id, year, month - 1)

        return comparison_service.compare_payroll_versions(
            previous.id, current.id
        ).to_dict()

    return PayrollComparisonReadSchema(**await session.run_sync(work))


@router.get(
    "/employees/{employee_id}/tax-status",
    response_model=TaxStatusSchema,
    summary="Get tax status",
    description=(
        "The employee's position in the progressive tax schedule: cumulative "
        "base, current and next bracket, and distance to the next bracket."
    ),
)
async def get_tax_status(
    employee_id: UUID = Depends(require_payroll_read_access),
    year: Optional[int] = Query(
        None, ge=2000, le=2999, description="Tax year (defaults to the current year)"
    ),
    month: Optional[int] = Query(
        None,
        ge=1,
        le=12,
        description="Month 1-12; defaults to the latest recorded month",
    ),
    session: AsyncSession = Depends(get_db),
) -> TaxStatusSchema:
    """Get the employee's progressive tax position."""
    tax_year = year if year is not None else date.today().year

    def work(sync_session: Session) -> dict:
        return (
            build_tax_status_service(sync_session)
            .get_tax_status(employee_id, tax_year, month)
            .to_dict()
        )

    return TaxStatusSchema(**await session.run_sync(work))


@router.get(
    "/employees/{employee_id}/dashboard/{year}/{month}",
    response_model=PayrollDashboardReadSchema,
    summary="Get payroll dashboard",
    description="Complete payroll dashboard for an employee in a given month.",
)
async def get_payroll_dashboard(
    employee_id: UUID = Depends(require_payroll_read_access),
    year: int = Path(..., ge=2000, le=2999, description="Tax year"),
    month: int = Path(..., ge=1, le=12, description="Month (1-12)"),
    session: AsyncSession = Depends(get_db),
) -> PayrollDashboardReadSchema:
    """Get the complete payroll dashboard."""

    def work(sync_session: Session) -> dict:
        return (
            build_dashboard_service(sync_session)
            .get_payroll_dashboard(employee_id, year, month)
            .to_dict()
        )

    return PayrollDashboardReadSchema(**await session.run_sync(work))


# Employee self-service routes deliberately derive the employee id from the
# authenticated user. They delegate to the same handlers/services as the
# authorized employee-id routes, so no financial logic is duplicated.


@router.get(
    "/me/payrolls",
    response_model=PayrollPeriodListSchema,
    summary="List my payroll periods",
)
async def list_my_payrolls(
    employee_id: UUID = Depends(get_current_employee),
    session: AsyncSession = Depends(get_db),
) -> PayrollPeriodListSchema:
    return await list_payrolls(employee_id=employee_id, session=session)


@router.get(
    "/me/payrolls/{year}/{month}",
    response_model=PayrollDetailSchema,
    summary="Get my payroll detail",
)
async def get_my_payroll_detail(
    year: int = Path(..., ge=2000, le=2999, description="Period year"),
    month: int = Path(..., ge=1, le=12, description="Month (1-12)"),
    employee_id: UUID = Depends(get_current_employee),
    session: AsyncSession = Depends(get_db),
) -> PayrollDetailSchema:
    return await get_payroll_detail(
        employee_id=employee_id, year=year, month=month, session=session
    )


@router.get(
    "/me/payrolls/{year}/{month}/comparison",
    response_model=PayrollComparisonReadSchema,
    summary="Get my payroll comparison",
)
async def get_my_payroll_comparison(
    year: int = Path(..., ge=2000, le=2999, description="Period year"),
    month: int = Path(..., ge=1, le=12, description="Month (1-12)"),
    employee_id: UUID = Depends(get_current_employee),
    session: AsyncSession = Depends(get_db),
) -> PayrollComparisonReadSchema:
    return await get_payroll_comparison(
        employee_id=employee_id, year=year, month=month, session=session
    )


@router.get(
    "/me/tax-status",
    response_model=TaxStatusSchema,
    summary="Get my tax status",
)
async def get_my_tax_status(
    year: Optional[int] = Query(None, ge=2000, le=2999),
    month: Optional[int] = Query(None, ge=1, le=12),
    employee_id: UUID = Depends(get_current_employee),
    session: AsyncSession = Depends(get_db),
) -> TaxStatusSchema:
    return await get_tax_status(
        employee_id=employee_id, year=year, month=month, session=session
    )


@router.get(
    "/me/dashboard/{year}/{month}",
    response_model=PayrollDashboardReadSchema,
    summary="Get my payroll dashboard",
)
async def get_my_payroll_dashboard(
    year: int = Path(..., ge=2000, le=2999, description="Tax year"),
    month: int = Path(..., ge=1, le=12, description="Month (1-12)"),
    employee_id: UUID = Depends(get_current_employee),
    session: AsyncSession = Depends(get_db),
) -> PayrollDashboardReadSchema:
    return await get_payroll_dashboard(
        employee_id=employee_id, year=year, month=month, session=session
    )
