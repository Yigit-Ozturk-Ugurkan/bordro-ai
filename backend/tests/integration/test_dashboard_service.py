"""
Tests for Dashboard Read Service V1.

Tests verify:
- Complete dashboard data retrieval
- Salary and comparison information
- Tax information integration
- Error handling
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import PayrollNotFoundError
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_detail import PayrollDeduction, PayrollEarning
from app.models.enums import (
    PayrollVersionStatus,
    PayrollSourceType,
    EmployeeStatus,
    CalculationMode,
)
from app.models.tax import TaxRuleSet
from app.services.payroll.dashboard_service import DashboardService
from app.services.payroll.comparison_service import PayrollComparisonService
from app.services.taxation.tax_service import TaxService
from app.services.taxation.tax_status_service import TaxStatusService
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.cumulative_tax_service import CumulativeTaxService


def create_payroll_version(
    db_session: Session,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    year: int,
    month: int,
    rule_set_id: uuid.UUID,
    gross_earnings: Decimal = Decimal("100000.00"),
    employee_sgk: Decimal = Decimal("10000.00"),
    income_tax: Decimal = Decimal("5000.00"),
    employee_unemployment: Decimal = Decimal("500.00"),
    stamp_tax: Decimal = Decimal("100.00"),
) -> PayrollVersion:
    """Helper to create payroll version."""
    total_deductions = (
        employee_sgk + income_tax + employee_unemployment + stamp_tax
    )
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
        total_earnings=gross_earnings,
        total_deductions=total_deductions,
        net_pay=net_pay,
        paid_days=Decimal("22.00"),
        missing_days=Decimal("0.00"),
        is_current=True,
    )
    db_session.add(pv)
    db_session.flush()

    # Detail lines are the source of truth for the dashboard breakdown.
    # Earning lines sum to gross; deduction lines sum to total_deductions.
    db_session.add(
        PayrollEarning(
            id=uuid.uuid4(),
            payroll_version_id=pv.id,
            code="BASE_SALARY",
            label="Temel Maas",
            category="BASE",
            amount=gross_earnings,
            sgk_subject_amount=gross_earnings,
            income_tax_subject_amount=gross_earnings,
            stamp_tax_subject_amount=gross_earnings,
        )
    )

    for code, label, amount in [
        ("SGK_EMPLOYEE", "SGK Isci Payi", employee_sgk),
        ("UNEMPLOYMENT", "Issizlik Sigortasi", employee_unemployment),
        ("INCOME_TAX", "Gelir Vergisi", income_tax),
        ("STAMP_TAX", "Damga Vergisi", stamp_tax),
    ]:
        db_session.add(
            PayrollDeduction(
                id=uuid.uuid4(),
                payroll_version_id=pv.id,
                code=code,
                label=label,
                category="STATUTORY",
                amount=amount,
                is_statutory=True,
                is_sensitive=False,
            )
        )

    db_session.flush()

    return pv


@pytest.fixture
def org_with_employee(db_session: Session) -> tuple[Organization, Employee]:
    """Create org and employee."""
    org = Organization(
        id=uuid.uuid4(),
        name="Dashboard Test Org",
        code=f"DASHTEST-{uuid.uuid4().hex[:8]}",
        timezone="Europe/Istanbul",
        is_active=True,
    )
    db_session.add(org)
    db_session.flush()

    employee = Employee(
        id=uuid.uuid4(),
        organization_id=org.id,
        employee_no=f"DASH-{uuid.uuid4().hex[:8]}",
        first_name="Dashboard",
        last_name="Test",
        status=EmployeeStatus.ACTIVE,
        hire_date=date(2026, 1, 1),
    )
    db_session.add(employee)
    db_session.flush()

    return org, employee


@pytest.fixture
def dashboard_services(db_session: Session) -> tuple[DashboardService, TaxRuleSet]:
    """Get dashboard services and rule set."""
    stmt = select(TaxRuleSet).where(TaxRuleSet.version == "TR_PAYROLL_2026_V1")
    rule_set = db_session.execute(stmt).scalar_one()

    tax_service = TaxService(db_session)
    tax_engine = TaxEngine(db_session, tax_service)
    cumulative_service = CumulativeTaxService(db_session, tax_engine)
    comparison_service = PayrollComparisonService(db_session)
    tax_status_service = TaxStatusService(db_session, tax_engine, tax_service)

    dashboard_service = DashboardService(
        db_session, cumulative_service, comparison_service, tax_status_service
    )

    return dashboard_service, rule_set


class TestDashboardBasic:
    """Test basic dashboard functionality."""

    def test_get_dashboard_single_month(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test retrieving dashboard for a single month."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        # Create January payroll
        pv = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set.id,
        )

        result = dashboard_service.get_payroll_dashboard(
            employee.id, 2026, 1
        )

        # Verify basic fields
        assert result.employee_id == employee.id
        assert result.tax_year == 2026
        assert result.period_month == 1
        assert result.gross_salary == Decimal("100000.00")
        assert result.net_salary == Decimal("84400.00")  # 100000 - 15600 deductions

    def test_dashboard_salary_with_comparison(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test dashboard includes previous month comparison."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        # January: 100,000 gross
        pv_jan = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set.id,
            gross_earnings=Decimal("100000.00"),
        )

        # February: 110,000 gross
        pv_feb = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            2,
            rule_set.id,
            gross_earnings=Decimal("110000.00"),
        )

        result = dashboard_service.get_payroll_dashboard(
            employee.id, 2026, 2
        )

        # Verify comparison
        assert result.previous_net_salary == Decimal("84400.00")  # January net
        assert result.net_salary == Decimal("94400.00")  # February net
        assert result.net_salary_delta == Decimal("10000.00")

    def test_dashboard_earnings_breakdown(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test dashboard includes earnings breakdown."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        pv = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set.id,
        )

        result = dashboard_service.get_payroll_dashboard(
            employee.id, 2026, 1
        )

        # Verify earnings: the breakdown comes from stored PayrollEarning
        # rows, and the line items must reconcile with the reported total.
        assert result.total_earnings == Decimal("100000.00")
        assert len(result.earnings_items) > 0

        codes = [item.code for item in result.earnings_items]
        assert "BASE_SALARY" in codes

        assert sum(item.amount for item in result.earnings_items) == (
            result.total_earnings
        )

    def test_dashboard_deductions_breakdown(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test dashboard includes deductions breakdown."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        pv = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set.id,
        )

        result = dashboard_service.get_payroll_dashboard(
            employee.id, 2026, 1
        )

        # Verify deductions: sourced from stored PayrollDeduction rows.
        assert result.total_deductions == Decimal("15600.00")
        deduction_codes = [item.code for item in result.deduction_items]
        assert "SGK_EMPLOYEE" in deduction_codes
        assert "INCOME_TAX" in deduction_codes

        assert sum(item.amount for item in result.deduction_items) == (
            result.total_deductions
        )

    def test_dashboard_attendance(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test dashboard includes attendance data."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        pv = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set.id,
        )

        result = dashboard_service.get_payroll_dashboard(
            employee.id, 2026, 1
        )

        # Verify attendance
        assert result.paid_days == Decimal("22.00")
        assert result.missing_days == Decimal("0.00")


class TestDashboardErrorHandling:
    """Test error handling."""

    def test_payroll_not_found(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test error when payroll not found."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        with pytest.raises(PayrollNotFoundError, match="No payroll found"):
            dashboard_service.get_payroll_dashboard(
                employee.id, 2026, 1
            )


class TestDashboardSerialization:
    """Test result serialization."""

    def test_dashboard_to_dict(
        self,
        db_session: Session,
        org_with_employee,
        dashboard_services,
    ):
        """Test converting dashboard to dictionary."""
        org, employee = org_with_employee
        dashboard_service, rule_set = dashboard_services

        pv = create_payroll_version(
            db_session,
            org.id,
            employee.id,
            2026,
            1,
            rule_set.id,
        )

        result = dashboard_service.get_payroll_dashboard(
            employee.id, 2026, 1
        )

        result_dict = result.to_dict()

        # Verify structure
        assert "employee_id" in result_dict
        assert "period" in result_dict
        assert "salary" in result_dict
        assert "earnings" in result_dict
        assert "deductions" in result_dict
        assert "attendance" in result_dict
        assert "tax" in result_dict

        # Verify values are strings (JSON-safe)
        assert isinstance(result_dict["salary"]["gross"], str)
        assert result_dict["salary"]["gross"] == "100000.00"
