"""
Pydantic response schemas for the read-only payroll API.

These are the public contract. ORM objects are never returned directly:
every route serializes through one of these models, so the wire format is
independent of the database schema.

All money fields are ``Decimal`` and serialize to JSON strings (pydantic's
default for Decimal), preserving scale exactly. No float ever appears in a
response body.
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PayrollPeriodSchema(BaseModel):
    """One payroll period in an employee's history."""

    year: int = Field(..., description="Period year")
    month: int = Field(..., description="Period month (1-12)")
    payroll_id: str = Field(..., description="UUID of the payroll")
    payroll_version_id: Optional[str] = Field(
        None, description="UUID of the current revision, if any exists"
    )
    revision_no: Optional[int] = Field(
        None, description="Revision number of the current revision"
    )
    status: Optional[str] = Field(None, description="Revision status")
    is_current: Optional[bool] = Field(
        None, description="Whether the revision is flagged current"
    )
    gross_earnings: Optional[Decimal] = Field(None, description="Gross earnings")
    net_pay: Optional[Decimal] = Field(None, description="Net pay")


class PayrollPeriodListSchema(BaseModel):
    """All payroll periods recorded for an employee."""

    employee_id: str = Field(..., description="UUID of employee")
    count: int = Field(..., description="Number of periods returned")
    periods: list[PayrollPeriodSchema] = Field(
        default_factory=list, description="Periods, newest first"
    )


class PayrollEarningLineSchema(BaseModel):
    """A single earning line of a payroll revision."""

    code: str = Field(..., description="Earning code")
    label: str = Field(..., description="Human-readable label")
    category: str = Field(..., description="Earning category")
    amount: Decimal = Field(..., description="Amount")


class PayrollDeductionLineSchema(BaseModel):
    """A single deduction line of a payroll revision."""

    code: str = Field(..., description="Deduction code")
    label: str = Field(..., description="Human-readable label")
    category: str = Field(..., description="Deduction category")
    amount: Decimal = Field(..., description="Amount")
    is_statutory: bool = Field(..., description="Legally mandated deduction")


class PayrollAbsenceLineSchema(BaseModel):
    """A single absence record of a payroll revision."""

    reason_code: str = Field(..., description="Absence reason code")
    description: Optional[str] = Field(None, description="Free-text description")
    day_count: Decimal = Field(..., description="Number of days")
    is_paid: bool = Field(..., description="Whether the absence is paid")
    gross_effect: Optional[Decimal] = Field(
        None, description="Effect on gross earnings (negative reduces gross)"
    )


class PayrollAttendanceSchema(BaseModel):
    """Attendance figures for a payroll revision."""

    paid_days: Decimal = Field(..., description="Paid working days")
    missing_days: Decimal = Field(..., description="Missing/absent days")
    absences: list[PayrollAbsenceLineSchema] = Field(
        default_factory=list, description="Absence records"
    )


class PayrollEarningsSchema(BaseModel):
    """Earnings section of a payroll revision."""

    total: Decimal = Field(..., description="Total earnings")
    items: list[PayrollEarningLineSchema] = Field(
        default_factory=list, description="Earning lines"
    )


class PayrollDeductionsSchema(BaseModel):
    """Deductions section of a payroll revision."""

    total: Decimal = Field(..., description="Total deductions")
    items: list[PayrollDeductionLineSchema] = Field(
        default_factory=list, description="Deduction lines"
    )


class PayrollRevisionSchema(BaseModel):
    """The current revision of a payroll period."""

    payroll_version_id: str = Field(..., description="UUID of the revision")
    revision_no: int = Field(..., description="Revision number")
    status: str = Field(..., description="Revision status")
    source_type: str = Field(..., description="How this revision was produced")
    calculation_mode: str = Field(..., description="Calculation mode")
    is_current: bool = Field(..., description="Whether flagged as current")
    currency: str = Field(..., description="ISO currency code")


class PayrollDetailSchema(BaseModel):
    """Full detail of one employee's payroll for one period."""

    employee_id: str = Field(..., description="UUID of employee")
    year: int = Field(..., description="Period year")
    month: int = Field(..., description="Period month (1-12)")
    payroll_id: str = Field(..., description="UUID of the payroll")
    revision: PayrollRevisionSchema = Field(..., description="Current revision")

    gross: Decimal = Field(..., description="Gross earnings")
    net: Decimal = Field(..., description="Net pay")

    earnings: PayrollEarningsSchema = Field(..., description="Earnings breakdown")
    deductions: PayrollDeductionsSchema = Field(
        ..., description="Deductions breakdown"
    )
    attendance: PayrollAttendanceSchema = Field(
        ..., description="Attendance and absences"
    )


class TaxBracketSchema(BaseModel):
    """A progressive tax bracket."""

    sort_order: int = Field(..., description="Bracket order within the schedule")
    lower_limit: Decimal = Field(..., description="Inclusive lower limit")
    upper_limit: Optional[Decimal] = Field(
        None, description="Exclusive upper limit; null for the final bracket"
    )
    rate: Decimal = Field(..., description="Marginal rate for this bracket")


class TaxStatusSchema(BaseModel):
    """An employee's position in the progressive tax schedule."""

    employee_id: str = Field(..., description="UUID of employee")
    tax_year: int = Field(..., description="Tax year")
    period_month: Optional[int] = Field(
        None, description="Month the status is reported as of"
    )
    monthly_taxable_base: Optional[Decimal] = Field(
        None, description="Taxable base for the month; null if no record yet"
    )
    cumulative_taxable_base: Decimal = Field(
        ..., description="Cumulative taxable base year-to-date"
    )
    current_bracket: Optional[TaxBracketSchema] = Field(
        None, description="Bracket containing the cumulative base"
    )
    next_bracket: Optional[TaxBracketSchema] = Field(
        None, description="Next bracket; null when already in the final bracket"
    )
    distance_to_next_bracket: Optional[Decimal] = Field(
        None, description="Income still needed to reach the next bracket"
    )
    rule_set_version: str = Field(
        ..., description="Tax rule set version used to resolve the brackets"
    )
