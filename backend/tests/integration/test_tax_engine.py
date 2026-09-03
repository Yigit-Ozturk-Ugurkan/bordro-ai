"""
Tax Engine V1 boundary and integration tests.

Tests exhaustively cover bracket thresholds and edge cases using
actual rule data from the 2026 seed (TR_PAYROLL_2026_V1).

Tax brackets (employment income):
1. 0 - 190,000 @ 15% (base_tax = 0)
2. 190,000 - 400,000 @ 20% (base_tax = 28,500)
3. 400,000 - 1,500,000 @ 27% (base_tax = 70,500)
4. 1,500,000 - 5,300,000 @ 35% (base_tax = 367,500)
5. 5,300,000 - ∞ @ 40% (base_tax = 1,697,500)
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.employee import Employee
from app.models.tax import TaxRuleSet, TaxBracket
from app.services.taxation.tax_service import TaxService
from app.services.taxation.tax_engine import TaxEngine, TaxBracketInfo


@pytest.fixture
def tax_engine_with_2026_rules(
    db_session: Session,
) -> tuple[TaxEngine, TaxRuleSet]:
    """
    Fixture providing TaxEngine and 2026 rule set.

    Assumes seed has been run (test_tax_seed.py verifies this).
    """
    # Get 2026 rule set
    stmt = select(TaxRuleSet).where(TaxRuleSet.version == "TR_PAYROLL_2026_V1")
    rule_set = db_session.execute(stmt).scalar_one()

    tax_service = TaxService(db_session)
    engine = TaxEngine(db_session, tax_service)

    return engine, rule_set


class TestTaxEngineBracketBoundaries:
    """Test tax calculation at exact bracket thresholds."""

    def test_bracket_1_lower_boundary(self, tax_engine_with_2026_rules):
        """Test at bracket 1 lower limit (0)."""
        engine, rule_set = tax_engine_with_2026_rules

        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("0.00"),
            monthly_taxable_base=Decimal("1000.00"),
            rule_set=rule_set,
        )

        assert result.calculated_tax == Decimal("0.00")
        assert result.current_bracket.sort_order == 1
        assert result.next_bracket.sort_order == 2
        assert result.effective_tax_rate == Decimal("0.000000")

    def test_bracket_1_just_before_upper_limit(
        self, tax_engine_with_2026_rules
    ):
        """Test just before bracket 1 upper limit (189,999.99)."""
        engine, rule_set = tax_engine_with_2026_rules

        # Tax = 189,999.99 * 0.15 = 28,499.9985 ≈ 28,500.00 (ROUND_HALF_UP)
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("189999.99"),
            monthly_taxable_base=Decimal("189999.99"),
            rule_set=rule_set,
        )

        assert result.calculated_tax == Decimal("28500.00")  # Rounds up
        assert result.current_bracket.sort_order == 1

    def test_bracket_1_exactly_at_upper_limit(self, tax_engine_with_2026_rules):
        """Test exactly at bracket 1 upper limit (190,000).
        
        Note: Using [lower, upper) semantics, 190,000 falls into bracket 2.
        Tax = base_tax_of_bracket_2 + (190,000 - 190,000) * 0.20 = 28,500
        """
        engine, rule_set = tax_engine_with_2026_rules

        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("190000.00"),
            monthly_taxable_base=Decimal("190000.00"),
            rule_set=rule_set,
        )

        # At threshold, we enter bracket 2
        assert result.current_bracket.sort_order == 2
        assert result.calculated_tax == Decimal("28500.00")

    def test_bracket_2_just_after_lower_limit(self, tax_engine_with_2026_rules):
        """Test just after bracket 2 lower limit (190,000.01)."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 190,000.01: in bracket 2
        # Tax = 28,500 + (190,000.01 - 190,000) * 0.20
        #     = 28,500 + 0.01 * 0.20
        #     = 28,500.00 (rounded)
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("190000.01"),
            monthly_taxable_base=Decimal("190000.01"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 2
        assert result.calculated_tax == Decimal("28500.00")

    def test_bracket_2_middle_value(self, tax_engine_with_2026_rules):
        """Test mid-bracket in bracket 2 (300,000)."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 300,000: in bracket 2
        # Tax = 28,500 + (300,000 - 190,000) * 0.20
        #     = 28,500 + 110,000 * 0.20
        #     = 28,500 + 22,000
        #     = 50,500.00
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("300000.00"),
            monthly_taxable_base=Decimal("300000.00"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 2
        assert result.calculated_tax == Decimal("50500.00")

    def test_bracket_2_exactly_at_upper_limit(self, tax_engine_with_2026_rules):
        """Test exactly at bracket 2 upper limit (400,000).
        
        Note: Using [lower, upper) semantics, 400,000 falls into bracket 3.
        Tax = base_tax_of_bracket_3 + (400,000 - 400,000) * 0.27 = 70,500
        """
        engine, rule_set = tax_engine_with_2026_rules

        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("400000.00"),
            monthly_taxable_base=Decimal("400000.00"),
            rule_set=rule_set,
        )

        # At threshold, we enter bracket 3
        assert result.current_bracket.sort_order == 3
        assert result.calculated_tax == Decimal("70500.00")

    def test_bracket_3_just_after_lower_limit(self, tax_engine_with_2026_rules):
        """Test just after bracket 3 lower limit (400,000.01)."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 400,000.01: in bracket 3
        # Tax = 70,500 + (400,000.01 - 400,000) * 0.27
        #     = 70,500 + 0.01 * 0.27
        #     = 70,500.00 (rounded)
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("400000.01"),
            monthly_taxable_base=Decimal("400000.01"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 3
        assert result.calculated_tax == Decimal("70500.00")

    def test_bracket_3_middle_value(self, tax_engine_with_2026_rules):
        """Test mid-bracket in bracket 3 (900,000)."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 900,000: in bracket 3
        # Tax = 70,500 + (900,000 - 400,000) * 0.27
        #     = 70,500 + 500,000 * 0.27
        #     = 70,500 + 135,000
        #     = 205,500.00
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("900000.00"),
            monthly_taxable_base=Decimal("900000.00"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 3
        assert result.calculated_tax == Decimal("205500.00")

    def test_bracket_5_open_ended_high_value(self, tax_engine_with_2026_rules):
        """Test in final bracket (open-ended) at high value."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 10,000,000: in bracket 5 (open-ended)
        # Tax = 1,697,500 + (10,000,000 - 5,300,000) * 0.40
        #     = 1,697,500 + 4,700,000 * 0.40
        #     = 1,697,500 + 1,880,000
        #     = 3,577,500.00
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("10000000.00"),
            monthly_taxable_base=Decimal("10000000.00"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 5
        assert result.next_bracket is None
        assert result.calculated_tax == Decimal("3577500.00")
        assert result.distance_to_next_bracket is None

    def test_progressive_continuity_across_bracket_2_to_3(
        self, tax_engine_with_2026_rules
    ):
        """Test progressive tax continuity when crossing from bracket 2 to 3."""
        engine, rule_set = tax_engine_with_2026_rules

        tax_at_boundary = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("400000.00"),
            monthly_taxable_base=Decimal("400000.00"),
            rule_set=rule_set,
        )

        tax_just_after = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("400000.01"),
            monthly_taxable_base=Decimal("400000.01"),
            rule_set=rule_set,
        )

        # Just after should be slightly more than at boundary
        assert tax_just_after.calculated_tax >= tax_at_boundary.calculated_tax


class TestTaxEngineBracketSelection:
    """Test get_current_bracket and get_next_bracket methods."""

    def test_get_current_bracket_bracket_1(self, tax_engine_with_2026_rules):
        """Test current bracket detection in bracket 1."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        bracket = engine.get_current_bracket(Decimal("100000.00"), brackets)

        assert bracket.sort_order == 1
        assert bracket.lower_limit == Decimal("0.00")
        assert bracket.upper_limit == Decimal("190000.00")

    def test_get_current_bracket_bracket_3(self, tax_engine_with_2026_rules):
        """Test current bracket detection in bracket 3."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        bracket = engine.get_current_bracket(Decimal("900000.00"), brackets)

        assert bracket.sort_order == 3
        assert bracket.lower_limit == Decimal("400000.00")
        assert bracket.upper_limit == Decimal("1500000.00")

    def test_get_current_bracket_final_open_ended(
        self, tax_engine_with_2026_rules
    ):
        """Test current bracket detection in final open-ended bracket."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        bracket = engine.get_current_bracket(Decimal("10000000.00"), brackets)

        assert bracket.sort_order == 5
        assert bracket.upper_limit is None

    def test_get_next_bracket_from_bracket_1(
        self, tax_engine_with_2026_rules
    ):
        """Test next bracket from bracket 1."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        current = engine.get_current_bracket(Decimal("100000.00"), brackets)
        next_bracket = engine.get_next_bracket(current, brackets)

        assert next_bracket.sort_order == 2
        assert next_bracket.lower_limit == Decimal("190000.00")

    def test_get_next_bracket_from_final_bracket_returns_none(
        self, tax_engine_with_2026_rules
    ):
        """Test next bracket from final bracket returns None."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        current = engine.get_current_bracket(Decimal("10000000.00"), brackets)
        next_bracket = engine.get_next_bracket(current, brackets)

        assert next_bracket is None


class TestTaxEngineDistanceCalculation:
    """Test distance to next bracket calculations."""

    def test_distance_in_bracket_1(self, tax_engine_with_2026_rules):
        """Test distance to next bracket from within bracket 1."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        current = engine.get_current_bracket(Decimal("100000.00"), brackets)
        next_bracket = engine.get_next_bracket(current, brackets)
        distance = engine.calculate_distance_to_next_bracket(
            Decimal("100000.00"), current, next_bracket
        )

        # Distance = 190,000 - 100,000 = 90,000
        assert distance == Decimal("90000.00")

    def test_distance_at_bracket_boundary(self, tax_engine_with_2026_rules):
        """Test distance when exactly at bracket threshold."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        current = engine.get_current_bracket(Decimal("190000.00"), brackets)
        next_bracket = engine.get_next_bracket(current, brackets)
        distance = engine.calculate_distance_to_next_bracket(
            Decimal("190000.00"), current, next_bracket
        )

        # Distance = 400,000 - 190,000 = 210,000
        assert distance == Decimal("210000.00")

    def test_distance_from_final_bracket_returns_none(
        self, tax_engine_with_2026_rules
    ):
        """Test distance from final bracket returns None."""
        engine, rule_set = tax_engine_with_2026_rules

        brackets = engine._get_sorted_brackets(rule_set.id, "EMPLOYMENT")
        current = engine.get_current_bracket(Decimal("10000000.00"), brackets)
        next_bracket = engine.get_next_bracket(current, brackets)
        distance = engine.calculate_distance_to_next_bracket(
            Decimal("10000000.00"), current, next_bracket
        )

        assert distance is None


class TestTaxEngineEffectiveRate:
    """Test effective tax rate calculations."""

    def test_effective_rate_bracket_1(self, tax_engine_with_2026_rules):
        """Test effective rate in bracket 1."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 100,000: tax = 100,000 * 0.15 = 15,000
        # effective_rate = 15,000 / 100,000 = 0.15
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("100000.00"),
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )

        assert result.effective_tax_rate == Decimal("0.150000")

    def test_effective_rate_bracket_3(self, tax_engine_with_2026_rules):
        """Test effective rate increases in bracket 3."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 900,000: tax = 205,500
        # effective_rate = 205,500 / 900,000 ≈ 0.228333
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("900000.00"),
            monthly_taxable_base=Decimal("900000.00"),
            rule_set=rule_set,
        )

        # 205500 / 900000 = 0.2283333...
        expected = (Decimal("205500") / Decimal("900000")).quantize(
            Decimal("0.000001")
        )
        assert result.effective_tax_rate == expected

    def test_effective_rate_zero_monthly_base(
        self, tax_engine_with_2026_rules
    ):
        """Test effective rate when monthly base is 0 (edge case)."""
        engine, rule_set = tax_engine_with_2026_rules

        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("100000.00"),
            monthly_taxable_base=Decimal("0.00"),
            rule_set=rule_set,
        )

        # Rate should be 0 when monthly base is 0
        assert result.effective_tax_rate == Decimal("0.000000")


class TestTaxEngineEdgeCases:
    """Test edge cases and error conditions."""

    def test_zero_cumulative_base(self, tax_engine_with_2026_rules):
        """Test with zero cumulative base."""
        engine, rule_set = tax_engine_with_2026_rules

        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("0.00"),
            monthly_taxable_base=Decimal("0.00"),
            rule_set=rule_set,
        )

        assert result.calculated_tax == Decimal("0.00")
        assert result.effective_tax_rate == Decimal("0.000000")

    def test_negative_cumulative_base_raises_error(
        self, tax_engine_with_2026_rules
    ):
        """Test that negative cumulative base raises ValueError."""
        engine, rule_set = tax_engine_with_2026_rules

        with pytest.raises(ValueError, match="closing_cumulative_base must be >= 0"):
            engine.calculate_progressive_tax(
                closing_cumulative_base=Decimal("-1000.00"),
                monthly_taxable_base=Decimal("1000.00"),
                rule_set=rule_set,
            )

    def test_negative_monthly_base_raises_error(
        self, tax_engine_with_2026_rules
    ):
        """Test that negative monthly base raises ValueError."""
        engine, rule_set = tax_engine_with_2026_rules

        with pytest.raises(ValueError, match="monthly_taxable_base must be >= 0"):
            engine.calculate_progressive_tax(
                closing_cumulative_base=Decimal("100000.00"),
                monthly_taxable_base=Decimal("-1000.00"),
                rule_set=rule_set,
            )

    def test_get_tax_position_alias(self, tax_engine_with_2026_rules):
        """Test that get_tax_position is an alias for calculate_progressive_tax."""
        engine, rule_set = tax_engine_with_2026_rules

        result1 = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("100000.00"),
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )

        result2 = engine.get_tax_position(
            closing_cumulative_base=Decimal("100000.00"),
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )

        assert result1.calculated_tax == result2.calculated_tax
        assert result1.effective_tax_rate == result2.effective_tax_rate


class TestTaxEngineMultipleBracketCrossing:
    """Test calculations that span multiple brackets."""

    def test_cross_from_bracket_1_to_2(self, tax_engine_with_2026_rules):
        """Test crossing from bracket 1 to bracket 2."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 200,000: spans brackets 1 and 2
        # Bracket 1: 0-190,000 @ 15%
        # Bracket 2: 190,000-200,000 @ 20%
        # Tax = (190,000 * 0.15) + ((200,000 - 190,000) * 0.20)
        #     = 28,500 + (10,000 * 0.20)
        #     = 28,500 + 2,000
        #     = 30,500.00
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("200000.00"),
            monthly_taxable_base=Decimal("200000.00"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 2
        assert result.calculated_tax == Decimal("30500.00")

    def test_cross_multiple_brackets_from_1_to_4(
        self, tax_engine_with_2026_rules
    ):
        """Test crossing from bracket 1 all the way to bracket 4."""
        engine, rule_set = tax_engine_with_2026_rules

        # At 2,000,000: spans brackets 1-4
        # Tax = (190k * 0.15) + (210k * 0.20) + (1.1M * 0.27) + (0.5M * 0.35)
        #     = 28,500 + 42,000 + 297,000 + 175,000
        #     = 542,500.00
        result = engine.calculate_progressive_tax(
            closing_cumulative_base=Decimal("2000000.00"),
            monthly_taxable_base=Decimal("2000000.00"),
            rule_set=rule_set,
        )

        assert result.current_bracket.sort_order == 4
        expected_tax = (
            Decimal("190000.00") * Decimal("0.15")
            + Decimal("210000.00") * Decimal("0.20")
            + Decimal("1100000.00") * Decimal("0.27")
            + Decimal("500000.00") * Decimal("0.35")
        )
        assert result.calculated_tax == expected_tax
