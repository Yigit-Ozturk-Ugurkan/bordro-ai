"""
Pydantic schemas for payroll comparison.

Validates and serializes comparison data at API boundary.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ComparisonCodeDeltaSchema(BaseModel):
    """Previous/current/delta for one earning or deduction code."""

    previous: Decimal = Field(..., description="Amount in the previous period")
    current: Decimal = Field(..., description="Amount in the current period")
    delta: Decimal = Field(..., description="Change for this code")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class ComparisonNetSchema(BaseModel):
    """Net salary comparison data."""

    previous: Decimal = Field(..., description="Previous net salary")
    current: Decimal = Field(..., description="Current net salary")
    delta: Decimal = Field(..., description="Change in net salary")
    delta_percent: Optional[Decimal] = Field(
        None, description="Percentage change (None if previous was zero)"
    )

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class ComparisonEarningsSchema(BaseModel):
    """Earnings comparison data."""

    previous: Decimal = Field(..., description="Previous total earnings")
    current: Decimal = Field(..., description="Current total earnings")
    delta: Decimal = Field(..., description="Change in earnings")
    delta_percent: Optional[Decimal] = Field(
        None, description="Percentage change (None if previous was zero)"
    )
    by_code: dict[str, ComparisonCodeDeltaSchema] = Field(
        default_factory=dict, description="Code-level earning deltas"
    )

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class ComparisonDeductionsSchema(BaseModel):
    """Deductions comparison data."""

    previous: Decimal = Field(..., description="Previous total deductions")
    current: Decimal = Field(..., description="Current total deductions")
    delta: Decimal = Field(..., description="Change in deductions")
    delta_percent: Optional[Decimal] = Field(
        None, description="Percentage change (None if previous was zero)"
    )
    by_code: dict[str, ComparisonCodeDeltaSchema] = Field(
        default_factory=dict, description="Code-level deduction deltas"
    )

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class ComparisonAttendanceSchema(BaseModel):
    """Attendance comparison data."""

    previous_missing_days: Decimal = Field(..., description="Previous missing days")
    current_missing_days: Decimal = Field(..., description="Current missing days")
    missing_days_delta: Decimal = Field(..., description="Change in missing days")

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}


class PayrollComparisonReadSchema(BaseModel):
    """Complete payroll comparison result."""

    previous_payroll_version_id: str = Field(
        ..., description="UUID of previous payroll version"
    )
    current_payroll_version_id: str = Field(
        ..., description="UUID of current payroll version"
    )
    employee_id: str = Field(..., description="UUID of employee")
    comparison_date: datetime = Field(..., description="When comparison was created")

    net: ComparisonNetSchema = Field(..., description="Net salary comparison")
    earnings: ComparisonEarningsSchema = Field(..., description="Earnings comparison")
    deductions: ComparisonDeductionsSchema = Field(
        ..., description="Deductions comparison"
    )
    attendance: ComparisonAttendanceSchema = Field(
        ..., description="Attendance comparison"
    )

    model_config = {"json_encoders": {Decimal: lambda v: str(v)}}
