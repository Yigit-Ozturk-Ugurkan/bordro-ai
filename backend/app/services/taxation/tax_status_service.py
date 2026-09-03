"""
Tax Status Read Service V1.

Answers "where does this employee stand in the progressive tax schedule
right now?" by composing existing deterministic pieces:

    TaxCumulativeRecord  -> the cumulative taxable base (the ledger)
    TaxService           -> which rule set applies to the period
    TaxEngine            -> bracket resolution and distance arithmetic

It computes no tax figures of its own. Bracket thresholds and rates are
never hard-coded here; they come from TaxRuleSet/TaxBracket rows via the
engine, so a rule change is a data change.

This service is the ONE source of truth for tax-position data in the read
API. The dashboard consumes it rather than recomputing bracket state.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.exceptions import EmployeeNotFoundError, TaxRuleSetNotFoundError
from app.core.money import ZERO_MONEY, money_str, quantize_money
from app.models.tax import TaxCumulativeRecord
from app.repositories.payroll_repository import PayrollReadRepository
from app.services.taxation.tax_engine import TaxBracketInfo, TaxEngine
from app.services.taxation.tax_service import TaxService


@dataclass(frozen=True)
class BracketView:
    """A tax bracket as exposed by the read API."""

    sort_order: int
    lower_limit: Decimal
    upper_limit: Optional[Decimal]
    rate: Decimal

    @classmethod
    def from_info(cls, info: TaxBracketInfo) -> "BracketView":
        """Build a view from the engine's bracket info."""
        return cls(
            sort_order=info.sort_order,
            lower_limit=info.lower_limit,
            upper_limit=info.upper_limit,
            rate=info.rate,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "sort_order": self.sort_order,
            "lower_limit": money_str(self.lower_limit),
            # None upper_limit means the final, open-ended bracket.
            "upper_limit": money_str(self.upper_limit),
            "rate": str(self.rate),
        }


@dataclass(frozen=True)
class TaxStatusResult:
    """Complete progressive-tax position for an employee in a tax year."""

    employee_id: uuid.UUID
    tax_year: int
    period_month: Optional[int]
    monthly_taxable_base: Optional[Decimal]
    cumulative_taxable_base: Decimal
    current_bracket: Optional[BracketView]
    next_bracket: Optional[BracketView]
    distance_to_next_bracket: Optional[Decimal]
    rule_set_version: str

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "employee_id": str(self.employee_id),
            "tax_year": self.tax_year,
            "period_month": self.period_month,
            # None means "no payroll recorded for this month yet", which is
            # different from a base of 0.00.
            "monthly_taxable_base": money_str(self.monthly_taxable_base),
            "cumulative_taxable_base": money_str(self.cumulative_taxable_base),
            "current_bracket": (
                self.current_bracket.to_dict() if self.current_bracket else None
            ),
            # None means the employee is already in the final open-ended
            # bracket, so there is no next bracket to reach.
            "next_bracket": (
                self.next_bracket.to_dict() if self.next_bracket else None
            ),
            "distance_to_next_bracket": money_str(self.distance_to_next_bracket),
            "rule_set_version": self.rule_set_version,
        }


class TaxStatusService:
    """Read-only progressive tax position for an employee."""

    def __init__(
        self,
        session: Session,
        tax_engine: TaxEngine,
        tax_service: TaxService,
    ) -> None:
        self._session = session
        self._tax_engine = tax_engine
        self._tax_service = tax_service
        self._repository = PayrollReadRepository(session)

    def get_tax_status(
        self,
        employee_id: uuid.UUID,
        tax_year: int,
        period_month: Optional[int] = None,
        jurisdiction: str = "TR",
        income_type: str = "EMPLOYMENT",
    ) -> TaxStatusResult:
        """
        Resolve the employee's position in the progressive tax schedule.

        Args:
            employee_id: employee UUID
            tax_year: calendar year (e.g. 2026)
            period_month: optional month 1-12. When given, the status is
                reported as of that month; otherwise the latest recorded
                month in the year is used.
            jurisdiction: rule set jurisdiction (default 'TR')
            income_type: bracket income type (default 'EMPLOYMENT')

        Returns:
            TaxStatusResult

        Raises:
            EmployeeNotFoundError: if the employee does not exist
            TaxRuleSetNotFoundError: if no rule set covers the period
        """
        if not self._repository.employee_exists(employee_id):
            raise EmployeeNotFoundError(employee_id)

        record = self._get_cumulative_record(employee_id, tax_year, period_month)

        # An employee with no ledger entry yet is at the start of the year:
        # a cumulative base of zero, which still resolves to a real bracket.
        cumulative_base = (
            quantize_money(record.closing_cumulative_base)
            if record is not None
            else ZERO_MONEY
        )
        monthly_base = (
            quantize_money(record.monthly_taxable_base)
            if record is not None
            else None
        )
        effective_month = record.period_month if record is not None else period_month

        target_date = self._resolve_target_date(tax_year, effective_month)
        rule_set = self._tax_service.resolve_rule_set(target_date, jurisdiction)
        if rule_set is None:
            raise TaxRuleSetNotFoundError(
                f"No active tax rule set for {jurisdiction} on {target_date.isoformat()}"
            )

        brackets = self._tax_engine.get_brackets(rule_set.id, income_type)
        if not brackets:
            raise TaxRuleSetNotFoundError(
                f"Tax rule set {rule_set.version} has no {income_type} brackets"
            )

        current = self._tax_engine.get_current_bracket(cumulative_base, brackets)
        next_bracket = (
            self._tax_engine.get_next_bracket(current, brackets)
            if current is not None
            else None
        )
        distance = (
            self._tax_engine.calculate_distance_to_next_bracket(
                cumulative_base, current, next_bracket
            )
            if current is not None
            else None
        )

        return TaxStatusResult(
            employee_id=employee_id,
            tax_year=tax_year,
            period_month=effective_month,
            monthly_taxable_base=monthly_base,
            cumulative_taxable_base=cumulative_base,
            current_bracket=BracketView.from_info(current) if current else None,
            next_bracket=(
                BracketView.from_info(next_bracket) if next_bracket else None
            ),
            distance_to_next_bracket=distance,
            rule_set_version=rule_set.version,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_cumulative_record(
        self,
        employee_id: uuid.UUID,
        tax_year: int,
        period_month: Optional[int],
    ) -> Optional[TaxCumulativeRecord]:
        """
        Fetch the ledger entry that defines the reported position.

        With a month given, that exact month is used. Without one, the
        latest recorded month in the year is used. Records are append-only,
        so the newest row for a month (by created_at) is the live one.
        """
        stmt = select(TaxCumulativeRecord).where(
            TaxCumulativeRecord.employee_id == employee_id,
            TaxCumulativeRecord.tax_year == tax_year,
        )

        if period_month is not None:
            stmt = stmt.where(TaxCumulativeRecord.period_month == period_month)

        stmt = stmt.order_by(
            desc(TaxCumulativeRecord.period_month),
            desc(TaxCumulativeRecord.created_at),
        ).limit(1)

        return self._session.execute(stmt).scalars().first()

    @staticmethod
    def _resolve_target_date(tax_year: int, period_month: Optional[int]) -> date:
        """Pick the date used to resolve the effective rule set."""
        return date(tax_year, period_month or 1, 1)
