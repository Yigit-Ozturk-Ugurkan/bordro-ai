from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollValidationCategory,
    PayrollValidationSeverity,
)
from app.services.imports.canonical_fields import CANONICAL_KEYS
from app.services.imports.payroll_validation_rules import (
    VALIDATION_RULES,
    ValidationContext,
    ValidationFinding,
)
from app.services.imports.payroll_validation_service import PayrollValidationService


def field(key, value_type, *, text=None, decimal=None, integer=None, date_value=None):
    return SimpleNamespace(
        id=uuid4(), effective_canonical_key=key, value_type=value_type,
        value_text=text, value_decimal=decimal, value_integer=integer,
        value_date=date_value,
    )


def rule(code):
    return next(item for item in VALIDATION_RULES if item.code == code)


def test_registry_is_code_owned_versioned_and_uses_canonical_inputs():
    assert len({item.code for item in VALIDATION_RULES}) == len(VALIDATION_RULES)
    assert all(item.version >= 1 and callable(item.validator) for item in VALIDATION_RULES)
    assert all(isinstance(item.category, PayrollValidationCategory) for item in VALIDATION_RULES)
    assert all(set(item.required_canonical_inputs) <= set(CANONICAL_KEYS)
               for item in VALIDATION_RULES)


def test_net_pay_uses_exact_decimal_and_reports_mismatch_and_missing():
    values = (
        field("total_earnings", PayrollCanonicalValueType.DECIMAL, decimal=Decimal("100000.00")),
        field("total_deductions", PayrollCanonicalValueType.DECIMAL, decimal=Decimal("25600.00")),
        field("net_pay", PayrollCanonicalValueType.DECIMAL, decimal=Decimal("74400.00")),
    )
    validator = rule("NET_PAY_RECONCILIATION")
    matched = validator.validator(ValidationContext(values), validator)[0]
    assert matched.severity == PayrollValidationSeverity.INFO
    assert matched.expected_value == matched.actual_value == "74400.00"

    values[2].value_decimal = Decimal("74399.99")
    mismatch = validator.validator(ValidationContext(values), validator)[0]
    assert mismatch.severity == PayrollValidationSeverity.ERROR
    assert mismatch.expected_value == "74400.00"
    assert mismatch.actual_value == "74399.99"

    missing = validator.validator(ValidationContext(values[:2]), validator)[0]
    assert missing.severity == PayrollValidationSeverity.INFO
    assert missing.details == {"applicability": "NOT_APPLICABLE"}


def test_period_identity_and_type_rules_are_defensive():
    period_rule = rule("PERIOD_VALIDITY")
    year = field("period_year", PayrollCanonicalValueType.INTEGER, integer=2026)
    month = field("period_month", PayrollCanonicalValueType.INTEGER, integer=9)
    assert period_rule.validator(ValidationContext((year, month)), period_rule)[0].severity == PayrollValidationSeverity.INFO
    month.value_integer = 0
    assert period_rule.validator(ValidationContext((year, month)), period_rule)[0].severity == PayrollValidationSeverity.BLOCKING
    month.value_integer = 13
    assert period_rule.validator(ValidationContext((year, month)), period_rule)[0].severity == PayrollValidationSeverity.BLOCKING
    year.value_integer = 0
    assert period_rule.validator(ValidationContext((year, month)), period_rule)[0].severity == PayrollValidationSeverity.BLOCKING

    identity_rule = rule("EMPLOYEE_IDENTITY")
    employee = field("employee_identifier", PayrollCanonicalValueType.IDENTIFIER, text="EMP-42")
    assert identity_rule.validator(ValidationContext((employee,)), identity_rule)[0].severity == PayrollValidationSeverity.BLOCKING
    resolved = ValidationContext((employee,), matching_employee_ids=(uuid4(),))
    assert identity_rule.validator(resolved, identity_rule)[0].severity == PayrollValidationSeverity.INFO

    type_rule = rule("SNAPSHOT_VALUE_TYPES")
    corrupt = field("period_year", PayrollCanonicalValueType.INTEGER, text="2026")
    assert type_rule.validator(ValidationContext((corrupt,)), type_rule)[0].severity == PayrollValidationSeverity.BLOCKING
    generic_date = field(None, PayrollCanonicalValueType.DATE, date_value=date(2026, 9, 1))
    assert type_rule.validator(ValidationContext((generic_date,)), type_rule) == []


def test_result_checksum_is_canonical_and_order_independent():
    findings = [
        ValidationFinding(
            code="B", version=1, category=PayrollValidationCategory.ARITHMETIC,
            severity=PayrollValidationSeverity.INFO, message="second",
            expected_value="74400.00", actual_value="74400.00",
            details={"z": "last", "a": "first"},
        ),
        ValidationFinding(
            code="A", version=1, category=PayrollValidationCategory.STRUCTURAL,
            severity=PayrollValidationSeverity.WARNING, message="first",
        ),
    ]
    checksum = PayrollValidationService.result_checksum(findings)
    assert checksum == PayrollValidationService.result_checksum(list(reversed(findings)))
    assert len(checksum) == 64
