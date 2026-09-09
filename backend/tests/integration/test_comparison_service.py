"""
Tests for Payroll Comparison Service V1.

Tests verify:
- Factual net salary comparison
- Earning and deduction deltas
- Percentage calculations (zero-safe)
- Code-level deltas (placeholder)
- Error handling
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion
from app.models.enums import (
    PayrollVersionStatus,
    PayrollSourceType,
    EmployeeStatus,
    CalculationMode,
)
from app.models.tax import TaxRuleSet
from app.services.payroll.comparison_service import (
    PayrollComparisonService,
    PayrollComparisonResult,
)


def create_payroll_version(
    db_session: Session,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    year: int,
    month: int,
    rule_set_id: uuid.UUID,
    gross_earnings: Decimal = Decimal("0.00"),
    employee_sgk: Decimal = Decimal("0.00"),
    income_tax: Decimal = Decimal("0.00"),
    employee_unemployment: Decimal = Decimal("0.00"),
    stamp_tax: Decimal = Decimal("0.00"),
    total_earnings: Decimal = None,
    total_deductions: Decimal = None,
    net_pay: Decimal = None,
) -> PayrollVersion:
    """Helper to create a Payroll and PayrollVersion with specific values."""
    # Calculate totals if not provided
    if total_earnings is None:
        total_earnings = gross_earnings
    if total_deductions is None:
        total_deductions = employee_sgk + income_tax + employee_unemployment + stamp_tax
    if net_pay is None:
        net_pay = gross_earnings - total_deductions

    payroll = Payroll(
        id=uuid.uuid4(),
        organization_id=org_id,
        employee_id=employee_id,
        period_year=year,
        period_month=month,
    )
    db_session.add(payroll)
    db_session.flush()

    pv = PayrollVersion(
        id=uuid.uuid4(),
        payroll_id=payroll.id,
        revision_no=1,
        status=PayrollVersionStatus.DRAFT,
        source_type=PayrollSourceType.MANUAL,
        calculation_mode=CalculationMode.CALCULATED,
        rule_set_id=rule_set_id,
        gross_earnings=gross_earnings,
        employee_sgk=employee_sgk,
        income_tax=income_tax,
        employee_unemployment=employee_unemployment,
        stamp_tax=stamp_tax,
        total_earnings=total_earnings,
        total_deductions=total_deductions,
        net_pay=net_pay,
    )
    db_session.add(pv)
    db_session.flush()

    return pv


@pytest.fixture
def org_with_employee(db_session: Session) -> tuple[Organization, Employee]:
    """Create org and employee."""
    org = Organization(
        id=uuid.uuid4(),
        name="Comparison Test Org",
        code=f"CMPTEST-{uuid.uuid4().hex[:8]}",
        timezone="Europe/Istanbul",
        is_active=True,
    )
    db_session.add(org)
    db_session.flush()

    employee = Employee(
        id=uuid.uuid4(),
        organization_id=org.id,
        employee_no=f"CMP-{uuid.uuid4().hex[:8]}",
        first_name="Comparison",
        last_name="Test",
        status=EmployeeStatus.ACTIVE,
        hire_date=date(2026, 1, 1),
    )
    db_session.add(employee)
    db_session.flush()

    return org, employee


@pytest.fixture
def rule_set_2026(db_session: Session) -> TaxRuleSet:
    """Get 2026 rule set."""
    from sqlalchemy import select
    stmt = select(TaxRuleSet).where(TaxRuleSet.version == "TR_PAYROLL_2026_V1")
    return db_session.execute(stmt).scalar_one()


class TestPayrollComparisonBasic:
    """Test basic comparison functionality."""

    def test_compare_same_employee_two_months(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Test comparing two consecutive payrolls."""
        org, employee = org_with_employee

        # January: 100,000 gross, 10,000 SGK, 5,000 income tax
        pv_jan = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
            gross_earnings=Decimal("100000.00"),
            employee_sgk=Decimal("10000.00"),
            income_tax=Decimal("5000.00"),
        )

        # February: 110,000 gross, 11,000 SGK, 5,500 income tax
        pv_feb = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set_2026.id,
            gross_earnings=Decimal("110000.00"),
            employee_sgk=Decimal("11000.00"),
            income_tax=Decimal("5500.00"),
        )

        service = PayrollComparisonService(db_session)
        result = service.compare_payroll_versions(pv_jan.id, pv_feb.id)

        # Verify result type
        assert isinstance(result, PayrollComparisonResult)

        # Net: (100000 - 10000 - 5000) = 85000 -> (110000 - 11000 - 5500) = 93500
        assert result.previous_net == Decimal("85000.00")
        assert result.current_net == Decimal("93500.00")
        assert result.net_delta == Decimal("8500.00")
        assert result.net_delta_percent == Decimal("10.00")

        # Income tax is read directly from each PayrollVersion and uses the
        # same Decimal delta/percentage semantics as the existing sections.
        assert result.previous_income_tax == Decimal("5000.00")
        assert result.current_income_tax == Decimal("5500.00")
        assert result.income_tax_delta == Decimal("500.00")
        assert result.income_tax_delta_percent == Decimal("10.00")

    def test_earnings_and_deductions_deltas(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Test that earnings and deduction deltas are calculated correctly."""
        org, employee = org_with_employee

        pv_1 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
            gross_earnings=Decimal("100000.00"),
            employee_sgk=Decimal("10000.00"),
            income_tax=Decimal("3000.00"),
            employee_unemployment=Decimal("500.00"),
        )

        pv_2 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set_2026.id,
            gross_earnings=Decimal("120000.00"),
            employee_sgk=Decimal("12000.00"),
            income_tax=Decimal("3500.00"),
            employee_unemployment=Decimal("600.00"),
        )

        service = PayrollComparisonService(db_session)
        result = service.compare_payroll_versions(pv_1.id, pv_2.id)

        # Earnings delta: 120000 - 100000 = 20000
        assert result.previous_total_earnings == Decimal("100000.00")
        assert result.current_total_earnings == Decimal("120000.00")
        assert result.earnings_delta == Decimal("20000.00")
        assert result.earnings_delta_percent == Decimal("20.00")

        # Deductions delta: (12000 + 3500 + 600) - (10000 + 3000 + 500) = 2100
        assert result.previous_total_deductions == Decimal("13500.00")
        assert result.current_total_deductions == Decimal("16100.00")
        assert result.deductions_delta == Decimal("2600.00")
        assert result.deductions_delta_percent == (
            (Decimal("2600.00") / Decimal("13500.00") * 100)
            .quantize(Decimal("0.01"))
        )


class TestPayrollComparisonPercentages:
    """Test percentage calculation (zero-safe)."""

    def test_net_delta_percent_zero_previous(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Test that percent is None when previous net is zero."""
        org, employee = org_with_employee

        # First version with zero net (all earnings deducted)
        pv_1 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
            gross_earnings=Decimal("100000.00"),
            employee_sgk=Decimal("100000.00"),  # Full deduction
        )

        # Second version with positive net
        pv_2 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set_2026.id,
            gross_earnings=Decimal("100000.00"),
            employee_sgk=Decimal("50000.00"),
        )

        service = PayrollComparisonService(db_session)
        result = service.compare_payroll_versions(pv_1.id, pv_2.id)

        # Previous net = 0, so percent should be None
        assert result.previous_net == Decimal("0.00")
        assert result.current_net == Decimal("50000.00")
        assert result.net_delta == Decimal("50000.00")
        assert result.net_delta_percent is None  # Can't calculate percent

    def test_earnings_delta_percent_zero_previous(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Test that earnings percent is None when previous earnings is zero."""
        org, employee = org_with_employee

        pv_1 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
            gross_earnings=Decimal("0.00"),
        )

        pv_2 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set_2026.id,
            gross_earnings=Decimal("100000.00"),
        )

        service = PayrollComparisonService(db_session)
        result = service.compare_payroll_versions(pv_1.id, pv_2.id)

        assert result.previous_total_earnings == Decimal("0.00")
        assert result.current_total_earnings == Decimal("100000.00")
        assert result.earnings_delta_percent is None

    def test_income_tax_delta_percent_zero_previous(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Income-tax percent uses the existing zero-safe helper semantics."""
        org, employee = org_with_employee

        pv_1 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
            income_tax=Decimal("0.00"),
        )
        pv_2 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set_2026.id,
            income_tax=Decimal("2500.00"),
        )

        result = PayrollComparisonService(db_session).compare_payroll_versions(
            pv_1.id, pv_2.id,
        )

        assert result.previous_income_tax == Decimal("0.00")
        assert result.current_income_tax == Decimal("2500.00")
        assert result.income_tax_delta == Decimal("2500.00")
        assert result.income_tax_delta_percent is None


