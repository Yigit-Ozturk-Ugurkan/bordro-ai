"""
Cumulative Tax Service V1: annual progressive tax base tracking.

This service manages the monthly cumulative state of an employee's taxable
income within a tax year, enabling correct application of progressive tax
brackets.

Key Responsibilities:
- Track opening/closing cumulative base per month per year per employee
- Reset cumulative base on year boundary (previous year → new year)
- Preserve full history (no overwrites, immutable records)
- Create TaxCalculationRun for audit trail
- Work with TaxEngine for tax calculations

Monthly Ledger Pattern:
    January:   opening=0 + monthly=M1 = closing=M1
    February:  opening=M1 + monthly=M2 = closing=M1+M2
    March:     opening=M1+M2 + monthly=M3 = closing=M1+M2+M3
    ...
    December:  opening=SUM(M1..M11) + monthly=M12 = closing=SUM(M1..M12)

Year Reset:
    December 31 (2026): closing_cumulative = SUM(all 2026)
    January 1 (2027):   opening_cumulative = 0 (NEW YEAR)

Database Design:
- TaxCalculationRun: immutable execution record (MONTHLY_PAYROLL trigger)
- TaxCumulativeRecord: monthly snapshots per run
- Unique constraint: (run_id, employee_id, year, period_month)
- Previous runs/records are never deleted or modified
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import ZERO_MONEY, quantize_money, quantize_rate
from app.models.employee import Employee
from app.models.organization import Organization
from app.models.payroll import PayrollVersion
from app.models.tax import (
    TaxCalculationRun,
    TaxCumulativeRecord,
    TaxRuleSet,
)
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.tax_service import TaxService


class CumulativeTaxService:
    """
    Service for managing annual cumulative income tax tracking.

    Each employee has a running cumulative tax base throughout a calendar year.
    Monthly records capture opening, monthly taxable, and closing amounts,
    enabling proper progressive tax calculation.
    """

    def __init__(
        self,
        session: Session,
        tax_engine: TaxEngine,
    ) -> None:
        """
        Initialize cumulative tax service.

        Args:
            session: SQLAlchemy session
            tax_engine: TaxEngine instance for tax calculations
        """
        self._session = session
        self._tax_engine = tax_engine

    def get_latest_cumulative_base(
        self,
        employee_id: uuid.UUID,
        tax_year: int,
    ) -> Decimal:
        """
        Get the latest closing cumulative base for an employee in a year.

        Searches for the highest period_month record in the given tax_year,
        returns its closing_cumulative_base.

        If no record exists, returns Decimal("0.00") (beginning of year).

        Args:
            employee_id: employee UUID
            tax_year: calendar year (e.g., 2026)

        Returns:
            Closing cumulative base as Decimal, or 0 if no records
        """
        stmt = (
            select(TaxCumulativeRecord)
            .where(
                TaxCumulativeRecord.employee_id == employee_id,
                TaxCumulativeRecord.tax_year == tax_year,
            )
            .order_by(TaxCumulativeRecord.period_month.desc())
            .limit(1)
        )
        record = self._session.execute(stmt).scalar_one_or_none()

        if record is None:
            return Decimal("0.00")

        return record.closing_cumulative_base

    def build_monthly_cumulative_record(
        self,
        employee_id: uuid.UUID,
        payroll_version_id: uuid.UUID,
        organization_id: uuid.UUID,
        tax_year: int,
        period_month: int,
        monthly_taxable_base: Decimal,
        rule_set: TaxRuleSet,
        income_type: str = "EMPLOYMENT",
        trigger_type: str = "MONTHLY_PAYROLL",
        target_date: date | None = None,
    ) -> TaxCumulativeRecord:
        """
        Build a monthly cumulative tax record for an employee.

        This method:
        1. Determines opening cumulative base (from previous month or 0)
        2. Calculates closing cumulative base (opening + monthly)
        3. Uses TaxEngine to calculate tax on closing base
        4. Creates a TaxCalculationRun (immutable audit trail)
        5. Creates a TaxCumulativeRecord
        6. Returns the new record (not yet committed)

        Args:
            employee_id: employee UUID
            payroll_version_id: PayrollVersion UUID for this month
            organization_id: organization UUID
            tax_year: calendar year (e.g., 2026)
            period_month: month number (1-12)
            monthly_taxable_base: this month's taxable income
            rule_set: TaxRuleSet to use for calculations
            income_type: income type (default: 'EMPLOYMENT')
            trigger_type: trigger type for calculation run (default: 'MONTHLY_PAYROLL')
            target_date: optional date for bracket effective dating

        Returns:
            TaxCumulativeRecord (not committed to DB yet)

        Raises:
            ValueError: if period_month not in 1-12
            RuntimeError: if tax calculation fails
        """
        if not 1 <= period_month <= 12:
            raise ValueError(f"period_month must be 1-12, got {period_month}")

        # Step 1: Determine opening cumulative base and prior cumulative tax.
        # Monthly withholding is the increase in cumulative tax liability,
        # not the full tax liability at the end of every month.
        previous_record = None
        if period_month == 1:
            # January: reset to 0 (new year)
            opening_cumulative_base = ZERO_MONEY
        else:
            previous_record = self._get_latest_record_before_month(
                employee_id, tax_year, period_month
            )
            opening_cumulative_base = (
                previous_record.closing_cumulative_base
                if previous_record is not None
                else ZERO_MONEY
            )

        # Step 2: Calculate closing cumulative base
        closing_cumulative_base = opening_cumulative_base + monthly_taxable_base

        # Step 3: Use TaxEngine to calculate tax
        tax_position = self._tax_engine.calculate_progressive_tax(
            closing_cumulative_base=closing_cumulative_base,
            monthly_taxable_base=monthly_taxable_base,
            rule_set=rule_set,
            income_type=income_type,
            target_date=target_date,
        )

        # Step 4: Create TaxCalculationRun (immutable audit trail)
        calc_run = TaxCalculationRun(
            id=uuid.uuid4(),
            organization_id=organization_id,
            employee_id=employee_id,
            tax_year=tax_year,
            rule_set_id=rule_set.id,
            trigger_type=trigger_type,
            status="COMPLETED",
            calculation_version="1.0",
        )
        self._session.add(calc_run)
        self._session.flush()

        # Step 5: Create TaxCumulativeRecord. The engine returns cumulative
        # tax at closing base; subtract cumulative tax already recognized in
        # earlier months to obtain this month's withholding.
        tax_exemptions = ZERO_MONEY
        previous_gross_calculated_tax = (
            previous_record.gross_calculated_tax
            if previous_record is not None
            else ZERO_MONEY
        )
        withholding_tax = self.calculate_monthly_withholding(
            gross_calculated_tax=tax_position.calculated_tax,
            previous_gross_calculated_tax=previous_gross_calculated_tax,
            tax_exemptions=tax_exemptions,
        )
        effective_tax_rate = self.calculate_effective_tax_rate(
            withholding_tax, monthly_taxable_base
        )

        cumulative_record = TaxCumulativeRecord(
            id=uuid.uuid4(),
            calculation_run_id=calc_run.id,
            employee_id=employee_id,
            payroll_version_id=payroll_version_id,
            tax_year=tax_year,
            period_month=period_month,
            opening_cumulative_base=opening_cumulative_base,
            monthly_taxable_base=monthly_taxable_base,
            closing_cumulative_base=closing_cumulative_base,
            gross_calculated_tax=tax_position.calculated_tax,
            tax_exemptions=tax_exemptions,  # No exemptions yet
            withholding_tax=withholding_tax,
            effective_tax_rate=effective_tax_rate,
        )

        return cumulative_record

    @staticmethod
    def calculate_monthly_withholding(
        gross_calculated_tax: Decimal,
        previous_gross_calculated_tax: Decimal,
        tax_exemptions: Decimal = ZERO_MONEY,
    ) -> Decimal:
        """Return this month's withholding from cumulative tax liabilities."""
        withholding = quantize_money(
            gross_calculated_tax
            - previous_gross_calculated_tax
            - tax_exemptions
        )
        if withholding < ZERO_MONEY:
            raise ValueError("monthly withholding tax must be >= 0")
        return withholding

    @staticmethod
    def calculate_effective_tax_rate(
        withholding_tax: Decimal,
        monthly_taxable_base: Decimal,
    ) -> Decimal:
        """Return the monthly withholding rate using Decimal-only arithmetic."""
        if monthly_taxable_base <= ZERO_MONEY:
            return Decimal("0.000000")
        rate = quantize_rate(withholding_tax / monthly_taxable_base)
        assert rate is not None
        return rate

    def _get_latest_record_before_month(
        self,
        employee_id: uuid.UUID,
        tax_year: int,
        period_month: int,
    ) -> TaxCumulativeRecord | None:
        """Return the latest earlier ledger entry within the same tax year."""
        stmt = (
            select(TaxCumulativeRecord)
            .where(
                TaxCumulativeRecord.employee_id == employee_id,
                TaxCumulativeRecord.tax_year == tax_year,
                TaxCumulativeRecord.period_month < period_month,
            )
            .order_by(TaxCumulativeRecord.period_month.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create_cumulative_records_for_payroll(
        self,
        payroll_version_id: uuid.UUID,
        monthly_taxable_base: Decimal,
        rule_set: TaxRuleSet,
        income_type: str = "EMPLOYMENT",
        trigger_type: str = "MONTHLY_PAYROLL",
        target_date: date | None = None,
    ) -> TaxCumulativeRecord:
        """
        Convenience method: create cumulative record from PayrollVersion.

        This method extracts employee/organization/tax_year from the
        PayrollVersion and calls build_monthly_cumulative_record.

        Args:
            payroll_version_id: PayrollVersion UUID
            monthly_taxable_base: this month's taxable income
            rule_set: TaxRuleSet to use
            income_type: income type (default: 'EMPLOYMENT')
            trigger_type: trigger type (default: 'MONTHLY_PAYROLL')
            target_date: optional date for bracket effective dating

        Returns:
            TaxCumulativeRecord (not committed)

        Raises:
            ValueError: if PayrollVersion not found
        """
        stmt = select(PayrollVersion).where(
            PayrollVersion.id == payroll_version_id
        )
        payroll_version = self._session.execute(stmt).scalar_one_or_none()

        if payroll_version is None:
            raise ValueError(
                f"PayrollVersion {payroll_version_id} not found"
            )

        # Extract payroll details
        payroll = payroll_version.payroll
        employee_id = payroll.employee_id
        organization_id = payroll.organization_id
        tax_year = payroll.period_year
        period_month = payroll.period_month

        return self.build_monthly_cumulative_record(
            employee_id=employee_id,
            payroll_version_id=payroll_version_id,
            organization_id=organization_id,
            tax_year=tax_year,
            period_month=period_month,
            monthly_taxable_base=monthly_taxable_base,
            rule_set=rule_set,
            income_type=income_type,
            trigger_type=trigger_type,
            target_date=target_date,
        )

    def get_annual_summary(
        self,
        employee_id: uuid.UUID,
        tax_year: int,
    ) -> dict:
        """
        Get summary of all months' cumulative records for a year.

        Returns a dict with:
        {
            "tax_year": tax_year,
            "months": [
                {
                    "period_month": 1,
                    "opening_cumulative_base": Decimal(...),
                    "monthly_taxable_base": Decimal(...),
                    "closing_cumulative_base": Decimal(...),
                    "gross_calculated_tax": Decimal(...),
                    "effective_tax_rate": Decimal(...),
                }
                ...
            ]
        }

        Args:
            employee_id: employee UUID
            tax_year: calendar year

        Returns:
            Summary dict
        """
        stmt = (
            select(TaxCumulativeRecord)
            .where(
                TaxCumulativeRecord.employee_id == employee_id,
                TaxCumulativeRecord.tax_year == tax_year,
            )
            .order_by(TaxCumulativeRecord.period_month)
        )
        records = list(self._session.execute(stmt).scalars().all())

        months_data = [
            {
                "period_month": r.period_month,
                "opening_cumulative_base": r.opening_cumulative_base,
                "monthly_taxable_base": r.monthly_taxable_base,
                "closing_cumulative_base": r.closing_cumulative_base,
                "gross_calculated_tax": r.gross_calculated_tax,
                "effective_tax_rate": r.effective_tax_rate,
            }
            for r in records
        ]

        return {
            "tax_year": tax_year,
            "months": months_data,
        }
