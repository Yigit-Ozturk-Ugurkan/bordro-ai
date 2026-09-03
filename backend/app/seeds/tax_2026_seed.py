"""
Development/reference seed for 2026 Turkish payroll tax rules.

This script seeds the database with:
- TaxRuleSet: TR_PAYROLL_2026_V1
- 5 progressive income tax brackets for employment income
- 5 standard payroll parameters (minimum wage, SGK rates, etc.)

IMPORTANT:
- This seed is for DEVELOPMENT and REFERENCE purposes only.
- It is NOT a production data loader.
- Tax values should NOT be hard-coded in calculation logic.
  The calculation engine should always read from these DB records.
- The seed is IDEMPOTENT: running it multiple times will not create
  duplicates. It checks for existing data before inserting.

Usage:
    cd backend
    .venv\\Scripts\\python.exe -m app.seeds.tax_2026_seed

Source: 2026 Turkish income tax law, SGK parameters.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.tax import PayrollParameter, TaxBracket, TaxRuleSet

# Seed constants
RULE_SET_VERSION = "TR_PAYROLL_2026_V1"
JURISDICTION = "TR"
EFFECTIVE_FROM = date(2026, 1, 1)
EFFECTIVE_TO = date(2027, 1, 1)

# 2026 progressive income tax brackets for employment income
BRACKETS = [
    {
        "sort_order": 1,
        "lower_limit": Decimal("0.00"),
        "upper_limit": Decimal("190000.00"),
        "rate": Decimal("0.150000"),
        "base_tax_amount": Decimal("0.00"),
    },
    {
        "sort_order": 2,
        "lower_limit": Decimal("190000.00"),
        "upper_limit": Decimal("400000.00"),
        "rate": Decimal("0.200000"),
        "base_tax_amount": Decimal("28500.00"),
    },
    {
        "sort_order": 3,
        "lower_limit": Decimal("400000.00"),
        "upper_limit": Decimal("1500000.00"),
        "rate": Decimal("0.270000"),
        "base_tax_amount": Decimal("70500.00"),
    },
    {
        "sort_order": 4,
        "lower_limit": Decimal("1500000.00"),
        "upper_limit": Decimal("5300000.00"),
        "rate": Decimal("0.350000"),
        "base_tax_amount": Decimal("367500.00"),
    },
    {
        "sort_order": 5,
        "lower_limit": Decimal("5300000.00"),
        "upper_limit": None,
        "rate": Decimal("0.400000"),
        "base_tax_amount": Decimal("1697500.00"),
    },
]

# 2026 standard payroll parameters
PARAMETERS = [
    {
        "parameter_key": "MINIMUM_GROSS_WAGE",
        "decimal_value": Decimal("33030.000000"),
        "unit": "TRY",
    },
    {
        "parameter_key": "SGK_EMPLOYEE_RATE",
        "decimal_value": Decimal("0.140000"),
        "unit": "rate",
    },
    {
        "parameter_key": "UNEMPLOYMENT_EMPLOYEE_RATE",
        "decimal_value": Decimal("0.010000"),
        "unit": "rate",
    },
    {
        "parameter_key": "SGK_MONTHLY_EARNINGS_FLOOR",
        "decimal_value": Decimal("33030.000000"),
        "unit": "TRY",
    },
    {
        "parameter_key": "SGK_MONTHLY_EARNINGS_CEILING",
        "decimal_value": Decimal("297270.000000"),
        "unit": "TRY",
    },
]


def seed_tax_2026(session: Session) -> dict[str, int]:
    """
    Seed the 2026 Turkish payroll tax rules.

    Returns a dict with counts of created entities:
    {
        "rule_set": 0 or 1,
        "brackets": N,
        "parameters": N,
    }

    Idempotent: skips creation if rule set version already exists.
    """
    result = {"rule_set": 0, "brackets": 0, "parameters": 0}

    # Check if rule set already exists
    stmt = select(TaxRuleSet).where(TaxRuleSet.version == RULE_SET_VERSION)
    existing = session.execute(stmt).scalar_one_or_none()

    if existing is not None:
        print(f"[SEED] Rule set '{RULE_SET_VERSION}' already exists. Skipping.")
        return result

    # Create rule set
    rule_set = TaxRuleSet(
        id=uuid.uuid4(),
        jurisdiction=JURISDICTION,
        name="Türkiye Bordro Vergi Kuralları 2026",
        version=RULE_SET_VERSION,
        effective_from=EFFECTIVE_FROM,
        effective_to=EFFECTIVE_TO,
        source_reference="2026 Gelir Vergisi Kanunu / SGK Parametreleri",
        status="ACTIVE",
    )
    session.add(rule_set)
    session.flush()
    result["rule_set"] = 1
    print(f"[SEED] Created rule set: {RULE_SET_VERSION} (id={rule_set.id})")

    # Create tax brackets
    for bracket_data in BRACKETS:
        bracket = TaxBracket(
            id=uuid.uuid4(),
            rule_set_id=rule_set.id,
            income_type="EMPLOYMENT",
            effective_from=EFFECTIVE_FROM,
            effective_to=EFFECTIVE_TO,
            **bracket_data,
        )
        session.add(bracket)
        result["brackets"] += 1

    session.flush()
    print(f"[SEED] Created {result['brackets']} tax brackets.")

    # Create payroll parameters
    for param_data in PARAMETERS:
        param = PayrollParameter(
            id=uuid.uuid4(),
            rule_set_id=rule_set.id,
            effective_from=EFFECTIVE_FROM,
            effective_to=EFFECTIVE_TO,
            source_reference="2026 resmi gazete",
            **param_data,
        )
        session.add(param)
        result["parameters"] += 1

    session.flush()
    print(f"[SEED] Created {result['parameters']} payroll parameters.")

    session.commit()
    print("[SEED] Seed completed successfully.")
    return result


def main() -> None:
    """Entry point for running the seed as a module."""
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with SessionLocal() as session:
        seed_tax_2026(session)


if __name__ == "__main__":
    main()
