"""
Pydantic v2 schemas for tax domain models.

These schemas enforce validation at the API boundary.
Financial values remain as Decimal — never converted to float.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# TaxRuleSet
# ---------------------------------------------------------------------------


class TaxRuleSetBase(BaseModel):
    """Shared fields for TaxRuleSet create/read."""

    jurisdiction: str = Field(..., max_length=20)
    name: str = Field(..., max_length=150)
    version: str = Field(..., max_length=100)
    effective_from: date
    effective_to: date | None = None
    source_reference: str | None = Field(default=None, max_length=500)
    status: str = Field(..., max_length=30)

    @model_validator(mode="after")
    def validate_effective_range(self) -> "TaxRuleSetBase":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class TaxRuleSetCreate(TaxRuleSetBase):
    """Schema for creating a TaxRuleSet."""

    pass


class TaxRuleSetRead(TaxRuleSetBase):
    """Schema for reading a TaxRuleSet from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# TaxBracket
# ---------------------------------------------------------------------------


class TaxBracketBase(BaseModel):
    """Shared fields for TaxBracket create/read."""

    income_type: str = Field(..., max_length=50)
    effective_from: date
    effective_to: date | None = None
    lower_limit: Decimal = Field(..., ge=Decimal("0"))
    upper_limit: Decimal | None = None
    rate: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    base_tax_amount: Decimal = Field(..., ge=Decimal("0"))
    sort_order: int = Field(..., ge=1)

    @model_validator(mode="after")
    def validate_limits_and_dates(self) -> "TaxBracketBase":
        if self.upper_limit is not None and self.upper_limit <= self.lower_limit:
            raise ValueError("upper_limit must be greater than lower_limit")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class TaxBracketCreate(TaxBracketBase):
    """Schema for creating a TaxBracket (rule_set_id set by service)."""

    pass


class TaxBracketRead(TaxBracketBase):
    """Schema for reading a TaxBracket from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_set_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# PayrollParameter
# ---------------------------------------------------------------------------


class PayrollParameterBase(BaseModel):
    """Shared fields for PayrollParameter create/read."""

    parameter_key: str = Field(..., max_length=100)
    effective_from: date
    effective_to: date | None = None
    decimal_value: Decimal | None = None
    text_value: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=50)
    source_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_has_value_and_dates(self) -> "PayrollParameterBase":
        if self.decimal_value is None and self.text_value is None:
            raise ValueError(
                "At least one of decimal_value or text_value must be provided"
            )
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class PayrollParameterCreate(PayrollParameterBase):
    """Schema for creating a PayrollParameter (rule_set_id set by service)."""

    pass


class PayrollParameterRead(PayrollParameterBase):
    """Schema for reading a PayrollParameter from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_set_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# TaxCalculationRun
# ---------------------------------------------------------------------------


class TaxCalculationRunBase(BaseModel):
    """Shared fields for TaxCalculationRun create/read."""

    tax_year: int = Field(..., ge=2000)
    trigger_type: str = Field(..., max_length=40)
    status: str = Field(..., max_length=30)
    calculation_version: str = Field(..., max_length=50)


class TaxCalculationRunCreate(TaxCalculationRunBase):
    """Schema for creating a TaxCalculationRun."""

    organization_id: uuid.UUID
    employee_id: uuid.UUID
    rule_set_id: uuid.UUID


class TaxCalculationRunRead(TaxCalculationRunBase):
    """Schema for reading a TaxCalculationRun from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    rule_set_id: uuid.UUID
    started_at: datetime
    completed_at: datetime | None


# ---------------------------------------------------------------------------
# TaxCumulativeRecord
# ---------------------------------------------------------------------------


class TaxCumulativeRecordBase(BaseModel):
    """Shared fields for TaxCumulativeRecord create/read."""

    tax_year: int = Field(..., ge=2000)
    period_month: int = Field(..., ge=1, le=12)
    opening_cumulative_base: Decimal = Field(..., ge=Decimal("0"))
    monthly_taxable_base: Decimal = Field(..., ge=Decimal("0"))
    closing_cumulative_base: Decimal = Field(..., ge=Decimal("0"))
    gross_calculated_tax: Decimal = Field(..., ge=Decimal("0"))
    tax_exemptions: Decimal = Field(..., ge=Decimal("0"))
    withholding_tax: Decimal = Field(..., ge=Decimal("0"))
    effective_tax_rate: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def validate_closing_gte_opening(self) -> "TaxCumulativeRecordBase":
        if self.closing_cumulative_base < self.opening_cumulative_base:
            raise ValueError(
                "closing_cumulative_base must be >= opening_cumulative_base"
            )
        return self


class TaxCumulativeRecordCreate(TaxCumulativeRecordBase):
    """Schema for creating a TaxCumulativeRecord."""

    employee_id: uuid.UUID
    payroll_version_id: uuid.UUID


class TaxCumulativeRecordRead(TaxCumulativeRecordBase):
    """Schema for reading a TaxCumulativeRecord from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    calculation_run_id: uuid.UUID
    employee_id: uuid.UUID
    payroll_version_id: uuid.UUID
    created_at: datetime
