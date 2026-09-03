import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    CalculationMode,
    PayrollSourceType,
    PayrollVersionStatus,
)


class Payroll(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payrolls"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "period_year",
            "period_month",
            name="uq_payroll_employee_period",
        ),
        CheckConstraint(
            "period_month >= 1 AND period_month <= 12",
            name="ck_payroll_period_month",
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

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)

    employee = relationship("Employee", back_populates="payrolls")
    versions = relationship(
        "PayrollVersion",
        back_populates="payroll",
        cascade="all, delete-orphan",
    )


class PayrollVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_versions"
    __table_args__ = (
        UniqueConstraint(
            "payroll_id",
            "revision_no",
            name="uq_payroll_version_revision",
        ),
        CheckConstraint(
            "revision_no >= 1",
            name="ck_payroll_version_revision_positive",
        ),
        Index(
            "uq_payroll_version_current",
            "payroll_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    payroll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payrolls.id", ondelete="CASCADE"),
        nullable=False,
    )

    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[PayrollVersionStatus] = mapped_column(nullable=False)
    source_type: Mapped[PayrollSourceType] = mapped_column(nullable=False)

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="TRY",
    )

    gross_earnings: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    sgk_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    income_tax_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    stamp_tax_base: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    employee_sgk: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    employee_unemployment: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    income_tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    stamp_tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    total_earnings: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    total_deductions: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    net_pay: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    paid_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    missing_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    calculation_mode: Mapped[CalculationMode] = mapped_column(nullable=False)

    calculation_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    rule_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_rule_sets.id", ondelete="RESTRICT"),
        nullable=True,
    )

    source_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    source_checksum: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    payroll = relationship("Payroll", back_populates="versions")

    rule_set = relationship(
        "TaxRuleSet",
        back_populates="payroll_versions",
    )

    earnings = relationship(
        "PayrollEarning",
        back_populates="payroll_version",
        cascade="all, delete-orphan",
    )

    deductions = relationship(
        "PayrollDeduction",
        back_populates="payroll_version",
        cascade="all, delete-orphan",
    )

    absences = relationship(
        "PayrollAbsence",
        back_populates="payroll_version",
        cascade="all, delete-orphan",
    )
