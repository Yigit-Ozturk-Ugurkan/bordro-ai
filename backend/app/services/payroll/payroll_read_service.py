"""
Payroll Read Service V1.

Backs the two plain read endpoints:
- the list of periods an employee has payrolls for
- the full detail of one period's current revision

Like the other read services it performs no financial arithmetic. Totals
come from the stored PayrollVersion, line items from the stored detail
rows. Its job is shaping stored facts into the API contract.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import EmployeeNotFoundError, PayrollNotFoundError
from app.core.money import money_str, quantize_days, quantize_money
from app.models.payroll import PayrollVersion
from app.repositories.payroll_repository import PayrollReadRepository


class PayrollReadService:
    """Read-only access to payroll periods and their detail."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = PayrollReadRepository(session)

    def list_payroll_periods(self, employee_id: uuid.UUID) -> dict:
        """
        List every payroll period recorded for an employee, newest first.

        An employee with no payrolls yet is not an error: the response is
        an empty list with count 0. Only an employee that does not exist
        raises.

        Raises:
            EmployeeNotFoundError: if the employee does not exist
        """
        if not self._repository.employee_exists(employee_id):
            raise EmployeeNotFoundError(employee_id)

        rows = self._repository.list_payroll_periods(employee_id)

        periods = []
        for payroll, version in rows:
            periods.append(
                {
                    "year": payroll.period_year,
                    "month": payroll.period_month,
                    "payroll_id": str(payroll.id),
                    "payroll_version_id": (
                        str(version.id) if version is not None else None
                    ),
                    "revision_no": version.revision_no if version else None,
                    "status": str(version.status) if version else None,
                    "is_current": version.is_current if version else None,
                    "gross_earnings": (
                        money_str(version.gross_earnings) if version else None
                    ),
                    "net_pay": money_str(version.net_pay) if version else None,
                }
            )

        return {
            "employee_id": str(employee_id),
            "count": len(periods),
            "periods": periods,
        }

    def get_payroll_detail(
        self,
        employee_id: uuid.UUID,
        period_year: int,
        period_month: int,
    ) -> dict:
        """
        Get the full detail of one period's current revision.

        Raises:
            EmployeeNotFoundError: if the employee does not exist
            PayrollNotFoundError: if the employee has no payroll for the period
        """
        if not self._repository.employee_exists(employee_id):
            raise EmployeeNotFoundError(employee_id)

        version = self._repository.get_current_version(
            employee_id, period_year, period_month
        )
        if version is None:
            raise PayrollNotFoundError(employee_id, period_year, period_month)

        return {
            "employee_id": str(employee_id),
            "year": period_year,
            "month": period_month,
            "payroll_id": str(version.payroll_id),
            "revision": {
                "payroll_version_id": str(version.id),
                "revision_no": version.revision_no,
                "status": str(version.status),
                "source_type": str(version.source_type),
                "calculation_mode": str(version.calculation_mode),
                "is_current": version.is_current,
                "currency": version.currency,
            },
            "gross": money_str(version.gross_earnings),
            "net": money_str(version.net_pay),
            "earnings": {
                "total": money_str(version.total_earnings),
                "items": self._earning_lines(version),
            },
            "deductions": {
                "total": money_str(version.total_deductions),
                "items": self._deduction_lines(version),
            },
            "attendance": {
                "paid_days": str(quantize_days(version.paid_days)),
                "missing_days": str(quantize_days(version.missing_days)),
                "absences": self._absence_lines(version),
            },
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _earning_lines(version: PayrollVersion) -> list[dict]:
        """Serialize the version's earning lines, ordered by code."""
        return [
            {
                "code": earning.code,
                "label": earning.label,
                "category": earning.category,
                "amount": money_str(earning.amount),
            }
            for earning in sorted(version.earnings, key=lambda e: e.code)
        ]

    @staticmethod
    def _deduction_lines(version: PayrollVersion) -> list[dict]:
        """Serialize the version's deduction lines, ordered by code."""
        return [
            {
                "code": deduction.code,
                "label": deduction.label,
                "category": deduction.category,
                "amount": money_str(deduction.amount),
                "is_statutory": deduction.is_statutory,
            }
            for deduction in sorted(version.deductions, key=lambda d: d.code)
        ]

    @staticmethod
    def _absence_lines(version: PayrollVersion) -> list[dict]:
        """Serialize the version's absence records, ordered by reason code."""
        return [
            {
                "reason_code": absence.reason_code,
                "description": absence.description,
                "day_count": str(quantize_days(absence.day_count)),
                "is_paid": absence.is_paid,
                # None is preserved: it means "no financial impact recorded",
                # which is not the same as an effect of exactly 0.00.
                "gross_effect": (
                    money_str(absence.gross_effect)
                    if absence.gross_effect is not None
                    else None
                ),
            }
            for absence in sorted(version.absences, key=lambda a: a.reason_code)
        ]
