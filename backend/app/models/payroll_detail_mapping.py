"""Deterministic mapping, reviewed snapshots, and materialization evidence."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, ForeignKey, ForeignKeyConstraint,
    Index, Integer, Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    PayrollDetailMappingStatus, PayrollDetailReviewStatus, PayrollDetailType,
    PayrollFieldMappingScope,
)


class PayrollDetailMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_detail_mappings"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_detail_mapping_priority"),
        CheckConstraint("version >= 1", name="ck_detail_mapping_version"),
        CheckConstraint(
            "(scope = 'SYSTEM' AND organization_id IS NULL AND template_external_id IS NULL) OR "
            "(scope = 'ORGANIZATION' AND organization_id IS NOT NULL AND template_external_id IS NULL) OR "
            "(scope = 'TEMPLATE' AND organization_id IS NOT NULL AND template_external_id IS NOT NULL)",
            name="ck_detail_mapping_scope_shape",
        ),
        Index("ix_detail_mapping_match", "organization_id", "source_label_normalized", "is_active"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True,
    )
    scope: Mapped[PayrollFieldMappingScope] = mapped_column(
        Enum(PayrollFieldMappingScope, name="payrollfieldmappingscope", create_type=False), nullable=False,
    )
    template_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_label_normalized: Mapped[str] = mapped_column(String(500), nullable=False)
    label_column_id: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_column_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity_column_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rate_column_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail_type: Mapped[PayrollDetailType] = mapped_column(
        Enum(PayrollDetailType, name="payrolldetailtype"), nullable=False,
    )
    canonical_code: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    target_values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )


class PayrollImportMappedDetail(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_import_mapped_details"
    __table_args__ = (
        ForeignKeyConstraint(["payroll_import_id", "organization_id"],
                             ["payroll_imports.id", "payroll_imports.organization_id"],
                             name="fk_mapped_detail_import_org", ondelete="CASCADE"),
        ForeignKeyConstraint(["source_table_id", "organization_id"],
                             ["payroll_import_tables.id", "payroll_import_tables.organization_id"],
                             name="fk_mapped_detail_table_org", ondelete="CASCADE"),
        ForeignKeyConstraint(["source_row_id", "source_table_id", "organization_id"],
                             ["payroll_import_table_rows.id", "payroll_import_table_rows.table_id", "payroll_import_table_rows.organization_id"],
                             name="fk_mapped_detail_row_org", ondelete="CASCADE"),
        UniqueConstraint("source_row_id", name="uq_mapped_detail_source_row"),
        UniqueConstraint("id", "organization_id", name="uq_mapped_detail_id_org"),
        CheckConstraint("length(source_checksum) = 64", name="ck_mapped_detail_source_checksum"),
        CheckConstraint("source_table_index >= 0", name="ck_mapped_detail_table_index"),
        CheckConstraint("source_row_index >= 0", name="ck_mapped_detail_row_index"),
        Index("ix_mapped_detail_org_import", "organization_id", "payroll_import_id"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_table_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_detail_mappings.id", ondelete="RESTRICT"), nullable=True,
    )
    mapping_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_values: Mapped[list] = mapped_column(JSONB, nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_type: Mapped[PayrollDetailType] = mapped_column(
        Enum(PayrollDetailType, name="payrolldetailtype", create_type=False), nullable=False,
    )
    canonical_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    target_values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mapping_status: Mapped[PayrollDetailMappingStatus] = mapped_column(
        Enum(PayrollDetailMappingStatus, name="payrolldetailmappingstatus"), nullable=False,
    )
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PayrollImportDetailReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_import_detail_reviews"
    __table_args__ = (
        ForeignKeyConstraint(["payroll_import_id", "organization_id"],
                             ["payroll_imports.id", "payroll_imports.organization_id"],
                             name="fk_detail_review_import_org", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["current_snapshot_id", "organization_id", "payroll_import_id"],
            ["payroll_import_detail_snapshots.id",
             "payroll_import_detail_snapshots.organization_id",
             "payroll_import_detail_snapshots.payroll_import_id"],
            name="fk_detail_review_current_snapshot_scope", ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint("payroll_import_id", name="uq_detail_review_import"),
        CheckConstraint("row_version >= 1", name="ck_detail_review_row_version"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[PayrollDetailReviewStatus] = mapped_column(
        Enum(PayrollDetailReviewStatus, name="payrolldetailreviewstatus"), nullable=False,
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mapping_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class PayrollImportDetailCorrection(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_detail_corrections"
    __table_args__ = (
        ForeignKeyConstraint(["payroll_import_id", "organization_id"],
                             ["payroll_imports.id", "payroll_imports.organization_id"],
                             name="fk_detail_correction_import_org", ondelete="RESTRICT"),
        ForeignKeyConstraint(["mapped_detail_id", "organization_id"],
                             ["payroll_import_mapped_details.id", "payroll_import_mapped_details.organization_id"],
                             name="fk_detail_correction_mapped_org", ondelete="RESTRICT"),
        UniqueConstraint("mapped_detail_id", "revision", name="uq_detail_correction_revision"),
        UniqueConstraint("id", "organization_id", "payroll_import_id",
                         name="uq_detail_correction_scope"),
        CheckConstraint("revision >= 1", name="ck_detail_correction_revision"),
        CheckConstraint("length(source_checksum) = 64", name="ck_detail_correction_source_checksum"),
        Index("ix_detail_correction_import", "organization_id", "payroll_import_id"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mapped_detail_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    detail_type: Mapped[PayrollDetailType] = mapped_column(
        Enum(PayrollDetailType, name="payrolldetailtype", create_type=False), nullable=False,
    )
    canonical_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    target_values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PayrollImportDetailSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_detail_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["payroll_import_id", "organization_id"],
                             ["payroll_imports.id", "payroll_imports.organization_id"],
                             name="fk_detail_snapshot_import_org", ondelete="RESTRICT"),
        UniqueConstraint("payroll_import_id", "revision", name="uq_detail_snapshot_revision"),
        UniqueConstraint("id", "organization_id", "payroll_import_id", name="uq_detail_snapshot_scope"),
        CheckConstraint("revision >= 1", name="ck_detail_snapshot_revision"),
        CheckConstraint("row_count >= 0", name="ck_detail_snapshot_row_count"),
        CheckConstraint("length(snapshot_checksum) = 64", name="ck_detail_snapshot_checksum"),
        Index("ix_detail_snapshot_import", "organization_id", "payroll_import_id", "revision"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    corrections_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    finalized_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    rows = relationship("PayrollImportDetailSnapshotRow", cascade="all, delete-orphan", order_by="PayrollImportDetailSnapshotRow.row_order")


class PayrollImportDetailSnapshotRow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_detail_snapshot_rows"
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_id", "organization_id", "payroll_import_id"],
                             ["payroll_import_detail_snapshots.id", "payroll_import_detail_snapshots.organization_id", "payroll_import_detail_snapshots.payroll_import_id"],
                             name="fk_detail_snapshot_row_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["source_row_id", "source_table_id", "organization_id"],
                             ["payroll_import_table_rows.id", "payroll_import_table_rows.table_id", "payroll_import_table_rows.organization_id"],
                             name="fk_detail_snapshot_row_source_org", ondelete="RESTRICT"),
        ForeignKeyConstraint(["source_table_id", "organization_id"],
                             ["payroll_import_tables.id", "payroll_import_tables.organization_id"],
                             name="fk_detail_snapshot_row_table_org", ondelete="RESTRICT"),
        ForeignKeyConstraint(["correction_id", "organization_id", "payroll_import_id"],
                             ["payroll_import_detail_corrections.id", "payroll_import_detail_corrections.organization_id", "payroll_import_detail_corrections.payroll_import_id"],
                             name="fk_detail_snapshot_row_correction_scope", ondelete="RESTRICT"),
        UniqueConstraint("snapshot_id", "source_row_id", name="uq_detail_snapshot_source_row"),
        UniqueConstraint("id", "organization_id", name="uq_detail_snapshot_row_id_org"),
        CheckConstraint("row_order >= 0", name="ck_detail_snapshot_row_order"),
        CheckConstraint("length(source_checksum) = 64", name="ck_detail_snapshot_row_source_checksum"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    correction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_type: Mapped[PayrollDetailType] = mapped_column(
        Enum(PayrollDetailType, name="payrolldetailtype", create_type=False), nullable=False,
    )
    canonical_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    target_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(
            "users.id", name="fk_detail_snapshot_row_reviewer", ondelete="RESTRICT",
        ), nullable=False,
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PayrollImportDetailMaterialization(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_detail_materializations"
    __table_args__ = (
        ForeignKeyConstraint(["payroll_import_id", "organization_id"],
                             ["payroll_imports.id", "payroll_imports.organization_id"],
                             name="fk_detail_materialization_import_org", ondelete="RESTRICT"),
        ForeignKeyConstraint(["detail_snapshot_id", "organization_id", "payroll_import_id"],
                             ["payroll_import_detail_snapshots.id", "payroll_import_detail_snapshots.organization_id", "payroll_import_detail_snapshots.payroll_import_id"],
                             name="fk_detail_materialization_snapshot_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["approval_id", "organization_id", "payroll_import_id"],
                             ["payroll_import_approvals.id", "payroll_import_approvals.organization_id", "payroll_import_approvals.payroll_import_id"],
                             name="fk_detail_materialization_approval_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["payroll_materialization_id", "organization_id", "payroll_import_id", "payroll_id", "payroll_version_id"],
                             ["payroll_import_materializations.id", "payroll_import_materializations.organization_id", "payroll_import_materializations.payroll_import_id", "payroll_import_materializations.payroll_id", "payroll_import_materializations.payroll_version_id"],
                             name="fk_detail_materialization_payroll_scope", ondelete="RESTRICT"),
        UniqueConstraint("payroll_materialization_id", name="uq_detail_materialization_payroll"),
        UniqueConstraint("id", "organization_id", "payroll_version_id", name="uq_detail_materialization_target_scope"),
        CheckConstraint("length(materialization_checksum) = 64", name="ck_detail_materialization_checksum"),
        CheckConstraint("earning_count >= 0 AND deduction_count >= 0 AND absence_count >= 0",
                        name="ck_detail_materialization_counts"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    detail_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_materialization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    materialization_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    earning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    deduction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    absence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    materialized_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    materialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = [name for name in globals() if name.startswith("Payroll")]
