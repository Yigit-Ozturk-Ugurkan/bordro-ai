"""
Payroll Comparison Service V1.

Provides deterministic, fact-based comparison between two payroll versions.

Scope discipline - this service reports WHAT changed, never WHY:
- previous/current net, earnings, deductions, income tax
- absolute and percentage deltas
- missing days delta
- per-code earning and deduction deltas

It deliberately produces no causal statements ("net fell because of X").
Attributing a net change to a single cause requires a counterfactual
engine that recomputes the payroll with one input held constant; no such
engine exists yet, and a delta alone does not establish causation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.money import (
    ZERO_MONEY,
    money_str,
    percent_change,
    quantize_days,
    quantize_money,
)
from app.models.payroll import Payroll
from app.repositories.payroll_repository import PayrollReadRepository


class PayrollComparisonResult:
    """Immutable result of comparing two payroll versions."""

    def __init__(
        self,
        previous_payroll_version_id: UUID,
        current_payroll_version_id: UUID,
        employee_id: UUID,
        comparison_date: datetime,
        #
        # Net salary
        previous_net: Decimal,
        current_net: Decimal,
        net_delta: Decimal,
        net_delta_percent: Optional[Decimal],
        #
        # Earnings
        previous_total_earnings: Decimal,
        current_total_earnings: Decimal,
        earnings_delta: Decimal,
        earnings_delta_percent: Optional[Decimal],
        #
        # Deductions
        previous_total_deductions: Decimal,
        current_total_deductions: Decimal,
        deductions_delta: Decimal,
        deductions_delta_percent: Optional[Decimal],
        #
        # Income tax
        previous_income_tax: Decimal,
        current_income_tax: Decimal,
        income_tax_delta: Decimal,
        income_tax_delta_percent: Optional[Decimal],
        #
        # Attendance
        previous_missing_days: Decimal,
        current_missing_days: Decimal,
        missing_days_delta: Decimal,
        #
        # Code-level deltas: code -> {previous, current, delta}
        earning_deltas: dict[str, dict[str, Decimal]],
        deduction_deltas: dict[str, dict[str, Decimal]],
    ):
        """Initialize immutable comparison result."""
        self.previous_payroll_version_id = previous_payroll_version_id
        self.current_payroll_version_id = current_payroll_version_id
        self.employee_id = employee_id
        self.comparison_date = comparison_date

        # Net salary
        self.previous_net = previous_net
        self.current_net = current_net
        self.net_delta = net_delta
        self.net_delta_percent = net_delta_percent

        # Earnings
        self.previous_total_earnings = previous_total_earnings
        self.current_total_earnings = current_total_earnings
        self.earnings_delta = earnings_delta
        self.earnings_delta_percent = earnings_delta_percent

        # Deductions
        self.previous_total_deductions = previous_total_deductions
        self.current_total_deductions = current_total_deductions
        self.deductions_delta = deductions_delta
        self.deductions_delta_percent = deductions_delta_percent

        # Income tax
        self.previous_income_tax = previous_income_tax
        self.current_income_tax = current_income_tax
        self.income_tax_delta = income_tax_delta
        self.income_tax_delta_percent = income_tax_delta_percent

        # Attendance
        self.previous_missing_days = previous_missing_days
        self.current_missing_days = current_missing_days
        self.missing_days_delta = missing_days_delta

        # Code-level deltas
        self.earning_deltas = earning_deltas
        self.deduction_deltas = deduction_deltas

    @staticmethod
    def _codes_to_dict(deltas: dict[str, dict[str, Decimal]]) -> dict[str, dict]:
        """Serialize per-code deltas, preserving zero values."""
        return {
            code: {
                "previous": money_str(values["previous"]),
                "current": money_str(values["current"]),
                "delta": money_str(values["delta"]),
            }
            for code, values in deltas.items()
        }

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "previous_payroll_version_id": str(self.previous_payroll_version_id),
            "current_payroll_version_id": str(self.current_payroll_version_id),
            "employee_id": str(self.employee_id),
            "comparison_date": self.comparison_date.isoformat(),
            "net": {
                "previous": money_str(self.previous_net),
                "current": money_str(self.current_net),
                "delta": money_str(self.net_delta),
                # `is not None` matters: a genuine 0.00% change must
                # serialize as "0.00", not as null.
                "delta_percent": (
                    str(self.net_delta_percent)
                    if self.net_delta_percent is not None
                    else None
                ),
            },
            "earnings": {
                "previous": money_str(self.previous_total_earnings),
                "current": money_str(self.current_total_earnings),
                "delta": money_str(self.earnings_delta),
                "delta_percent": (
                    str(self.earnings_delta_percent)
                    if self.earnings_delta_percent is not None
                    else None
                ),
                "by_code": self._codes_to_dict(self.earning_deltas),
            },
            "deductions": {
                "previous": money_str(self.previous_total_deductions),
                "current": money_str(self.current_total_deductions),
                "delta": money_str(self.deductions_delta),
                "delta_percent": (
                    str(self.deductions_delta_percent)
                    if self.deductions_delta_percent is not None
                    else None
                ),
                "by_code": self._codes_to_dict(self.deduction_deltas),
            },
            "income_tax": {
                "previous": money_str(self.previous_income_tax),
                "current": money_str(self.current_income_tax),
                "delta": money_str(self.income_tax_delta),
                "delta_percent": (
                    str(self.income_tax_delta_percent)
                    if self.income_tax_delta_percent is not None
                    else None
                ),
            },
            "attendance": {
                "previous_missing_days": str(self.previous_missing_days),
                "current_missing_days": str(self.current_missing_days),
                "missing_days_delta": str(self.missing_days_delta),
            },
        }


class PayrollComparisonService:
    """Compare two payroll versions (deterministic, factual only)."""

    def __init__(self, session: Session):
        """Initialize with database session."""
        self.session = session
        self._repository = PayrollReadRepository(session)

    def compare_payroll_versions(
        self,
        previous_version_id: UUID,
        current_version_id: UUID,
    ) -> PayrollComparisonResult:
        """
        Compare two payroll versions.

        Args:
            previous_version_id: ID of previous PayrollVersion
            current_version_id: ID of current PayrollVersion

        Returns:
            PayrollComparisonResult with factual deltas

        Raises:
            NotFoundError: If either version does not exist
            ValueError: If the versions belong to different employees
        """
        prev_version = self._repository.get_version(previous_version_id)
        if not prev_version:
            raise NotFoundError(
                f"Previous payroll version not found: {previous_version_id}"
            )

        curr_version = self._repository.get_version(current_version_id)
        if not curr_version:
            raise NotFoundError(
                f"Current payroll version not found: {current_version_id}"
            )

        # Verify same employee
        prev_payroll = self.session.get(Payroll, prev_version.payroll_id)
        curr_payroll = self.session.get(Payroll, curr_version.payroll_id)

        if prev_payroll.employee_id != curr_payroll.employee_id:
            raise ValueError("Payroll versions must be for the same employee")

        employee_id = prev_payroll.employee_id

        # NET
        prev_net = quantize_money(prev_version.net_pay)
        curr_net = quantize_money(curr_version.net_pay)
        net_delta = curr_net - prev_net
        net_delta_percent = percent_change(net_delta, prev_net)

        # EARNINGS
        prev_earnings = quantize_money(prev_version.total_earnings)
        curr_earnings = quantize_money(curr_version.total_earnings)
        earnings_delta = curr_earnings - prev_earnings
        earnings_delta_percent = percent_change(earnings_delta, prev_earnings)

        # DEDUCTIONS
        prev_deductions = quantize_money(prev_version.total_deductions)
        curr_deductions = quantize_money(curr_version.total_deductions)
        deductions_delta = curr_deductions - prev_deductions
        deductions_delta_percent = percent_change(deductions_delta, prev_deductions)

        # INCOME TAX
        prev_income_tax = quantize_money(prev_version.income_tax)
        curr_income_tax = quantize_money(curr_version.income_tax)
        income_tax_delta = curr_income_tax - prev_income_tax
        income_tax_delta_percent = percent_change(income_tax_delta, prev_income_tax)

        # ATTENDANCE
        prev_missing_days = quantize_days(prev_version.missing_days)
        curr_missing_days = quantize_days(curr_version.missing_days)
        missing_days_delta = curr_missing_days - prev_missing_days

        # CODE-LEVEL DELTAS
        earning_deltas = self._code_deltas(
            {e.code: e.amount for e in prev_version.earnings},
            {e.code: e.amount for e in curr_version.earnings},
        )
        deduction_deltas = self._code_deltas(
            {d.code: d.amount for d in prev_version.deductions},
            {d.code: d.amount for d in curr_version.deductions},
        )

        return PayrollComparisonResult(
            previous_payroll_version_id=previous_version_id,
            current_payroll_version_id=current_version_id,
            employee_id=employee_id,
            comparison_date=datetime.now(timezone.utc),
            previous_net=prev_net,
            current_net=curr_net,
            net_delta=net_delta,
            net_delta_percent=net_delta_percent,
            previous_total_earnings=prev_earnings,
            current_total_earnings=curr_earnings,
            earnings_delta=earnings_delta,
            earnings_delta_percent=earnings_delta_percent,
            previous_total_deductions=prev_deductions,
            current_total_deductions=curr_deductions,
            deductions_delta=deductions_delta,
            deductions_delta_percent=deductions_delta_percent,
            previous_income_tax=prev_income_tax,
            current_income_tax=curr_income_tax,
            income_tax_delta=income_tax_delta,
            income_tax_delta_percent=income_tax_delta_percent,
            previous_missing_days=prev_missing_days,
            current_missing_days=curr_missing_days,
            missing_days_delta=missing_days_delta,
            earning_deltas=earning_deltas,
            deduction_deltas=deduction_deltas,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _code_deltas(
        previous: dict[str, Decimal],
        current: dict[str, Decimal],
    ) -> dict[str, dict[str, Decimal]]:
        """
        Build per-code deltas across the union of both periods' codes.

        A code present in only one period is reported with 0.00 on the
        missing side, so that an added bonus or a dropped allowance shows
        up as a real delta rather than silently disappearing.
        """
        deltas: dict[str, dict[str, Decimal]] = {}

        for code in sorted(set(previous) | set(current)):
            prev_amount = quantize_money(previous.get(code, ZERO_MONEY))
            curr_amount = quantize_money(current.get(code, ZERO_MONEY))
            deltas[code] = {
                "previous": prev_amount,
                "current": curr_amount,
                "delta": curr_amount - prev_amount,
            }

        return deltas
