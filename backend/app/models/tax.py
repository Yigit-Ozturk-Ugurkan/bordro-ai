"""
Tax domain models: rule sets, brackets, parameters, calculation runs,
and cumulative records.

These models form the foundation for Türkiye's progressive income tax
system with year-based cumulative tracking.

Design decisions:
- Status and trigger fields are VARCHAR (not DB enums) to avoid schema
  migration when adding new statuses.
- Effective dating uses [effective_from, effective_to) — inclusive start,
  exclusive end. effective_to = NULL means open-ended (currently active).
- ON DELETE RESTRICT on rule_set references: tax history must not be
  accidentally destroyed.
- TaxCalculationRun preserves history: old runs are never deleted or
  overwritten. A payroll revision triggers a new run.
- TaxCumulativeRecord tracks monthly cumulative state per employee per
  tax year, enabling progressive bracket application and year-reset.
- Financial amounts: NUMERIC(18,2). Rates: NUMERIC(9,6).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin


class TaxRuleSet(UUIDPrimaryKeyMixin, Base):
    """
    A versioned collection of tax rules for a specific jurisdiction.

    Each rule set has an effective date range and contains:
    - Tax brackets (progressive income tax rates)
    - Payroll parameters (SGK rates, minimum wage, ceilings, etc.)

    The 'version' field is globally unique and serves as the human-readable
    identifier for this rule set (e.g., 'TR_PAYROLL_2026_V1').

    Status values (VARCHAR, not enum):
    - DRAFT: under development, not yet usable for calculations
    - ACTIVE: currently in use for payroll calculations
    - RETIRED: replaced by a newer version, kept for historical reference
    """

    __tablename__ = "tax_rule_sets"
    __table_args__ = (
        UniqueConstraint(
            "version",
            name="uq_tax_rule_set_version",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_tax_rule_set_effective_range",
        ),
    )

    jurisdiction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    effective_to: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    brackets = relationship(
        "TaxBracket",
        back_populates="rule_set",
        cascade="all, delete-orphan",
    )

    parameters = relationship(
        "PayrollParameter",
        back_populates="rule_set",
        cascade="all, delete-orphan",
    )

    calculation_runs = relationship(
        "TaxCalculationRun",
        back_populates="rule_set",
    )

    payroll_versions = relationship(
        "PayrollVersion",
        back_populates="rule_set",
    )


class TaxBracket(UUIDPrimaryKeyMixin, Base):
    """
    A single bracket in a progressive income tax schedule.

    Brackets are ordered by sort_order within a rule_set + income_type
    combination. The final bracket typically has upper_limit = NULL
    (open-ended).

    Example for TR employment income 2026:
        sort_order=1: 0 → 190,000 @ 15% (base_tax=0)
        sort_order=2: 190,000 → 400,000 @ 20% (base_tax=28,500)
        sort_order=3: 400,000 → 1,500,000 @ 27% (base_tax=70,500)
        sort_order=4: 1,500,000 → 5,300,000 @ 35% (base_tax=367,500)
        sort_order=5: 5,300,000 → ∞ @ 40% (base_tax=1,697,500)

    base_tax_amount is the cumulative tax from all lower brackets,
    used for direct bracket-based calculation without iterating.
    """

    __tablename__ = "tax_brackets"
    __table_args__ = (
        UniqueConstraint(
            "rule_set_id",
            "income_type",
            "sort_order",
            name="uq_tax_bracket_rule_set_type_order",
        ),
        CheckConstraint(
            "lower_limit >= 0",
            name="ck_tax_bracket_lower_non_negative",
        ),
        CheckConstraint(
            "upper_limit IS NULL OR upper_limit > lower_limit",
            name="ck_tax_bracket_upper_gt_lower",
        ),
        CheckConstraint(
            "rate >= 0 AND rate <= 1",
            name="ck_tax_bracket_rate_valid_range",
        ),
        CheckConstraint(
            "base_tax_amount >= 0",
            name="ck_tax_bracket_base_tax_non_negative",
        ),
        CheckConstraint(
            "sort_order >= 1",
            name="ck_tax_bracket_sort_order_positive",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_tax_bracket_effective_range",
        ),
        Index(
            "ix_tax_brackets_rule_set_id",
            "rule_set_id",
        ),
    )

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_rule_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )

    income_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    effective_to: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    lower_limit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    upper_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    rate: Mapped[Decimal] = mapped_column(
        Numeric(9, 6),
        nullable=False,
    )

    base_tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    rule_set = relationship(
        "TaxRuleSet",
        back_populates="brackets",
    )


class PayrollParameter(UUIDPrimaryKeyMixin, Base):
    """
    An effective-dated payroll/tax parameter within a rule set.

    Examples:
    - MINIMUM_GROSS_WAGE = 33030.00
    - SGK_EMPLOYEE_RATE = 0.14
    - SGK_MONTHLY_EARNINGS_CEILING = 297270.00

    At least one of decimal_value or text_value must be set.
    Both cannot be NULL simultaneously.
    """

    __tablename__ = "payroll_parameters"
    __table_args__ = (
        CheckConstraint(
            "decimal_value IS NOT NULL OR text_value IS NOT NULL",
            name="ck_payroll_parameter_has_value",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_payroll_parameter_effective_range",
        ),
        Index(
            "ix_payroll_parameters_rule_set_key",
            "rule_set_id",
            "parameter_key",
        ),
    )

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_rule_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )

    parameter_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    effective_to: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    decimal_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )

    text_value: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    rule_set = relationship(
        "TaxRuleSet",
        back_populates="parameters",
    )


class TaxCalculationRun(UUIDPrimaryKeyMixin, Base):
    """
    An immutable record of a tax calculation execution.

    Each recalculation produces a new run — old runs are never overwritten.
    This enables full audit trail of how cumulative tax was computed over time.

    Trigger types (VARCHAR):
    - MONTHLY_PAYROLL: standard monthly processing
    - PAYROLL_REVISION: triggered by a payroll version change
    - MANUAL_RECALCULATION: user-initiated recalculation
    - IMPORT: initial data import

    Status values (VARCHAR):
    - RUNNING: calculation in progress
    - COMPLETED: successfully finished
    - FAILED: calculation encountered an error
    """

    __tablename__ = "tax_calculation_runs"
    __table_args__ = (
        CheckConstraint(
            "tax_year >= 2000",
            name="ck_tax_calc_run_tax_year_valid",
        ),
        Index(
            "ix_tax_calc_runs_org_id",
            "organization_id",
        ),
        Index(
            "ix_tax_calc_runs_employee_id",
            "employee_id",
        ),
        Index(
            "ix_tax_calc_runs_rule_set_id",
            "rule_set_id",
        ),
        Index(
            "ix_tax_calc_runs_payroll_version_id",
            "payroll_version_id",
        ),
        UniqueConstraint(
            "id", "organization_id", "employee_id", "tax_year",
            "rule_set_id", "payroll_version_id",
            name="uq_tax_calc_run_sync_scope",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )

    tax_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_rule_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )

    payroll_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )

    trigger_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    calculation_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    organization = relationship("Organization")
    employee = relationship("Employee")
    rule_set = relationship(
        "TaxRuleSet",
        back_populates="calculation_runs",
    )
    cumulative_records = relationship(
        "TaxCumulativeRecord",
        back_populates="calculation_run",
        cascade="all, delete-orphan",
    )


class TaxCumulativeRecord(UUIDPrimaryKeyMixin, Base):
    """
    Monthly cumulative income tax state for an employee in a tax year.

    Tracks the progressive accumulation of taxable income and computed tax
    across months within a single tax year. When a new year begins,
    opening_cumulative_base resets to 0.

    Key fields:
    - opening_cumulative_base: cumulative taxable base at start of this month
    - monthly_taxable_base: this month's taxable income
    - closing_cumulative_base: cumulative taxable base at end of this month
    - gross_calculated_tax: total progressive tax on closing_cumulative_base
    - tax_exemptions: any exemptions/credits applied
    - withholding_tax: gross_calculated_tax - prior months' tax - exemptions
    - effective_tax_rate: withholding_tax / monthly_taxable_base

    Note: closing_cumulative_base >= opening_cumulative_base is enforced at
    DB level. However, the invariant closing = opening + monthly is NOT
    enforced as a DB check to allow controlled exceptions during
    reconciliation or adjustment scenarios.
    """

    __tablename__ = "tax_cumulative_records"
    __table_args__ = (
        UniqueConstraint(
            "calculation_run_id",
            "employee_id",
            "tax_year",
            "period_month",
            name="uq_tax_cumulative_run_emp_year_month",
        ),
        UniqueConstraint(
            "id", "calculation_run_id", "employee_id", "payroll_version_id",
            "tax_year", "period_month",
            name="uq_tax_cumulative_sync_scope",
        ),
        UniqueConstraint(
            "supersedes_record_id",
            name="uq_tax_cumulative_supersedes_record",
        ),
        CheckConstraint(
            "tax_year >= 2000",
            name="ck_tax_cumulative_tax_year_valid",
        ),
        CheckConstraint(
            "period_month >= 1 AND period_month <= 12",
            name="ck_tax_cumulative_period_month_valid",
        ),
        CheckConstraint(
            "opening_cumulative_base >= 0",
            name="ck_tax_cumulative_opening_base_non_negative",
        ),
        CheckConstraint(
            "monthly_taxable_base >= 0",
            name="ck_tax_cumulative_monthly_base_non_negative",
        ),
        CheckConstraint(
            "closing_cumulative_base >= 0",
            name="ck_tax_cumulative_closing_base_non_negative",
        ),
        CheckConstraint(
            "closing_cumulative_base >= opening_cumulative_base",
            name="ck_tax_cumulative_closing_gte_opening",
        ),
        CheckConstraint(
            "gross_calculated_tax >= 0",
            name="ck_tax_cumulative_gross_tax_non_negative",
        ),
        CheckConstraint(
            "tax_exemptions >= 0",
            name="ck_tax_cumulative_exemptions_non_negative",
        ),
        CheckConstraint(
            "withholding_tax >= 0",
            name="ck_tax_cumulative_withholding_non_negative",
        ),
        CheckConstraint(
            "effective_tax_rate >= 0 AND effective_tax_rate <= 1",
            name="ck_tax_cumulative_effective_rate_valid",
        ),
        Index(
            "ix_tax_cumulative_employee_year_month",
            "employee_id",
            "tax_year",
            "period_month",
        ),
        Index(
            "ix_tax_cumulative_calc_run_id",
            "calculation_run_id",
        ),
        Index(
            "ix_tax_cumulative_payroll_version_id",
            "payroll_version_id",
        ),
        Index(
            "uq_tax_cumulative_current_period",
            "employee_id", "tax_year", "period_month",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    calculation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_calculation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )

    payroll_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    tax_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    period_month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    opening_cumulative_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    monthly_taxable_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    closing_cumulative_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    gross_calculated_tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    tax_exemptions: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    withholding_tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    effective_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(9, 6),
        nullable=False,
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )

    supersedes_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_cumulative_records.id", ondelete="RESTRICT"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    calculation_run = relationship(
        "TaxCalculationRun",
        back_populates="cumulative_records",
    )
    employee = relationship("Employee")
    payroll_version = relationship("PayrollVersion")
