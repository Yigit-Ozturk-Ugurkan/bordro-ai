"""
Unit tests for tax domain Pydantic schemas.

Tests cover:
- TaxRuleSetBase / Create / Read validation
- TaxBracketBase / Create / Read validation
- PayrollParameterBase / Create / Read validation
- TaxCalculationRunBase / Create / Read validation
- TaxCumulativeRecordBase / Create / Read validation
"""

from datetime import date
from decimal import Decimal
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.tax import (
    PayrollParameterBase,
    PayrollParameterCreate,
    TaxBracketBase,
    TaxBracketCreate,
    TaxCalculationRunBase,
    TaxCalculationRunCreate,
    TaxCumulativeRecordBase,
    TaxCumulativeRecordCreate,
    TaxRuleSetBase,
    TaxRuleSetCreate,
)


class TestTaxRuleSetSchemas:
    def test_valid_rule_set_schema(self) -> None:
        data = {
            "jurisdiction": "TR",
            "name": "Türkiye Bordro Vergi Kuralları 2026",
            "version": "TR_PAYROLL_2026_V1",
            "effective_from": date(2026, 1, 1),
            "effective_to": date(2027, 1, 1),
            "source_reference": "Gelir Vergisi Kanunu",
            "status": "ACTIVE",
        }
        schema = TaxRuleSetCreate(**data)
        assert schema.version == "TR_PAYROLL_2026_V1"
        assert schema.effective_to == date(2027, 1, 1)

    def test_open_ended_rule_set_schema(self) -> None:
        data = {
            "jurisdiction": "TR",
            "name": "Türkiye Bordro Vergi Kuralları 2026",
            "version": "TR_PAYROLL_2026_V1",
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
            "status": "ACTIVE",
        }
        schema = TaxRuleSetCreate(**data)
        assert schema.effective_to is None

    def test_invalid_effective_date_range_schema(self) -> None:
        data = {
            "jurisdiction": "TR",
            "name": "Türkiye Bordro Vergi Kuralları 2026",
            "version": "TR_PAYROLL_2026_V1",
            "effective_from": date(2026, 1, 1),
            "effective_to": date(2025, 1, 1),
            "status": "ACTIVE",
        }
        with pytest.raises(ValidationError, match="effective_to must be after effective_from"):
            TaxRuleSetCreate(**data)

    def test_effective_to_equal_effective_from_schema(self) -> None:
        data = {
            "jurisdiction": "TR",
            "name": "Türkiye Bordro Vergi Kuralları 2026",
            "version": "TR_PAYROLL_2026_V1",
            "effective_from": date(2026, 1, 1),
            "effective_to": date(2026, 1, 1),
            "status": "ACTIVE",
        }
        with pytest.raises(ValidationError, match="effective_to must be after effective_from"):
            TaxRuleSetCreate(**data)


class TestTaxBracketSchemas:
    def test_valid_bracket_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "effective_to": date(2027, 1, 1),
            "lower_limit": Decimal("0.00"),
            "upper_limit": Decimal("190000.00"),
            "rate": Decimal("0.150000"),
            "base_tax_amount": Decimal("0.00"),
            "sort_order": 1,
        }
        schema = TaxBracketCreate(**data)
        assert schema.lower_limit == Decimal("0.00")
        assert schema.rate == Decimal("0.150000")

    def test_valid_open_ended_final_bracket_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
            "lower_limit": Decimal("5300000.00"),
            "upper_limit": None,
            "rate": Decimal("0.400000"),
            "base_tax_amount": Decimal("1697500.00"),
            "sort_order": 5,
        }
        schema = TaxBracketCreate(**data)
        assert schema.upper_limit is None

    def test_negative_lower_limit_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "lower_limit": Decimal("-10.00"),
            "upper_limit": Decimal("190000.00"),
            "rate": Decimal("0.150000"),
            "base_tax_amount": Decimal("0.00"),
            "sort_order": 1,
        }
        with pytest.raises(ValidationError):
            TaxBracketCreate(**data)

    def test_upper_lte_lower_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "lower_limit": Decimal("200000.00"),
            "upper_limit": Decimal("100000.00"),
            "rate": Decimal("0.150000"),
            "base_tax_amount": Decimal("0.00"),
            "sort_order": 1,
        }
        with pytest.raises(ValidationError, match="upper_limit must be greater than lower_limit"):
            TaxBracketCreate(**data)

    def test_rate_negative_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "lower_limit": Decimal("0.00"),
            "upper_limit": Decimal("190000.00"),
            "rate": Decimal("-0.01"),
            "base_tax_amount": Decimal("0.00"),
            "sort_order": 1,
        }
        with pytest.raises(ValidationError):
            TaxBracketCreate(**data)

    def test_rate_greater_than_one_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "lower_limit": Decimal("0.00"),
            "upper_limit": Decimal("190000.00"),
            "rate": Decimal("1.01"),
            "base_tax_amount": Decimal("0.00"),
            "sort_order": 1,
        }
        with pytest.raises(ValidationError):
            TaxBracketCreate(**data)

    def test_negative_base_tax_schema(self) -> None:
        data = {
            "income_type": "EMPLOYMENT",
            "effective_from": date(2026, 1, 1),
            "lower_limit": Decimal("0.00"),
            "upper_limit": Decimal("190000.00"),
            "rate": Decimal("0.15"),
            "base_tax_amount": Decimal("-10.00"),
            "sort_order": 1,
        }
        with pytest.raises(ValidationError):
            TaxBracketCreate(**data)