class TestPayrollComparisonErrorHandling:
    """Test error handling."""

    def test_version_not_found(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Test error when version not found."""
        org, employee = org_with_employee

        pv = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
        )

        fake_id = uuid.uuid4()

        service = PayrollComparisonService(db_session)

        with pytest.raises(NotFoundError, match="Previous payroll version not found"):
            service.compare_payroll_versions(fake_id, pv.id)

        with pytest.raises(NotFoundError, match="Current payroll version not found"):
            service.compare_payroll_versions(pv.id, fake_id)

    def test_different_employees(
        self,
        db_session: Session,
        rule_set_2026,
    ):
        """Test error when versions belong to different employees."""
        org = Organization(
            id=uuid.uuid4(),
            name="Test Org",
            code=f"TEST-{uuid.uuid4().hex[:8]}",
            timezone="Europe/Istanbul",
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        emp1 = Employee(
            id=uuid.uuid4(),
            organization_id=org.id,
            employee_no="EMP001",
            first_name="Employee",
            last_name="One",
            status=EmployeeStatus.ACTIVE,
            hire_date=date(2026, 1, 1),
        )
        emp2 = Employee(
            id=uuid.uuid4(),
            organization_id=org.id,
            employee_no="EMP002",
            first_name="Employee",
            last_name="Two",
            status=EmployeeStatus.ACTIVE,
            hire_date=date(2026, 1, 1),
        )
        db_session.add_all([emp1, emp2])
        db_session.flush()

        pv1 = create_payroll_version(
            db_session, org.id, emp1.id, 2026, 1, rule_set_2026.id
        )
        pv2 = create_payroll_version(
            db_session, org.id, emp2.id, 2026, 1, rule_set_2026.id
        )

        service = PayrollComparisonService(db_session)

        with pytest.raises(ValueError, match="must be for the same employee"):
            service.compare_payroll_versions(pv1.id, pv2.id)


class TestPayrollComparisonSerialization:
    """Test result serialization to dictionary."""

    def test_to_dict_serialization(
        self,
        db_session: Session,
        org_with_employee,
        rule_set_2026,
    ):
        """Test converting result to dictionary."""
        org, employee = org_with_employee

        pv_1 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set_2026.id,
            gross_earnings=Decimal("100000.00"),
            employee_sgk=Decimal("10000.00"),
            income_tax=Decimal("5000.00"),
        )

        pv_2 = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set_2026.id,
            gross_earnings=Decimal("110000.00"),
            employee_sgk=Decimal("11000.00"),
            income_tax=Decimal("5500.00"),
        )

        service = PayrollComparisonService(db_session)
        result = service.compare_payroll_versions(pv_1.id, pv_2.id)

        result_dict = result.to_dict()

        # Verify structure
        assert "net" in result_dict
        assert "earnings" in result_dict
        assert "deductions" in result_dict
        assert "income_tax" in result_dict
        assert "attendance" in result_dict

        # Verify all values are strings (JSON-safe)
        assert isinstance(result_dict["net"]["previous"], str)
        assert isinstance(result_dict["net"]["delta"], str)
        assert result_dict["net"]["previous"] == "85000.00"
        assert result_dict["net"]["delta"] == "8500.00"
        assert result_dict["income_tax"] == {
            "previous": "5000.00",
            "current": "5500.00",
            "delta": "500.00",
            "delta_percent": "10.00",
        }
        assert all(
            isinstance(value, str)
            for value in result_dict["income_tax"].values()
        )
