"""
Tax Engine V1: deterministic progressive income tax calculation.

This engine calculates Turkish income tax based on cumulative taxable base
and progressive tax brackets. All calculations use Decimal for precision.

Key Design Principles:
- ALL tax calculations are deterministic and rule-based
- NO tax values are hard-coded in this module
- Tax brackets and rates are fetched from TaxRuleSet/TaxBracket
- Cumulative base tracking enables progressive tax application
- LLM will later explain results, not calculate them

Tax Calculation Method:
- Progressive taxation: tax = base_tax_of_bracket + (cumulative_base - lower_limit) * rate
- For each bracket, we apply the marginal rate only to the portion of income
  within that bracket's limits
- Effective tax rate = total_tax / monthly_taxable_base

Database Assumptions:
- TaxBracket records have correct base_tax_amount pre-calculated
- Brackets are ordered by sort_order and cover 0 to infinity
- Final bracket has upper_limit = NULL
- All rates and amounts use appropriate NUMERIC precision
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.tax import TaxBracket, TaxRuleSet
from app.services.taxation.tax_service import TaxService


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class TaxBracketInfo:
    """Immutable bracket information for tax calculation."""

    bracket_id: uuid.UUID
    income_type: str
    sort_order: int
    lower_limit: Decimal
    upper_limit: Decimal | None  # None for final open-ended bracket
    rate: Decimal
    base_tax_amount: Decimal


@dataclass
class TaxPositionResult:
    """
    Complete tax position for an employee's cumulative base.

    Fields:
    - taxable_base: closing cumulative taxable income (input)
    - calculated_tax: progressive tax on taxable_base
    - current_bracket: bracket containing taxable_base
    - next_bracket: next progressive bracket (or None if at highest)
    - distance_to_next_bracket: income needed to reach next bracket
    - effective_tax_rate: calculated_tax / monthly_taxable_base
    - rule_set_version: version string for audit trail
    """

    taxable_base: Decimal
    monthly_taxable_base: Decimal
    calculated_tax: Decimal
    current_bracket: TaxBracketInfo
    next_bracket: TaxBracketInfo | None
    distance_to_next_bracket: Decimal | None  # None if at final bracket
    effective_tax_rate: Decimal
    rule_set_version: str


# ============================================================================
# Tax Engine
# ============================================================================


class TaxEngine:
    """
    Progressive income tax calculation engine for Türkiye.

    Supports:
    - Multiple jurisdictions and rule sets
    - Effective dating (rule changes mid-year)
    - Bracket transitions and boundary cases
    - Audit trail via rule_set_version
    - Year-reset cumulative tracking (handled by caller)
    """

    def __init__(self, session: Session, tax_service: TaxService) -> None:
        """
        Initialize tax engine with database session and tax service.

        Args:
            session: SQLAlchemy session for database access
            tax_service: TaxService instance for rule resolution
        """
        self._session = session
        self._tax_service = tax_service

    # ========================================================================
    # Public API
    # ========================================================================

    def calculate_progressive_tax(
        self,
        closing_cumulative_base: Decimal,
        monthly_taxable_base: Decimal,
        rule_set: TaxRuleSet,
        income_type: str = "EMPLOYMENT",
        target_date: date | None = None,
    ) -> TaxPositionResult:
        """
        Calculate progressive income tax for a given cumulative base.

        This is the main entry point for tax calculation. It returns the
        complete tax position including current/next brackets and effective rate.

        Args:
            closing_cumulative_base: cumulative taxable income through this month
            monthly_taxable_base: this month's taxable income (for effective rate)
            rule_set: TaxRuleSet instance containing brackets
            income_type: income classification (default: 'EMPLOYMENT')
            target_date: optional date for bracket effective dating

        Returns:
            TaxPositionResult with complete tax information

        Raises:
            ValueError: if brackets are invalid or cumulative_base < 0
            RuntimeError: if no brackets found or tax calculation fails
        """
        if closing_cumulative_base < Decimal("0"):
            raise ValueError("closing_cumulative_base must be >= 0")

        if monthly_taxable_base < Decimal("0"):
            raise ValueError("monthly_taxable_base must be >= 0")

        # Get brackets for this rule set and income type
        brackets = self._get_sorted_brackets(
            rule_set.id, income_type, target_date
        )
        if not brackets:
            raise RuntimeError(
                f"No tax brackets found for {rule_set.version}, "
                f"income_type={income_type}"
            )

        # Find current bracket for the cumulative base
        current_bracket = self.get_current_bracket(closing_cumulative_base, brackets)
        if current_bracket is None:
            raise RuntimeError(
                f"Could not determine current bracket for base={closing_cumulative_base}"
            )

        # Calculate tax on cumulative base
        calculated_tax = self._calculate_bracket_tax(
            closing_cumulative_base, current_bracket, brackets
        )

        # Determine next bracket
        next_bracket = self.get_next_bracket(current_bracket, brackets)

        # Calculate distance to next bracket
        distance = self.calculate_distance_to_next_bracket(
            closing_cumulative_base, current_bracket, next_bracket
        )

        # Calculate effective tax rate
        if monthly_taxable_base > Decimal("0"):
            effective_rate = (calculated_tax / monthly_taxable_base).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            # Clamp to [0, 1] range in case of rounding edge cases
            effective_rate = max(
                Decimal("0"), min(Decimal("1"), effective_rate)
            )
        else:
            effective_rate = Decimal("0")

        return TaxPositionResult(
            taxable_base=closing_cumulative_base,
            monthly_taxable_base=monthly_taxable_base,
            calculated_tax=calculated_tax,
            current_bracket=current_bracket,
            next_bracket=next_bracket,
            distance_to_next_bracket=distance,
            effective_tax_rate=effective_rate,
            rule_set_version=rule_set.version,
        )

    def get_tax_position(
        self,
        closing_cumulative_base: Decimal,
        monthly_taxable_base: Decimal,
        rule_set: TaxRuleSet,
        income_type: str = "EMPLOYMENT",
        target_date: date | None = None,
    ) -> TaxPositionResult:
        """
        Alias for calculate_progressive_tax (public API consistency).

        Returns the complete tax position for an employee.
        """
        return self.calculate_progressive_tax(
            closing_cumulative_base,
            monthly_taxable_base,
            rule_set,
            income_type,
            target_date,
        )

    def get_brackets(
        self,
        rule_set_id: uuid.UUID,
        income_type: str = "EMPLOYMENT",
        target_date: date | None = None,
    ) -> list[TaxBracketInfo]:
        """
        Retrieve the bracket schedule for a rule set, ordered by sort_order.

        Public accessor for callers that need the schedule itself (for
        example the tax-status read service) rather than a calculation.
        """
        return self._get_sorted_brackets(rule_set_id, income_type, target_date)

    def get_current_bracket(
        self,
        taxable_base: Decimal,
        brackets: list[TaxBracketInfo] | None = None,
        rule_set_id: uuid.UUID | None = None,
        income_type: str = "EMPLOYMENT",
        target_date: date | None = None,
    ) -> TaxBracketInfo | None:
        """
        Find the bracket containing the given taxable base.

        Args:
            taxable_base: cumulative taxable income
            brackets: optional pre-fetched bracket list (for efficiency)
            rule_set_id: rule set UUID (if brackets not provided)
            income_type: income type (if brackets not provided)
            target_date: optional date filter

        Returns:
            TaxBracketInfo for the current bracket, or None if not found
        """
        if brackets is None:
            if rule_set_id is None:
                raise ValueError("Either brackets or rule_set_id must be provided")
            brackets = self._get_sorted_brackets(rule_set_id, income_type, target_date)

        # Find bracket where: lower_limit <= taxable_base < upper_limit
        for bracket in brackets:
            if taxable_base >= bracket.lower_limit:
                # Check upper limit
                if bracket.upper_limit is None or taxable_base < bracket.upper_limit:
                    return bracket
            else:
                # taxable_base < lower_limit: current bracket is before this one
                break

        return None

    def get_next_bracket(
        self,
        current_bracket: TaxBracketInfo,
        brackets: list[TaxBracketInfo] | None = None,
        rule_set_id: uuid.UUID | None = None,
        income_type: str = "EMPLOYMENT",
        target_date: date | None = None,
    ) -> TaxBracketInfo | None:
        """
        Find the next bracket after the current one.

        Args:
            current_bracket: current bracket info
            brackets: optional pre-fetched bracket list
            rule_set_id: rule set UUID (if brackets not provided)
            income_type: income type (if brackets not provided)
            target_date: optional date filter

        Returns:
            TaxBracketInfo for next bracket, or None if current is final
        """
        if brackets is None:
            if rule_set_id is None:
                raise ValueError("Either brackets or rule_set_id must be provided")
            brackets = self._get_sorted_brackets(rule_set_id, income_type, target_date)

        # Find next bracket by sort_order
        for bracket in brackets:
            if bracket.sort_order > current_bracket.sort_order:
                return bracket

        # No next bracket: current is final
        return None

    def calculate_distance_to_next_bracket(
        self,
        taxable_base: Decimal,
        current_bracket: TaxBracketInfo,
        next_bracket: TaxBracketInfo | None,
    ) -> Decimal | None:
        """
        Calculate how much income is needed to reach the next bracket.

        Returns:
        - Positive Decimal if there is a next bracket
        - None if current bracket is final (open-ended)
        - 0 if taxable_base is exactly at bracket boundary

        Args:
            taxable_base: current cumulative taxable income
            current_bracket: current bracket info
            next_bracket: next bracket info (or None if final)

        Returns:
            Distance to next bracket, or None if current is final
        """
        if next_bracket is None:
            # Current is final bracket (open-ended)
            return None

        # Distance = next_bracket.lower_limit - taxable_base
        # Can be negative if already past the threshold
        distance = next_bracket.lower_limit - taxable_base

        return max(Decimal("0"), distance)

    # ========================================================================
    # Private Implementation
    # ========================================================================

    def _get_sorted_brackets(
        self,
        rule_set_id: uuid.UUID,
        income_type: str,
        target_date: date | None = None,
    ) -> list[TaxBracketInfo]:
        """
        Retrieve and convert tax brackets to info objects.

        Returns:
            List of TaxBracketInfo ordered by sort_order
        """
        db_brackets = self._tax_service.get_tax_brackets(
            rule_set_id, income_type, target_date
        )

        return [
            TaxBracketInfo(
                bracket_id=b.id,
                income_type=b.income_type,
                sort_order=b.sort_order,
                lower_limit=b.lower_limit,
                upper_limit=b.upper_limit,
                rate=b.rate,
                base_tax_amount=b.base_tax_amount,
            )
            for b in db_brackets
        ]

    def _calculate_bracket_tax(
        self,
        taxable_base: Decimal,
        current_bracket: TaxBracketInfo,
        all_brackets: list[TaxBracketInfo],
    ) -> Decimal:
        """
        Calculate progressive tax for a cumulative base.

        Algorithm:
        1. Start with base_tax_amount from current bracket (tax from all lower brackets)
        2. Add marginal tax for this bracket: (taxable_base - lower_limit) * rate

        Returns:
            Calculated tax as Decimal
        """
        # Start with cumulative tax from all brackets below current
        tax = current_bracket.base_tax_amount

        # Add tax for income in current bracket
        income_in_bracket = taxable_base - current_bracket.lower_limit
        marginal_tax = income_in_bracket * current_bracket.rate

        # Total tax = base (from lower brackets) + marginal (this bracket)
        total_tax = tax + marginal_tax

        # Round to 2 decimal places (Turkish currency precision)
        return total_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
