"""
Integration tests for tax domain models:
- TaxRuleSet
- TaxBracket
- PayrollParameter
- TaxCalculationRun
- TaxCumulativeRecord

Tests cover:
- Database CHECK constraint enforcement
- Database UNIQUE constraint enforcement
- Foreign key CASCADE and RESTRICT behavior
- Relationship loading and data integrity
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.organization import Organization
from app.models.payroll import PayrollVersion
from app.models.tax import (
    PayrollParameter,
    TaxBracket,
    TaxCalculationRun,
    TaxCumulativeRecord,
    TaxRuleSet,
)


# ===================================================================
# Helper factory functions
# ===================================================================


def _make_rule_set(
    *,
    jurisdiction: str = "TR",
    name: str = "Türkiye Bordro Vergi Kuralları 2026",
    version: str | None = None,
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = date(2027, 1, 1),
    source_reference: str | None = "2026 Gelir Vergisi Kanunu",
    status: str = "ACTIVE",
) -> TaxRuleSet:
    return TaxRuleSet(
        id=uuid.uuid4(),
        jurisdiction=jurisdiction,
        name=name,
        version=version or f"TR_PAYROLL_{uuid.uuid4().hex[:8].upper()}",
        effective_from=effective_from,
        effective_to=effective_to,
        source_reference=source_reference,
        status=status,
    )


def _make_bracket(
    rule_set_id: uuid.UUID,
    *,
    income_type: str = "EMPLOYMENT",
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = date(2027, 1, 1),
    lower_limit: Decimal = Decimal("0.00"),
    upper_limit: Decimal | None = Decimal("190000.00"),
    rate: Decimal = Decimal("0.150000"),
    base_tax_amount: Decimal = Decimal("0.00"),
    sort_order: int = 1,
) -> TaxBracket:
    return TaxBracket(
        id=uuid.uuid4(),
        rule_set_id=rule_set_id,
        income_type=income_type,
        effective_from=effective_from,
        effective_to=effective_to,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
        rate=rate,
        base_tax_amount=base_tax_amount,
        sort_order=sort_order,
    )


def _make_parameter(
    rule_set_id: uuid.UUID,
    *,
    parameter_key: str = "MINIMUM_GROSS_WAGE",
    effective_from: date = date(2026, 1, 1),
    effective_to: date | None = date(2027, 1, 1),
    decimal_value: Decimal | None = Decimal("33030.000000"),
    text_value: str | None = None,
    unit: str | None = "TRY",
    source_reference: str | None = "2026 Resmi Gazete",
) -> PayrollParameter:
    return PayrollParameter(
        id=uuid.uuid4(),
        rule_set_id=rule_set_id,
        parameter_key=parameter_key,
        effective_from=effective_from,
        effective_to=effective_to,
        decimal_value=decimal_value,
        text_value=text_value,
        unit=unit,
        source_reference=source_reference,
    )


def _make_calc_run(
    organization_id: uuid.UUID,
    employee_id: uuid.UUID,
    rule_set_id: uuid.UUID,
    *,
    tax_year: int = 2026,
    trigger_type: str = "MONTHLY_PAYROLL",
    status: str = "COMPLETED",
    calculation_version: str = "1.0.0",
) -> TaxCalculationRun:
    return TaxCalculationRun(
        id=uuid.uuid4(),
        organization_id=organization_id,
        employee_id=employee_id,
        rule_set_id=rule_set_id,
        tax_year=tax_year,
        trigger_type=trigger_type,
        status=status,
        calculation_version=calculation_version,
    )


def _make_cumulative_record(
    calculation_run_id: uuid.UUID,
    employee_id: uuid.UUID,
    payroll_version_id: uuid.UUID,
    *,
    tax_year: int = 2026,
    period_month: int = 1,
    opening_cumulative_base: Decimal = Decimal("0.00"),
    monthly_taxable_base: Decimal = Decimal("30000.00"),
    closing_cumulative_base: Decimal = Decimal("30000.00"),
    gross_calculated_tax: Decimal = Decimal("4500.00"),
    tax_exemptions: Decimal = Decimal("0.00"),
    withholding_tax: Decimal = Decimal("4500.00"),
    effective_tax_rate: Decimal = Decimal("0.150000"),
) -> TaxCumulativeRecord:
    return TaxCumulativeRecord(
        id=uuid.uuid4(),
        calculation_run_id=calculation_run_id,
        employee_id=employee_id,
        payroll_version_id=payroll_version_id,
        tax_year=tax_year,
        period_month=period_month,
        opening_cumulative_base=opening_cumulative_base,
        monthly_taxable_base=monthly_taxable_base,
        closing_cumulative_base=closing_cumulative_base,
        gross_calculated_tax=gross_calculated_tax,
        tax_exemptions=tax_exemptions,
        withholding_tax=withholding_tax,
        effective_tax_rate=effective_tax_rate,
    )


# ===================================================================
# TaxRuleSet Tests
# ===================================================================


class TestTaxRuleSetModel:
    def test_create_valid_tax_rule_set(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        saved = db_session.get(TaxRuleSet, rule_set.id)
        assert saved is not None
        assert saved.jurisdiction == "TR"
        assert saved.status == "ACTIVE"
        assert saved.effective_to == date(2027, 1, 1)

    def test_invalid_effective_date_range_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set(
            effective_from=date(2026, 1, 1),
            effective_to=date(2025, 1, 1),  # effective_to < effective_from
        )
        db_session.add(rule_set)
        with pytest.raises(IntegrityError, match="ck_tax_rule_set_effective_range"):
            db_session.flush()

    def test_effective_to_equal_effective_from_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set(
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 1, 1),  # effective_to == effective_from
        )
        db_session.add(rule_set)
        with pytest.raises(IntegrityError, match="ck_tax_rule_set_effective_range"):
            db_session.flush()

    def test_open_ended_effective_date_accepted(self, db_session: Session) -> None:
        rule_set = _make_rule_set(effective_to=None)
        db_session.add(rule_set)
        db_session.flush()

        saved = db_session.get(TaxRuleSet, rule_set.id)
        assert saved is not None
        assert saved.effective_to is None

    def test_duplicate_version_rejected(self, db_session: Session) -> None:
        version_code = f"TR_RULE_{uuid.uuid4().hex[:8]}"
        rs1 = _make_rule_set(version=version_code)
        rs2 = _make_rule_set(version=version_code)

        db_session.add(rs1)
        db_session.flush()

        db_session.add(rs2)
        with pytest.raises(IntegrityError, match="uq_tax_rule_set_version"):
            db_session.flush()


# ===================================================================
# TaxBracket Tests
# ===================================================================


class TestTaxBracketModel:
    def test_valid_bracket_creation(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(rule_set.id, sort_order=1)
        db_session.add(bracket)
        db_session.flush()

        saved = db_session.get(TaxBracket, bracket.id)
        assert saved is not None
        assert saved.rate == Decimal("0.150000")
        assert saved.rule_set_id == rule_set.id

    def test_valid_open_ended_final_bracket(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(
            rule_set.id,
            lower_limit=Decimal("5300000.00"),
            upper_limit=None,
            rate=Decimal("0.400000"),
            base_tax_amount=Decimal("1697500.00"),
            sort_order=5,
        )
        db_session.add(bracket)
        db_session.flush()

        saved = db_session.get(TaxBracket, bracket.id)
        assert saved is not None
        assert saved.upper_limit is None
        assert saved.rate == Decimal("0.400000")

    def test_negative_lower_limit_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(rule_set.id, lower_limit=Decimal("-10.00"))
        db_session.add(bracket)
        with pytest.raises(IntegrityError, match="ck_tax_bracket_lower_non_negative"):
            db_session.flush()

    def test_upper_limit_lte_lower_limit_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(
            rule_set.id,
            lower_limit=Decimal("200000.00"),
            upper_limit=Decimal("100000.00"),
        )
        db_session.add(bracket)
        with pytest.raises(IntegrityError, match="ck_tax_bracket_upper_gt_lower"):
            db_session.flush()

    def test_upper_limit_equal_lower_limit_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(
            rule_set.id,
            lower_limit=Decimal("200000.00"),
            upper_limit=Decimal("200000.00"),
        )
        db_session.add(bracket)
        with pytest.raises(IntegrityError, match="ck_tax_bracket_upper_gt_lower"):
            db_session.flush()

    def test_rate_negative_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(rule_set.id, rate=Decimal("-0.050000"))
        db_session.add(bracket)
        with pytest.raises(IntegrityError, match="ck_tax_bracket_rate_valid_range"):
            db_session.flush()

    def test_rate_greater_than_one_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(rule_set.id, rate=Decimal("1.050000"))
        db_session.add(bracket)
        with pytest.raises(IntegrityError, match="ck_tax_bracket_rate_valid_range"):
            db_session.flush()

    def test_negative_base_tax_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        bracket = _make_bracket(rule_set.id, base_tax_amount=Decimal("-100.00"))
        db_session.add(bracket)
        with pytest.raises(IntegrityError, match="ck_tax_bracket_base_tax_non_negative"):
            db_session.flush()

    def test_duplicate_sort_order_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        b1 = _make_bracket(rule_set.id, income_type="EMPLOYMENT", sort_order=1)
        b2 = _make_bracket(rule_set.id, income_type="EMPLOYMENT", sort_order=1)
        db_session.add(b1)
        db_session.flush()

        db_session.add(b2)
        with pytest.raises(IntegrityError, match="uq_tax_bracket_rule_set_type_order"):
            db_session.flush()


# ===================================================================
# PayrollParameter Tests
# ===================================================================


class TestPayrollParameterModel:
    def test_valid_decimal_parameter_creation(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        param = _make_parameter(
            rule_set.id,
            parameter_key="MINIMUM_GROSS_WAGE",
            decimal_value=Decimal("33030.00"),
        )
        db_session.add(param)
        db_session.flush()

        saved = db_session.get(PayrollParameter, param.id)
        assert saved is not None
        assert saved.decimal_value == Decimal("33030.000000")
        assert saved.text_value is None

    def test_valid_text_parameter_creation(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        param = _make_parameter(
            rule_set.id,
            parameter_key="TAX_EXEMPTION_POLICY",
            decimal_value=None,
            text_value="STANDARD_2026",
            unit=None,
        )
        db_session.add(param)
        db_session.flush()

        saved = db_session.get(PayrollParameter, param.id)
        assert saved is not None
        assert saved.text_value == "STANDARD_2026"
        assert saved.decimal_value is None

    def test_both_decimal_and_text_null_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        param = _make_parameter(
            rule_set.id,
            decimal_value=None,
            text_value=None,
        )
        db_session.add(param)
        with pytest.raises(IntegrityError, match="ck_payroll_parameter_has_value"):
            db_session.flush()

    def test_invalid_effective_date_range_rejected(self, db_session: Session) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        param = _make_parameter(
            rule_set.id,
            effective_from=date(2026, 6, 1),
            effective_to=date(2026, 1, 1),
        )
        db_session.add(param)
        with pytest.raises(IntegrityError, match="ck_payroll_parameter_effective_range"):
            db_session.flush()


# ===================================================================
# TaxCalculationRun Tests
# ===================================================================


class TestTaxCalculationRunModel:
    def test_valid_calculation_run_creation(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(
            organization_id=sample_organization.id,
            employee_id=sample_employee.id,
            rule_set_id=rule_set.id,
            tax_year=2026,
        )
        db_session.add(run)
        db_session.flush()

        saved = db_session.get(TaxCalculationRun, run.id)
        assert saved is not None
        assert saved.tax_year == 2026
        assert saved.trigger_type == "MONTHLY_PAYROLL"
        assert saved.rule_set.version == rule_set.version

    def test_invalid_tax_year_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(
            organization_id=sample_organization.id,
            employee_id=sample_employee.id,
            rule_set_id=rule_set.id,
            tax_year=1999,  # < 2000
        )
        db_session.add(run)
        with pytest.raises(IntegrityError, match="ck_tax_calc_run_tax_year_valid"):
            db_session.flush()


# ===================================================================
# TaxCumulativeRecord Tests
# ===================================================================


class TestTaxCumulativeRecordModel:
    def test_valid_cumulative_record_creation(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(
            sample_organization.id,
            sample_employee.id,
            rule_set.id,
        )
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            calculation_run_id=run.id,
            employee_id=sample_employee.id,
            payroll_version_id=sample_payroll_version.id,
            period_month=1,
            opening_cumulative_base=Decimal("0.00"),
            monthly_taxable_base=Decimal("30000.00"),
            closing_cumulative_base=Decimal("30000.00"),
            gross_calculated_tax=Decimal("4500.00"),
            tax_exemptions=Decimal("0.00"),
            withholding_tax=Decimal("4500.00"),
            effective_tax_rate=Decimal("0.150000"),
        )
        db_session.add(record)
        db_session.flush()

        saved = db_session.get(TaxCumulativeRecord, record.id)
        assert saved is not None
        assert saved.closing_cumulative_base == Decimal("30000.00")
        assert saved.effective_tax_rate == Decimal("0.150000")

    @pytest.mark.parametrize("invalid_month", [0, 13, -1])
    def test_invalid_period_month_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
        invalid_month: int,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            period_month=invalid_month,
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_period_month_valid"):
            db_session.flush()

    def test_negative_opening_cumulative_base_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            opening_cumulative_base=Decimal("-100.00"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_opening_base_non_negative"):
            db_session.flush()

    def test_negative_monthly_taxable_base_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            monthly_taxable_base=Decimal("-500.00"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_monthly_base_non_negative"):
            db_session.flush()

    def test_negative_gross_calculated_tax_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            gross_calculated_tax=Decimal("-200.00"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_gross_tax_non_negative"):
            db_session.flush()

    def test_negative_tax_exemptions_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            tax_exemptions=Decimal("-50.00"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_exemptions_non_negative"):
            db_session.flush()

    def test_negative_withholding_tax_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            withholding_tax=Decimal("-10.00"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_withholding_non_negative"):
            db_session.flush()

    def test_closing_less_than_opening_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            opening_cumulative_base=Decimal("50000.00"),
            closing_cumulative_base=Decimal("30000.00"),  # closing < opening
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_closing_gte_opening"):
            db_session.flush()

    def test_rate_negative_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            effective_tax_rate=Decimal("-0.010000"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_effective_rate_valid"):
            db_session.flush()

    def test_rate_greater_than_one_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            effective_tax_rate=Decimal("1.000001"),
        )
        db_session.add(record)
        with pytest.raises(IntegrityError, match="ck_tax_cumulative_effective_rate_valid"):
            db_session.flush()

    def test_duplicate_run_emp_year_month_rejected(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        r1 = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            tax_year=2026,
            period_month=3,
        )
        r2 = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            tax_year=2026,
            period_month=3,
        )
        db_session.add(r1)
        db_session.flush()

        db_session.add(r2)
        with pytest.raises(IntegrityError, match="uq_tax_cumulative_run_emp_year_month"):
            db_session.flush()

    def test_tax_calculation_run_delete_is_rejected_as_immutable(
        self,
        db_session: Session,
        sample_organization: Organization,
        sample_employee: Employee,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        run = _make_calc_run(sample_organization.id, sample_employee.id, rule_set.id)
        db_session.add(run)
        db_session.flush()

        record = _make_cumulative_record(
            run.id,
            sample_employee.id,
            sample_payroll_version.id,
            period_month=1,
        )
        db_session.add(record)
        db_session.flush()

        nested = db_session.begin_nested()
        with pytest.raises(
            DBAPIError, match="synchronized tax calculation evidence is immutable",
        ):
            db_session.execute(
                text("DELETE FROM tax_calculation_runs WHERE id = :id"),
                {"id": run.id},
            )
            db_session.flush()
        nested.rollback()
        assert db_session.get(TaxCalculationRun, run.id) is not None
        assert db_session.get(TaxCumulativeRecord, record.id) is not None


# ===================================================================
# PayrollVersion.rule_set_id FK Tests
# ===================================================================


class TestPayrollVersionRuleSetRelationship:
    def test_payroll_version_links_to_tax_rule_set(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        sample_payroll_version.rule_set_id = rule_set.id
        db_session.flush()

        saved_version = db_session.get(PayrollVersion, sample_payroll_version.id)
        assert saved_version is not None
        assert saved_version.rule_set_id == rule_set.id
        assert saved_version.rule_set is not None
        assert saved_version.rule_set.version == rule_set.version

    def test_cannot_delete_rule_set_referenced_by_payroll_version(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        rule_set = _make_rule_set()
        db_session.add(rule_set)
        db_session.flush()

        sample_payroll_version.rule_set_id = rule_set.id
        db_session.flush()

        with pytest.raises(IntegrityError, match="foreign key|fk_payroll_versions_rule_set_id|violates foreign key constraint"):
            db_session.execute(
                text("DELETE FROM tax_rule_sets WHERE id = :id"),
                {"id": rule_set.id},
            )
            db_session.flush()
