"""
Payroll read repository.

Centralises every payroll query used by the read-only API so that the
services above it never build their own competing SQL for the same
question. All methods take a synchronous ``Session``; the async FastAPI
layer reaches them through ``AsyncSession.run_sync``.

"Current" revision semantics:
    A Payroll may have several PayrollVersion revisions. Exactly one may
    carry ``is_current = True`` (enforced by the partial unique index
    ``uq_payroll_version_current``). That flagged revision is the
    authoritative one. When no revision is flagged — legacy or in-progress
    data — the newest revision_no is used as a documented fallback.
"""

import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import Employee
from app.models.payroll import Payroll, PayrollVersion


class PayrollReadRepository:
    """Read-only data access for payrolls and their revisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Employee
    # ------------------------------------------------------------------

    def employee_exists(self, employee_id: uuid.UUID) -> bool:
        """Return True if the employee exists."""
        stmt = select(Employee.id).where(Employee.id == employee_id)
        return self._session.execute(stmt).scalar_one_or_none() is not None

    def get_employee(self, employee_id: uuid.UUID) -> Employee | None:
        """Fetch an employee by id."""
        return self._session.get(Employee, employee_id)

    # ------------------------------------------------------------------
    # Payroll periods
    # ------------------------------------------------------------------

    def list_payroll_periods(
        self,
        employee_id: uuid.UUID,
    ) -> list[tuple[Payroll, PayrollVersion | None]]:
        """
        List every payroll period for an employee, newest period first,
        paired with its current revision (or None when it has no revision).
        """
        stmt = (
            select(Payroll)
            .where(Payroll.employee_id == employee_id)
            .order_by(desc(Payroll.period_year), desc(Payroll.period_month))
            .options(selectinload(Payroll.versions))
        )
        payrolls = list(self._session.execute(stmt).scalars().all())

        return [(p, self._pick_current(list(p.versions))) for p in payrolls]

    def get_payroll(
        self,
        employee_id: uuid.UUID,
        period_year: int,
        period_month: int,
    ) -> Payroll | None:
        """Fetch the Payroll row for an employee/period."""
        stmt = select(Payroll).where(
            Payroll.employee_id == employee_id,
            Payroll.period_year == period_year,
            Payroll.period_month == period_month,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Payroll versions
    # ------------------------------------------------------------------

    def get_current_version(
        self,
        employee_id: uuid.UUID,
        period_year: int,
        period_month: int,
    ) -> PayrollVersion | None:
        """
        Fetch the current revision for an employee/period.

        This is the single source of truth for "which revision does the API
        show"; dashboard, comparison and tax-status all route through it.
        """
        stmt = (
            select(PayrollVersion)
            .join(Payroll, PayrollVersion.payroll_id == Payroll.id)
            .where(
                Payroll.employee_id == employee_id,
                Payroll.period_year == period_year,
                Payroll.period_month == period_month,
            )
            .options(
                selectinload(PayrollVersion.earnings),
                selectinload(PayrollVersion.deductions),
                selectinload(PayrollVersion.absences),
            )
        )
        return self._pick_current(list(self._session.execute(stmt).scalars().all()))

    def get_version(self, version_id: uuid.UUID) -> PayrollVersion | None:
        """Fetch a specific PayrollVersion with its detail lines loaded."""
        stmt = (
            select(PayrollVersion)
            .where(PayrollVersion.id == version_id)
            .options(
                selectinload(PayrollVersion.earnings),
                selectinload(PayrollVersion.deductions),
                selectinload(PayrollVersion.absences),
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_current(versions: list[PayrollVersion]) -> PayrollVersion | None:
        """
        Select the authoritative revision from a list of revisions.

        Prefers the one flagged ``is_current``; falls back to the highest
        revision_no so that partially-populated data still resolves
        deterministically rather than by insertion order.
        """
        if not versions:
            return None

        for version in versions:
            if version.is_current:
                return version

        return max(versions, key=lambda v: v.revision_no)