class TestPayrollParameterSchemas:
    def test_valid_decimal_parameter_schema(self) -> None:
        data = {
            "parameter_key": "MINIMUM_GROSS_WAGE",
            "effective_from": date(2026, 1, 1),
            "decimal_value": Decimal("33030.00"),
            "unit": "TRY",
        }
        schema = PayrollParameterCreate(**data)
        assert schema.decimal_value == Decimal("33030.00")
        assert schema.text_value is None

    def test_valid_text_parameter_schema(self) -> None:
        data = {
            "parameter_key": "DEFAULT_TAX_CODE",
            "effective_from": date(2026, 1, 1),
            "decimal_value": None,
            "text_value": "TR_STD",
        }
        schema = PayrollParameterCreate(**data)
        assert schema.text_value == "TR_STD"

    def test_both_decimal_and_text_null_schema_rejected(self) -> None:
        data = {
            "parameter_key": "INVALID_KEY",
            "effective_from": date(2026, 1, 1),
            "decimal_value": None,
            "text_value": None,
        }
        with pytest.raises(ValidationError, match="At least one of decimal_value or text_value must be provided"):
            PayrollParameterCreate(**data)

    def test_invalid_effective_date_schema_rejected(self) -> None:
        data = {
            "parameter_key": "MINIMUM_GROSS_WAGE",
            "effective_from": date(2026, 6, 1),
            "effective_to": date(2026, 1, 1),
            "decimal_value": Decimal("33030.00"),
        }
        with pytest.raises(ValidationError, match="effective_to must be after effective_from"):
            PayrollParameterCreate(**data)


class TestTaxCalculationRunSchemas:
    def test_valid_run_schema(self) -> None:
        data = {
            "organization_id": uuid.uuid4(),
            "employee_id": uuid.uuid4(),
            "rule_set_id": uuid.uuid4(),
            "tax_year": 2026,
            "trigger_type": "MONTHLY_PAYROLL",
            "status": "COMPLETED",
            "calculation_version": "1.0.0",
        }
        schema = TaxCalculationRunCreate(**data)
        assert schema.tax_year == 2026

    def test_invalid_tax_year_schema_rejected(self) -> None:
        data = {
            "organization_id": uuid.uuid4(),
            "employee_id": uuid.uuid4(),
            "rule_set_id": uuid.uuid4(),
            "tax_year": 1999,  # < 2000
            "trigger_type": "MONTHLY_PAYROLL",
            "status": "COMPLETED",
            "calculation_version": "1.0.0",
        }
        with pytest.raises(ValidationError):
            TaxCalculationRunCreate(**data)


