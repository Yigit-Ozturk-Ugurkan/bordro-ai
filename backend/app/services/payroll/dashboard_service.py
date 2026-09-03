"""
Dashboard Read Service V1.

Composes the payroll dashboard for one employee/year/month out of the
deterministic services that already own each answer:

    PayrollReadRepository -> which revision is current, and its detail lines
    TaxStatusService      -> bracket position and cumulative base

It performs no independent financial arithmetic. Totals are read from the
stored PayrollVersion; line items are read from PayrollEarning /
PayrollDeduction rows; bracket data comes from the tax status service. The
only arithmetic here is the previous-month net delta, which is a plain
subtraction of two stored values.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import EmployeeNotFoundError, PayrollNotFoundError
from app.core.money import (
    ZERO_MONEY,
    money_str,
    percent_change,
    quantize_days,
    quantize_money,
)
from app.models.payroll import PayrollVersion
from app.repositories.payroll_repository import PayrollReadRepository
from app.services.payroll.comparison_service import PayrollComparisonService
from app.services.taxation.cumulative_tax_service import CumulativeTaxService
from app.services.taxation.tax_status_service import BracketView, TaxStatusService


class DashboardEarningItem:
    """Single earning line item, sourced from a PayrollEarning row."""

    def __init__(self, code: str, description: str, amount: Decimal):
        """Initialize earning item."""
        self.code = code
        self.description = description
        self.amount = amount

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "description": self.description,
            "amount": money_str(self.amount),
        }


class DashboardDeductionItem:
    """Single deduction line item, sourced from a PayrollDeduction row."""

    def __init__(self, code: str, description: str, amount: Decimal):
        """Initialize deduction item."""
        self.code = code
        self.description = description
        self.amount = amount

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "description": self.description,
            "amount": money_str(self.amount),
        }


class DashboardTaxInfo:
    """Tax section of the dashboard."""

    def __init__(
        self,
        income_tax: Decimal,
        monthly_taxable_base: Optional[Decimal],
        cumulative_tax_base: Decimal,
        current_bracket_rate: Optional[Decimal] = None,
        next_bracket_rate: Optional[Decimal] = None,
        distance_to_next_bracket: Optional[Decimal] = None,
        rule_set_version: Optional[str] = None,
        current_bracket: Optional["BracketView"] = None,
        next_bracket: Optional["BracketView"] = None,
    ):
        """Initialize tax info."""
        self.income_tax = income_tax
        self.monthly_taxable_base = monthly_taxable_base
        self.cumulative_tax_base = cumulative_tax_base
        self.current_bracket_rate = current_bracket_rate
        self.next_bracket_rate = next_bracket_rate
        self.distance_to_next_bracket = distance_to_next_bracket
        self.rule_set_version = rule_set_version
        self.current_bracket = current_bracket
        self.next_bracket = next_bracket

    def to_dict(self) -> dict:
        """
        Convert to dictionary.

        Every optional field is tested with `is not None`. Testing
        truthiness would render a legitimate Decimal("0.00") - an employee
        sitting exactly on a bracket threshold, for instance - as null.
        """
        return {
            "income_tax": money_str(self.income_tax),
            "monthly_taxable_base": money_str(self.monthly_taxable_base),
            "cumulative_tax_base": money_str(self.cumulative_tax_base),
            "current_bracket_rate": (
                str(self.current_bracket_rate)
                if self.current_bracket_rate is not None
                else None
            ),
            "next_bracket_rate": (
                str(self.next_bracket_rate)
                if self.next_bracket_rate is not None
                else None
            ),
            "distance_to_next_bracket": money_str(self.distance_to_next_bracket),
            "rule_set_version": self.rule_set_version,
            # Full bracket objects (limits + rate), so a caller can render
            # the position without re-deriving it from the bare rates.
            "current_bracket": (
                self.current_bracket.to_dict() if self.current_bracket else None
            ),
            "next_bracket": (
                self.next_bracket.to_dict() if self.next_bracket else None
            ),
        }


class DashboardResult:
    """Complete dashboard data for employee/year/month."""

    def __init__(
        self,
        employee_id: UUID,
        tax_year: int,
        period_month: int,
        gross_salary: Decimal,
        net_salary: Decimal,
        earnings_items: list[DashboardEarningItem],
        total_earnings: Decimal,
        deduction_items: list[DashboardDeductionItem],
        total_deductions: Decimal,
        #
        # Optional with defaults
        previous_net_salary: Optional[Decimal] = None,
        net_salary_delta: Optional[Decimal] = None,
        net_salary_delta_percent: Optional[Decimal] = None,
        paid_days: Decimal = ZERO_MONEY,
        missing_days: Decimal = ZERO_MONEY,
        tax_info: Optional[DashboardTaxInfo] = None,
    ):
        """Initialize dashboard result."""
        self.employee_id = employee_id
        self.tax_year = tax_year
        self.period_month = period_month

        self.gross_salary = gross_salary
        self.net_salary = net_salary
        self.previous_net_salary = previous_net_salary
        self.net_salary_delta = net_salary_delta
        self.net_salary_delta_percent = net_salary_delta_percent

        self.earnings_items = earnings_items
        self.total_earnings = total_earnings

        self.deduction_items = deduction_items
        self.total_deductions = total_deductions

        self.paid_days = paid_days
        self.missing_days = missing_days

        self.tax_info = tax_info or DashboardTaxInfo(
            income_tax=ZERO_MONEY,
            monthly_taxable_base=None,
            cumulative_tax_base=ZERO_MONEY,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "employee_id": str(self.employee_id),
            "period": {
                "year": self.tax_year,
                "month": self.period_month,
            },
            "salary": {
                "gross": money_str(self.gross_salary),
                "net": money_str(self.net_salary),
                # None means "no previous month on record"; that is
                # different from a previous net of 0.00, so `is not None`.
                "previous_net": money_str(self.previous_net_salary),
                "net_delta": money_str(self.net_salary_delta),
                # `is not None`: a real 0.00% change must not become null.
                "net_delta_percent": (
                    str(self.net_salary_delta_percent)
                    if self.net_salary_delta_percent is not None
                    else None
                ),
            },
            "earnings": {
                "items": [item.to_dict() for item in self.earnings_items],
                "total": money_str(self.total_earnings),
            },
            "deductions": {
                "items": [item.to_dict() for item in self.deduction_items],
                "total": money_str(self.total_deductions),
            },
            "attendance": {
                "paid_days": str(self.paid_days),
                "missing_days": str(self.missing_days),
            },
            "tax": self.tax_info.to_dict(),
        }


class DashboardService:
    """Provide payroll dashboard data."""

    def __init__(
        self,
        session: Session,
        cumulative_tax_service: CumulativeTaxService,
        comparison_service: PayrollComparisonService,
        tax_status_service: TaxStatusService,
    ):
        """Initialize dashboard service."""
        self.session = session
        self.cumulative_tax_service = cumulative_tax_service
        self.comparison_service = comparison_service
        self.tax_status_service = tax_status_service
        self._repository = PayrollReadRepository(session)

    def get_payroll_dashboard(
        self,
        employee_id: UUID,
        tax_year: int,
        period_month: int,
    ) -> DashboardResult:
        """
        Get the complete dashboard for employee/year/month.

        Args:
            employee_id: Employee UUID
            tax_year: Year (e.g., 2026)
            period_month: Month 1-12

        Returns:
            DashboardResult with complete payroll information

        Raises:
            EmployeeNotFoundError: if the employee does not exist
            PayrollNotFoundError: if the employee has no payroll for the period
        """
        if not self._repository.employee_exists(employee_id):
            raise EmployeeNotFoundError(employee_id)

        payroll_version = self._repository.get_current_version(
            employee_id, tax_year, period_month
        )
        if not payroll_version:
            raise PayrollNotFoundError(employee_id, tax_year, period_month)

        gross_salary = quantize_money(payroll_version.gross_earnings)
        net_salary = quantize_money(payroll_version.net_pay)

        # Previous-month net, when a previous period exists in this year.
        previous_net_salary = None
        net_salary_delta = None
        net_salary_delta_percent = None
        if period_month > 1:
            prev_version = self._repository.get_current_version(
                employee_id, tax_year, period_month - 1
            )
            if prev_version:
                previous_net_salary = quantize_money(prev_version.net_pay)
                net_salary_delta = net_salary - previous_net_salary
                net_salary_delta_percent = percent_change(
                    net_salary_delta, previous_net_salary
                )

        earnings_items = self._extract_earnings_items(payroll_version)
        deduction_items = self._extract_deduction_items(payroll_version)

        tax_info = self._get_tax_info(employee_id, tax_year, period_month, payroll_version)

        return DashboardResult(
            employee_id=employee_id,
            tax_year=tax_year,
            period_month=period_month,
            gross_salary=gross_salary,
            net_salary=net_salary,
            previous_net_salary=previous_net_salary,
            net_salary_delta=net_salary_delta,
            net_salary_delta_percent=net_salary_delta_percent,
            earnings_items=earnings_items,
            total_earnings=quantize_money(payroll_version.total_earnings),
            deduction_items=deduction_items,
            total_deductions=quantize_money(payroll_version.total_deductions),
            paid_days=quantize_days(payroll_version.paid_days),
            missing_days=quantize_days(payroll_version.missing_days),
            tax_info=tax_info,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_current_payroll_version(
        self,
        employee_id: UUID,
        tax_year: int,
        period_month: int,
    ) -> Optional[PayrollVersion]:
        """
        Get the current payroll version for a period.

        Retained as a thin delegation to the repository so existing callers
        keep working; the repository is the single source of truth for
        "current revision" semantics.
        """
        return self._repository.get_current_version(
            employee_id, tax_year, period_month
        )

    @staticmethod
    def _extract_earnings_items(pv: PayrollVersion) -> list[DashboardEarningItem]:
        """
        Build the earnings breakdown from the version's PayrollEarning rows.

        The stored detail lines are the source of truth. Nothing is
        synthesised: a version with no earning lines reports an empty
        breakdown alongside its stored total, rather than inventing a
        single lump-sum line that would disagree with the real data.
        """
        return [
            DashboardEarningItem(
                code=earning.code,
                description=earning.label,
                amount=quantize_money(earning.amount),
            )
            for earning in sorted(pv.earnings, key=lambda e: e.code)
        ]

    @staticmethod
    def _extract_deduction_items(pv: PayrollVersion) -> list[DashboardDeductionItem]:
        """Build the deductions breakdown from PayrollDeduction rows."""
        return [
            DashboardDeductionItem(
                code=deduction.code,
                description=deduction.label,
                amount=quantize_money(deduction.amount),
            )
            for deduction in sorted(pv.deductions, key=lambda d: d.code)
        ]

    def _get_tax_info(
        self,
        employee_id: UUID,
        tax_year: int,
        period_month: int,
        payroll_version: PayrollVersion,
    ) -> DashboardTaxInfo:
        """
        Build the tax section by delegating to TaxStatusService.

        Bracket resolution lives in exactly one place. The dashboard adds
        only the month's withheld income tax, which is a stored payroll
        value, not a recomputation.
        """
        income_tax = quantize_money(payroll_version.income_tax)

        status = self.tax_status_service.get_tax_status(
            employee_id, tax_year, period_month
        )

        return DashboardTaxInfo(
            income_tax=income_tax,
            monthly_taxable_base=status.monthly_taxable_base,
            cumulative_tax_base=status.cumulative_taxable_base,
            current_bracket_rate=(
                status.current_bracket.rate if status.current_bracket else None
            ),
            next_bracket_rate=(
                status.next_bracket.rate if status.next_bracket else None
            ),
            distance_to_next_bracket=status.distance_to_next_bracket,
            rule_set_version=status.rule_set_version,
            current_bracket=status.current_bracket,
            next_bracket=status.next_bracket,
        )
