"""
Pydantic v2 schemas for payroll detail models.

These schemas enforce validation at the API boundary before data
reaches the database layer. Financial values remain as Decimal —
never converted to float.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# PayrollEarning
# ---------------------------------------------------------------------------


class PayrollEarningBase(BaseModel):
    """Shared fields for PayrollEarning create/read."""

    code: str = Field(..., max_length=100)
    label: str = Field(..., max_length=200)
    category: str = Field(..., max_length=100)
    quantity: Decimal | None = None
    unit_amount: Decimal | None = None
    amount: Decimal = Field(..., ge=Decimal("0"))
    sgk_subject_amount: Decimal = Field(..., ge=Decimal("0"))
    income_tax_subject_amount: Decimal = Field(..., ge=Decimal("0"))
    stamp_tax_subject_amount: Decimal = Field(..., ge=Decimal("0"))


class PayrollEarningCreate(PayrollEarningBase):
    """Schema for creating a PayrollEarning (payroll_version_id set by service)."""

    pass


class PayrollEarningRead(PayrollEarningBase):
    """Schema for reading a PayrollEarning from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payroll_version_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# PayrollDeduction
# ---------------------------------------------------------------------------


class PayrollDeductionBase(BaseModel):
    """Shared fields for PayrollDeduction create/read."""

    code: str = Field(..., max_length=100)
    label: str = Field(..., max_length=200)
    category: str = Field(..., max_length=100)
    amount: Decimal = Field(..., ge=Decimal("0"))
    base_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    rate: Decimal | None = None
    is_statutory: bool
    is_sensitive: bool = False

    @field_validator("rate")
    @classmethod
    def validate_rate_range(cls, v: Decimal | None) -> Decimal | None:
        if v is not None:
            if v < Decimal("0") or v > Decimal("1"):
                raise ValueError("rate must be between 0 and 1")
        return v


class PayrollDeductionCreate(PayrollDeductionBase):
    """Schema for creating a PayrollDeduction (payroll_version_id set by service)."""

    pass


class PayrollDeductionRead(PayrollDeductionBase):
    """Schema for reading a PayrollDeduction from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payroll_version_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# PayrollAbsence
# ---------------------------------------------------------------------------


class PayrollAbsenceBase(BaseModel):
    """
    Shared fields for PayrollAbsence create/read.

    Sign convention for gross_effect:
        * gross_effect <= 0 means the absence reduced gross earnings.
        * gross_effect = None means no financial impact data available.
    """

    reason_code: str = Field(..., max_length=100)
    description: str | None = Field(default=None, max_length=500)
    day_count: Decimal = Field(..., gt=Decimal("0"))
    is_paid: bool
    gross_effect: Decimal | None = None


class PayrollAbsenceCreate(PayrollAbsenceBase):
    """Schema for creating a PayrollAbsence (payroll_version_id set by service)."""

    pass


class PayrollAbsenceRead(PayrollAbsenceBase):
    """Schema for reading a PayrollAbsence from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payroll_version_id: uuid.UUID
    created_at: datetime