class TestTaxCumulativeRecordSchemas:
    def test_valid_cumulative_record_schema(self) -> None:
        data = {
            "employee_id": uuid.uuid4(),
            "payroll_version_id": uuid.uuid4(),
            "tax_year": 2026,
            "period_month": 1,
            "opening_cumulative_base": Decimal("0.00"),
            "monthly_taxable_base": Decimal("30000.00"),
            "closing_cumulative_base": Decimal("30000.00"),
            "gross_calculated_tax": Decimal("4500.00"),
            "tax_exemptions": Decimal("0.00"),
            "withholding_tax": Decimal("4500.00"),
            "effective_tax_rate": Decimal("0.150000"),
        }
        schema = TaxCumulativeRecordCreate(**data)
        assert schema.period_month == 1
        assert schema.closing_cumulative_base == Decimal("30000.00")

    @pytest.mark.parametrize("invalid_month", [0, 13, -1])
    def test_invalid_period_month_schema_rejected(self, invalid_month: int) -> None:
        data = {
            "employee_id": uuid.uuid4(),
            "payroll_version_id": uuid.uuid4(),
            "tax_year": 2026,
            "period_month": invalid_month,
            "opening_cumulative_base": Decimal("0.00"),
            "monthly_taxable_base": Decimal("30000.00"),
            "closing_cumulative_base": Decimal("30000.00"),
            "gross_calculated_tax": Decimal("4500.00"),
            "tax_exemptions": Decimal("0.00"),
            "withholding_tax": Decimal("4500.00"),
            "effective_tax_rate": Decimal("0.150000"),
        }
        with pytest.raises(ValidationError):
            TaxCumulativeRecordCreate(**data)

    def test_closing_less_than_opening_schema_rejected(self) -> None:
        data = {
            "employee_id": uuid.uuid4(),
            "payroll_version_id": uuid.uuid4(),
            "tax_year": 2026,
            "period_month": 1,
            "opening_cumulative_base": Decimal("50000.00"),
            "monthly_taxable_base": Decimal("30000.00"),
            "closing_cumulative_base": Decimal("30000.00"),  # < opening
            "gross_calculated_tax": Decimal("4500.00"),
            "tax_exemptions": Decimal("0.00"),
            "withholding_tax": Decimal("4500.00"),
            "effective_tax_rate": Decimal("0.150000"),
        }
        with pytest.raises(ValidationError, match="closing_cumulative_base must be >= opening_cumulative_base"):
            TaxCumulativeRecordCreate(**data)

    def test_negative_monetary_values_schema_rejected(self) -> None:
        base_data = {
            "employee_id": uuid.uuid4(),
            "payroll_version_id": uuid.uuid4(),
            "tax_year": 2026,
            "period_month": 1,
            "opening_cumulative_base": Decimal("0.00"),
            "monthly_taxable_base": Decimal("30000.00"),
            "closing_cumulative_base": Decimal("30000.00"),
            "gross_calculated_tax": Decimal("4500.00"),
            "tax_exemptions": Decimal("0.00"),
            "withholding_tax": Decimal("4500.00"),
            "effective_tax_rate": Decimal("0.150000"),
        }

        for field in [
            "opening_cumulative_base",
            "monthly_taxable_base",
            "closing_cumulative_base",
            "gross_calculated_tax",
            "tax_exemptions",
            "withholding_tax",
        ]:
            bad_data = base_data.copy()
            bad_data[field] = Decimal("-1.00")
            with pytest.raises(ValidationError):
                TaxCumulativeRecordCreate(**bad_data)

    def test_effective_rate_outside_range_schema_rejected(self) -> None:
        base_data = {
            "employee_id": uuid.uuid4(),
            "payroll_version_id": uuid.uuid4(),
            "tax_year": 2026,
            "period_month": 1,
            "opening_cumulative_base": Decimal("0.00"),
            "monthly_taxable_base": Decimal("30000.00"),
            "closing_cumulative_base": Decimal("30000.00"),
            "gross_calculated_tax": Decimal("4500.00"),
            "tax_exemptions": Decimal("0.00"),
            "withholding_tax": Decimal("4500.00"),
        }

        # rate < 0
        with pytest.raises(ValidationError):
            TaxCumulativeRecordCreate(**{**base_data, "effective_tax_rate": Decimal("-0.01")})

        # rate > 1
        with pytest.raises(ValidationError):
            TaxCumulativeRecordCreate(**{**base_data, "effective_tax_rate": Decimal("1.01")})
