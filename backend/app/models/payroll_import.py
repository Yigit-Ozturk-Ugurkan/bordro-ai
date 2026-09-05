"""Durable, organization-scoped document import and generic staging models."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    func,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PayrollImportFieldReviewStatus, PayrollImportStatus


class PayrollImport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_imports"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "content_sha256",
            name="uq_payroll_import_org_content_sha256",
        ),
        UniqueConstraint(
            "id", "organization_id", name="uq_payroll_import_id_org",
        ),
        Index("ix_payroll_import_org_status", "organization_id", "status"),
        Index("ix_payroll_import_org_created", "organization_id", "created_at"),
        CheckConstraint(
            "detected_month IS NULL OR (detected_month >= 1 AND detected_month <= 12)",
            name="ck_payroll_import_detected_month",
        ),
        CheckConstraint(
            "processing_attempt >= 0", name="ck_payroll_import_processing_attempt",
        ),
        CheckConstraint(
            "template_match_score IS NULL OR "
            "(template_match_score >= 0 AND template_match_score <= 1)",
            name="ck_payroll_import_template_match_score",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[PayrollImportStatus] = mapped_column(
        Enum(PayrollImportStatus, name="payrollimportstatus"), nullable=False,
        default=PayrollImportStatus.UPLOADED,
    )
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="DOCUMENT_UPLOAD"
    )
    reader_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="GENERAL_READER"
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    detected_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    detected_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    template_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template_match_score: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 8), nullable=True
    )
    extraction_schema_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    reader_table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reader_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    processing_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    documents = relationship(
        "PayrollImportDocument", back_populates="payroll_import",
        cascade="all, delete-orphan",
    )
    fields = relationship(
        "PayrollImportField", back_populates="payroll_import",
        cascade="all, delete-orphan", overlaps="document,fields",
    )


class PayrollImportDocument(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payroll_import_documents"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_payroll_import_document_file_id"),
        UniqueConstraint("storage_key", name="uq_payroll_import_document_storage_key"),
        UniqueConstraint(
            "id", "payroll_import_id", "organization_id",
            name="uq_payroll_import_document_identity_scope",
        ),
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            ondelete="CASCADE", name="fk_import_document_import_org",
        ),
        Index(
            "ix_payroll_import_document_org_import",
            "organization_id", "payroll_import_id",
        ),
        CheckConstraint("size_bytes > 0", name="ck_import_document_size_positive"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reader_document_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payroll_import = relationship("PayrollImport", back_populates="documents")
    fields = relationship(
        "PayrollImportField", back_populates="document",
        cascade="all, delete-orphan", overlaps="fields,payroll_import",
    )


class PayrollImportField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payroll_import_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            ondelete="CASCADE", name="fk_import_field_import_org",
        ),
        ForeignKeyConstraint(
            ["payroll_import_document_id", "payroll_import_id", "organization_id"],
            ["payroll_import_documents.id", "payroll_import_documents.payroll_import_id",
             "payroll_import_documents.organization_id"],
            ondelete="CASCADE", name="fk_import_field_document_scope",
        ),
        UniqueConstraint(
            "payroll_import_document_id", "source_field_id", "page_number",
            name="uq_payroll_import_field_source_page",
        ),
        Index(
            "ix_payroll_import_field_org_import",
            "organization_id", "payroll_import_id",
        ),
        Index(
            "ix_payroll_import_field_import_source",
            "payroll_import_id", "source_field_id",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_payroll_import_field_confidence",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_import_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    source_field_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_label: Mapped[str] = mapped_column(String(500), nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    coordinate_space: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extraction_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rule_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    missing_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_status: Mapped[PayrollImportFieldReviewStatus] = mapped_column(
        Enum(PayrollImportFieldReviewStatus, name="payrollimportfieldreviewstatus"),
        nullable=False,
    )

    payroll_import = relationship(
        "PayrollImport", back_populates="fields", overlaps="document,fields"
    )
    document = relationship(
        "PayrollImportDocument", back_populates="fields",
        overlaps="fields,payroll_import",
    )
