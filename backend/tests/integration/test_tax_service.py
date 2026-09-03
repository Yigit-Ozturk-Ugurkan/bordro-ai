"""
Integration tests for TaxService query and rule-resolution infrastructure.
"""

from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.tax import PayrollParameter, TaxBracket, TaxRuleSet
from app.seeds.tax_2026_seed import RULE_SET_VERSION, seed_tax_2026
from app.services.taxation.tax_service import TaxService


class TestTaxService:
    def test_get_rule_set_by_version(self, db_session: Session) -> None:
        seed_tax_2026(db_session)
        service = TaxService(db_session)

        rule_set = service.get_rule_set_by_version(RULE_SET_VERSION)
        assert rule_set is not None
        assert rule_set.version == RULE_SET_VERSION
        assert rule_set.jurisdiction == "TR"

        not_found = service.get_rule_set_by_version("NON_EXISTENT_VERSION")
        assert not_found is None

    def test_resolve_rule_set_active_date(self, db_session: Session) -> None:
        seed_tax_2026(db_session)
        service = TaxService(db_session)

        # 2026-06-15 is within [2026-01-01, 2027-01-01)
        rule_set = service.resolve_rule_set(date(2026, 6, 15), "TR")
        assert rule_set is not None
        assert rule_set.version == RULE_SET_VERSION

        # Out of bounds date
        old_rule_set = service.resolve_rule_set(date(2020, 1, 1), "TR")
        assert old_rule_set is None

    def test_get_tax_brackets_ordered(self, db_session: Session) -> None:
        seed_tax_2026(db_session)
        service = TaxService(db_session)

        rule_set = service.get_rule_set_by_version(RULE_SET_VERSION)
        assert rule_set is not None

        brackets = service.get_tax_brackets(rule_set.id, "EMPLOYMENT")
        assert len(brackets) == 5
        sort_orders = [b.sort_order for b in brackets]
        assert sort_orders == [1, 2, 3, 4, 5]

        assert brackets[0].rate == Decimal("0.150000")
        assert brackets[0].lower_limit == Decimal("0.00")
        assert brackets[0].upper_limit == Decimal("190000.00")
        assert brackets[4].upper_limit is None  # open ended

    def test_get_parameter_and_decimal(self, db_session: Session) -> None:
        seed_tax_2026(db_session)
        service = TaxService(db_session)

        rule_set = service.get_rule_set_by_version(RULE_SET_VERSION)
        assert rule_set is not None

        target_date = date(2026, 5, 1)
        param = service.get_parameter(rule_set.id, "MINIMUM_GROSS_WAGE", target_date)
        assert param is not None
        assert param.decimal_value == Decimal("33030.000000")

        val = service.get_parameter_decimal(rule_set.id, "SGK_EMPLOYEE_RATE", target_date)
        assert val == Decimal("0.140000")

        unknown = service.get_parameter_decimal(rule_set.id, "UNKNOWN_KEY", target_date)
        assert unknown is None
