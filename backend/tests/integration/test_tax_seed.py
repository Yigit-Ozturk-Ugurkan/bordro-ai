"""
Integration tests for tax seed idempotency.

Tests verify:
- Running seed_tax_2026 creates the 2026 rule set, brackets, parameters.
- Running seed_tax_2026 a second time does not create duplicate rule sets,
  brackets, or parameters.
"""

from decimal import Decimal
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tax import (
    PayrollParameter,
    TaxBracket,
    TaxRuleSet,
)
from app.seeds import tax_2026_seed as tax_seed_module
from app.seeds.tax_2026_seed import (
    BRACKETS,
    PARAMETERS,
    RULE_SET_VERSION,
    seed_tax_2026,
)


class TestTaxSeedIdempotency:
    def test_seed_first_run_creates_records(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Exercise a genuine first run without deleting immutable historical
        # tax runs/records that may reference the normal development seed.
        isolated_version = f"TEST_TR_PAYROLL_2026_{uuid.uuid4().hex}"
        monkeypatch.setattr(
            tax_seed_module, "RULE_SET_VERSION", isolated_version,
        )

        result1 = seed_tax_2026(db_session)
        assert result1["rule_set"] == 1
        assert result1["brackets"] == len(BRACKETS)
        assert result1["parameters"] == len(PARAMETERS)

        # Check in DB
        rule_set = db_session.execute(
            select(TaxRuleSet).where(TaxRuleSet.version == isolated_version)
        ).scalar_one()
        assert rule_set is not None
        assert rule_set.status == "ACTIVE"

        bracket_count = db_session.scalar(
            select(func.count(TaxBracket.id)).where(
                TaxBracket.rule_set_id == rule_set.id
            )
        )
        assert bracket_count == 5

        param_count = db_session.scalar(
            select(func.count(PayrollParameter.id)).where(
                PayrollParameter.rule_set_id == rule_set.id
            )
        )
        assert param_count == 5

    def test_seed_second_run_is_idempotent_no_duplicates(self, db_session: Session) -> None:
        stmt = select(TaxRuleSet).where(TaxRuleSet.version == RULE_SET_VERSION)
        existing = db_session.execute(stmt).scalar_one_or_none()

        if existing is None:
            seed_tax_2026(db_session)

        # Second run
        result2 = seed_tax_2026(db_session)
        assert result2["rule_set"] == 0
        assert result2["brackets"] == 0
        assert result2["parameters"] == 0

        # Verify exact counts in DB
        rule_sets = db_session.execute(
            select(TaxRuleSet).where(TaxRuleSet.version == RULE_SET_VERSION)
        ).scalars().all()
        assert len(rule_sets) == 1

        rule_set_id = rule_sets[0].id
        brackets = db_session.execute(
            select(TaxBracket).where(TaxBracket.rule_set_id == rule_set_id)
        ).scalars().all()
        assert len(brackets) == 5

        parameters = db_session.execute(
            select(PayrollParameter).where(
                PayrollParameter.rule_set_id == rule_set_id
            )
        ).scalars().all()
        assert len(parameters) == 5
