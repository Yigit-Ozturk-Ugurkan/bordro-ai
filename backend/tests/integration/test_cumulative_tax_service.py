"""
Tests for Cumulative Tax Service V1 - Fixed version.

Tests verify:
- Monthly cumulative ledger (opening + monthly = closing)
- Year boundary behavior (reset on new year)
- Tax calculation integration
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion
from app.models.enums import (
    PayrollVersionStatus,
    PayrollSourceType,
    EmployeeStatus,
    CalculationMode,
)
from app.models.tax import TaxRuleSet, TaxCumulativeRecord
from app.services.taxation.tax_service import TaxService
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.cumulative_tax_service import CumulativeTaxService


def create_payroll_version(
    db_session: Session,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    year: int,
    month: int,
    rule_set_id: uuid.UUID,
) -> PayrollVersion:
    """Helper to create a Payroll and PayrollVersion."""
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
    )
    db_session.add(pv)
    db_session.flush()

    return pv


@pytest.fixture
def cumulative_tax_service_2026(
    db_session: Session,
) -> tuple[CumulativeTaxService, TaxRuleSet]:
    """Fixture providing CumulativeTaxService and 2026 rule set."""
    stmt = select(TaxRuleSet).where(TaxRuleSet.version == "TR_PAYROLL_2026_V1")
    rule_set = db_session.execute(stmt).scalar_one()

    tax_service = TaxService(db_session)
    tax_engine = TaxEngine(db_session, tax_service)
    service = CumulativeTaxService(db_session, tax_engine)

    return service, rule_set


@pytest.fixture
def org_with_employee(db_session: Session) -> tuple[Organization, Employee]:
    """Create org and employee for testing."""
    org = Organization(
        id=uuid.uuid4(),
        name="Cumulative Tax Test Org",
        code=f"CTEST-{uuid.uuid4().hex[:8]}",
        timezone="Europe/Istanbul",
        is_active=True,
    )
    db_session.add(org)
    db_session.flush()

    employee = Employee(
        id=uuid.uuid4(),
        organization_id=org.id,
        employee_no=f"CTAX-{uuid.uuid4().hex[:8]}",
        first_name="Cumulative",
        last_name="Test",
        status=EmployeeStatus.ACTIVE,
        hire_date=date(2026, 1, 1),
    )
    db_session.add(employee)
    db_session.flush()

    return org, employee


class TestCumulativeTaxServiceMonthlyLedger:
    """Test monthly ledger functionality."""

    def test_january_starts_with_zero_opening(
        self,
        db_session: Session,
        cumulative_tax_service_2026,
        org_with_employee,
    ):
        """Test that January has opening_cumulative_base = 0."""
        service, rule_set = cumulative_tax_service_2026
        org, employee = org_with_employee

        pv_jan = create_payroll_version(
            db_session, org.id, employee.id, 2026, 1, rule_set.id
        )

        record = service.build_monthly_cumulative_record(
            employee_id=employee.id,
            payroll_version_id=pv_jan.id,
            organization_id=org.id,
            tax_year=2026,
            period_month=1,
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )

        assert record.opening_cumulative_base == Decimal("0.00")
        assert record.closing_cumulative_base == Decimal("100000.00")
        assert record.gross_calculated_tax == Decimal("15000.00")
        assert record.withholding_tax == Decimal("15000.00")
        assert record.effective_tax_rate == Decimal("0.150000")

    def test_february_opening_equals_january_closing(
        self,
        db_session: Session,
        cumulative_tax_service_2026,
        org_with_employee,
    ):
        """Test that February opening = January closing."""
        service, rule_set = cumulative_tax_service_2026
        org, employee = org_with_employee

        # January
        pv_jan = create_payroll_version(
            db_session, org.id, employee.id, 2026, 1, rule_set.id
        )
        record_jan = service.build_monthly_cumulative_record(
            employee_id=employee.id,
            payroll_version_id=pv_jan.id,
            organization_id=org.id,
            tax_year=2026,
            period_month=1,
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )
        db_session.add(record_jan)
        db_session.flush()

        # February
        pv_feb = create_payroll_version(
            db_session, org.id, employee.id, 2026, 2, rule_set.id
        )
        record_feb = service.build_monthly_cumulative_record(
            employee_id=employee.id,
            payroll_version_id=pv_feb.id,
            organization_id=org.id,
            tax_year=2026,
            period_month=2,
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )

        assert record_feb.opening_cumulative_base == record_jan.closing_cumulative_base
        assert record_feb.gross_calculated_tax == Decimal("30500.00")
        assert record_feb.withholding_tax == Decimal("15500.00")
        assert record_feb.effective_tax_rate == Decimal("0.155000")


class TestCumulativeTaxServiceYearBoundary:
    """Test year boundary behavior."""

    def test_year_reset_on_new_year(
        self,
        db_session: Session,
        cumulative_tax_service_2026,
        org_with_employee,
    ):
        """Test that Jan 2027 opens at 0 despite Dec 2026 closing."""
        service, rule_set = cumulative_tax_service_2026
        org, employee = org_with_employee

        # December 2026
        pv_dec = create_payroll_version(
            db_session, org.id, employee.id, 2026, 12, rule_set.id
        )
        record_dec = service.build_monthly_cumulative_record(
            employee_id=employee.id,
            payroll_version_id=pv_dec.id,
            organization_id=org.id,
            tax_year=2026,
            period_month=12,
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )
        db_session.add(record_dec)
        db_session.flush()

        # January 2027 - should start fresh at 0
        pv_jan_2027 = create_payroll_version(
            db_session, org.id, employee.id, 2027, 1, rule_set.id
        )
        record_jan_2027 = service.build_monthly_cumulative_record(
            employee_id=employee.id,
            payroll_version_id=pv_jan_2027.id,
            organization_id=org.id,
            tax_year=2027,
            period_month=1,
            monthly_taxable_base=Decimal("100000.00"),
            rule_set=rule_set,
        )

        # Key assertion: new year starts fresh
        assert record_jan_2027.opening_cumulative_base == Decimal("0.00")


class TestCumulativeTaxServiceHistory:
    """Test history and query functionality."""

    def test_get_latest_cumulative_base_returns_highest_month(
        self,
        db_session: Session,
        cumulative_tax_service_2026,
        org_with_employee,
    ):
        """Test that latest base query returns highest month."""
        service, rule_set = cumulative_tax_service_2026
        org, employee = org_with_employee

        # Create Jan and Feb
        for month in [1, 2]:
            pv = create_payroll_version(
                db_session, org.id, employee.id, 2026, month, rule_set.id
            )
            record = service.build_monthly_cumulative_record(
                employee_id=employee.id,
                payroll_version_id=pv.id,
                organization_id=org.id,
                tax_year=2026,
                period_month=month,
                monthly_taxable_base=Decimal("100000.00"),
                rule_set=rule_set,
            )
            db_session.add(record)
            db_session.flush()

        latest = service.get_latest_cumulative_base(employee.id, 2026)
        assert latest == Decimal("200000.00")  # Jan + Feb

    def test_zero_base_when_no_records_exist(
        self,
        db_session: Session,
        cumulative_tax_service_2026,
        org_with_employee,
    ):
        """Test that get_latest_cumulative_base returns 0 if no records."""
        service, rule_set = cumulative_tax_service_2026
        org, employee = org_with_employee

        latest = service.get_latest_cumulative_base(employee.id, 2026)
        assert latest == Decimal("0.00")
