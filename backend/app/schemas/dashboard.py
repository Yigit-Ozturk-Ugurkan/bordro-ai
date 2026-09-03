"""
Pydantic schemas for payroll dashboard.

Validates and serializes dashboard data at API boundary.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardEarningItemSchema(BaseModel):
    """Single earning item."""

    code: str = Field(..., description="Earning code")
    description: str = Field(..., description="Earning description")
    amount: Decimal = Field(..., description="Amount")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardDeductionItemSchema(BaseModel):
    """Single deduction item."""

    code: str = Field(..., description="Deduction code")
    description: str = Field(..., description="Deduction description")
    amount: Decimal = Field(..., description="Amount")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardEarningsSchema(BaseModel):
    """Earnings section."""

    items: list[DashboardEarningItemSchema] = Field(
        default_factory=list, description="Earning line items"
    )
    total: Decimal = Field(..., description="Total earnings")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardDeductionsSchema(BaseModel):
    """Deductions section."""

    items: list[DashboardDeductionItemSchema] = Field(
        default_factory=list, description="Deduction line items"
    )
    total: Decimal = Field(..., description="Total deductions")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardSalarySchema(BaseModel):
    """Salary section."""

    gross: Decimal = Field(..., description="Gross salary")
    net: Decimal = Field(..., description="Net salary (take-home)")
    previous_net: Optional[Decimal] = Field(
        None, description="Previous month's net salary"
    )
    net_delta: Optional[Decimal] = Field(None, description="Change in net salary")
    net_delta_percent: Optional[Decimal] = Field(
        None,
        description=(
            "Percentage change in net salary; null when there is no previous "
            "month or the previous net was zero"
        ),
    )

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardAttendanceSchema(BaseModel):
    """Attendance section."""

    paid_days: Decimal = Field(..., description="Paid working days")
    missing_days: Decimal = Field(..., description="Missing/absent days")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardBracketSchema(BaseModel):
    """A progressive tax bracket as shown on the dashboard."""

    sort_order: int = Field(..., description="Bracket order within the schedule")
    lower_limit: Decimal = Field(..., description="Inclusive lower limit")
    upper_limit: Optional[Decimal] = Field(
        None, description="Exclusive upper limit; null for the final bracket"
    )
    rate: Decimal = Field(..., description="Marginal rate for this bracket")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardTaxSchema(BaseModel):
    """Tax section."""

    income_tax: Decimal = Field(..., description="Monthly income tax")
    monthly_taxable_base: Optional[Decimal] = Field(
        None, description="Taxable base for this month; null if no ledger record"
    )
    cumulative_tax_base: Decimal = Field(
        ..., description="Cumulative tax base year-to-date"
    )
    current_bracket_rate: Optional[Decimal] = Field(
        None, description="Current tax bracket rate"
    )
    next_bracket_rate: Optional[Decimal] = Field(
        None, description="Next tax bracket rate"
    )
    distance_to_next_bracket: Optional[Decimal] = Field(
        None, description="Income needed to reach next bracket"
    )
    rule_set_version: Optional[str] = Field(
        None, description="Tax rule set version used to resolve the brackets"
    )
    current_bracket: Optional[DashboardBracketSchema] = Field(
        None, description="Bracket containing the cumulative base"
    )
    next_bracket: Optional[DashboardBracketSchema] = Field(
        None, description="Next bracket; null when already in the final bracket"
    )

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class DashboardPeriodSchema(BaseModel):
    """Period information."""

    year: int = Field(..., description="Tax year")
    month: int = Field(..., description="Month (1-12)")


class PayrollDashboardReadSchema(BaseModel):
    """Complete payroll dashboard."""

    employee_id: str = Field(..., description="UUID of employee")
    period: DashboardPeriodSchema = Field(..., description="Period information")
    salary: DashboardSalarySchema = Field(..., description="Salary details")
    earnings: DashboardEarningsSchema = Field(..., description="Earnings breakdown")
    deductions: DashboardDeductionsSchema = Field(..., description="Deductions breakdown")
    attendance: DashboardAttendanceSchema = Field(
        ..., description="Attendance information"
    )
    tax: DashboardTaxSchema = Field(..., description="Tax information")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}
