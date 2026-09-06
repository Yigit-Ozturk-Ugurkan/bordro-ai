"""add reviewer corrections and immutable reviewed snapshots

Revision ID: e9c3f5a7b013
Revises: c8b2e4f6a012
Create Date: 2026-09-06 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e9c3f5a7b013"
down_revision: Union[str, Sequence[str], None] = "c8b2e4f6a012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

review_status = postgresql.ENUM(
    "IN_PROGRESS", "READY_FOR_SNAPSHOT", "SNAPSHOTTED",
    name="payrollimportreviewstatus", create_type=False,
)
correction_action = postgresql.ENUM(
    "APPLY", "REVERT", name="payrollreviewcorrectionaction", create_type=False,
)
field_status = postgresql.ENUM(
    "PENDING", "RESOLVED", "STALE", name="payrollreviewfieldstatus", create_type=False,
)
provenance = postgresql.ENUM(
    "ADAPTER", "REVIEWER_CORRECTION",
    name="payrollreviewvalueprovenance", create_type=False,
)
value_type = postgresql.ENUM(
    "DECIMAL", "INTEGER", "DAY_COUNT", "DATE", "TEXT", "IDENTIFIER",
    name="payrollcanonicalvaluetype", create_type=False,
)
mapping_status = postgresql.ENUM(
    "MAPPED", "UNMAPPED", "AMBIGUOUS", "PARSE_FAILED",
    name="payrollfieldmappingstatus", create_type=False,
)

KEY_CHECK = (
    "('employee_identifier','period_year','period_month','gross_earnings','sgk_base',"
    "'income_tax_base','stamp_tax_base','employee_sgk','employee_unemployment',"
    "'income_tax','stamp_tax','total_earnings','total_deductions','net_pay','paid_days',"
    "'missing_days','cumulative_income_tax_base')"
)


def upgrade() -> None:
    bind = op.get_bind()
    review_status.create(bind, checkfirst=True)
    correction_action.create(bind, checkfirst=True)
    field_status.create(bind, checkfirst=True)
    provenance.create(bind, checkfirst=True)

    op.create_table(
        "payroll_import_reviews",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("status", review_status, nullable=False),
        sa.Column("started_by_user_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_reviewed_by_user_id", sa.UUID(), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("current_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("adapter_output_checksum", sa.String(64), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("row_version >= 1", name="ck_import_review_row_version_positive"),
        sa.CheckConstraint(
            "length(adapter_output_checksum) = 64",
            name="ck_import_review_adapter_checksum_length",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_review_import_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["started_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_import_id", name="uq_import_review_payroll_import"),
        sa.UniqueConstraint(
            "id", "payroll_import_id", "organization_id",
            name="uq_import_review_identity_scope",
        ),
    )
    op.create_index(
        "ix_import_review_org_import", "payroll_import_reviews",
        ["organization_id", "payroll_import_id"],
    )

    op.create_table(
        "payroll_import_field_corrections",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_field_id", sa.UUID(), nullable=False),
        sa.Column("source_mapped_field_id", sa.UUID(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", correction_action, nullable=False),
        sa.Column("supersedes_correction_id", sa.UUID(), nullable=True),
        sa.Column("reviewer_user_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("adapter_fingerprint", sa.String(64), nullable=False),
        sa.Column("original_mapping_status", mapping_status, nullable=False),
        sa.Column("original_canonical_key", sa.String(100), nullable=True),
        sa.Column("original_value_type", value_type, nullable=True),
        sa.Column("original_value_text", sa.Text(), nullable=True),
        sa.Column("original_value_decimal", sa.Numeric(18, 2), nullable=True),
        sa.Column("original_value_integer", sa.Integer(), nullable=True),
        sa.Column("original_value_date", sa.Date(), nullable=True),
        sa.Column("override_canonical_key", sa.String(100), nullable=True),
        sa.Column("section_key", sa.String(50), nullable=True),
        sa.Column("value_type", value_type, nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_decimal", sa.Numeric(18, 2), nullable=True),
        sa.Column("value_integer", sa.Integer(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_field_correction_revision_positive"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_field_correction_reason_present"),
        sa.CheckConstraint(
            f"original_canonical_key IS NULL OR original_canonical_key IN {KEY_CHECK}",
            name="ck_field_correction_original_key",
        ),
        sa.CheckConstraint(
            f"override_canonical_key IS NULL OR override_canonical_key IN {KEY_CHECK}",
            name="ck_field_correction_override_key",
        ),
        sa.CheckConstraint(
            "(action = 'REVERT' AND override_canonical_key IS NULL AND section_key IS NULL "
            "AND value_type IS NULL AND value_text IS NULL AND value_decimal IS NULL "
            "AND value_integer IS NULL AND value_date IS NULL) OR "
            "(action = 'APPLY' AND value_type IS NOT NULL AND "
            "((override_canonical_key IS NULL AND section_key IS NULL) OR "
            "(override_canonical_key IS NOT NULL AND section_key IS NOT NULL)))",
            name="ck_field_correction_action_shape",
        ),
        sa.CheckConstraint(
            "action = 'REVERT' OR "
            "(value_type IN ('DECIMAL','DAY_COUNT') AND value_decimal IS NOT NULL "
            "AND value_text IS NULL AND value_integer IS NULL AND value_date IS NULL) OR "
            "(value_type = 'INTEGER' AND value_integer IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_date IS NULL) OR "
            "(value_type = 'DATE' AND value_date IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL) OR "
            "(value_type IN ('TEXT','IDENTIFIER') AND value_text IS NOT NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL AND value_date IS NULL)",
            name="ck_field_correction_typed_value",
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "payroll_import_id", "organization_id"],
            ["payroll_import_reviews.id", "payroll_import_reviews.payroll_import_id",
             "payroll_import_reviews.organization_id"],
            name="fk_field_correction_review_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_field_id", "payroll_import_id", "organization_id"],
            ["payroll_import_fields.id", "payroll_import_fields.payroll_import_id",
             "payroll_import_fields.organization_id"],
            name="fk_field_correction_source_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_correction_id"], ["payroll_import_field_corrections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_id", "payroll_import_field_id", "revision",
            name="uq_field_correction_review_source_revision",
        ),
    )
    op.create_index(
        "ix_field_correction_org_import", "payroll_import_field_corrections",
        ["organization_id", "payroll_import_id"],
    )
    op.create_index(
        "ix_field_correction_review_source", "payroll_import_field_corrections",
        ["review_id", "payroll_import_field_id", "revision"],
    )

    op.create_table(
        "payroll_import_review_snapshots",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_staging_checksum", sa.String(64), nullable=False),
        sa.Column("adapter_output_checksum", sa.String(64), nullable=False),
        sa.Column("review_corrections_checksum", sa.String(64), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("field_count", sa.Integer(), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_review_snapshot_version_positive"),
        sa.CheckConstraint("field_count >= 0", name="ck_review_snapshot_field_count"),
        sa.CheckConstraint("issue_count >= 0", name="ck_review_snapshot_issue_count"),
        sa.CheckConstraint(
            "length(source_staging_checksum) = 64 AND length(adapter_output_checksum) = 64 "
            "AND length(review_corrections_checksum) = 64 AND length(snapshot_checksum) = 64",
            name="ck_review_snapshot_checksum_lengths",
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "payroll_import_id", "organization_id"],
            ["payroll_import_reviews.id", "payroll_import_reviews.payroll_import_id",
             "payroll_import_reviews.organization_id"],
            name="fk_review_snapshot_review_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "snapshot_version", name="uq_review_snapshot_version"),
        sa.UniqueConstraint("id", "organization_id", name="uq_review_snapshot_id_org"),
        sa.UniqueConstraint(
            "id", "review_id", "payroll_import_id", "organization_id",
            name="uq_review_snapshot_identity_scope",
        ),
    )
    op.create_index(
        "ix_review_snapshot_org_import", "payroll_import_review_snapshots",
        ["organization_id", "payroll_import_id"],
    )
    op.create_foreign_key(
        "fk_import_review_current_snapshot_org", "payroll_import_reviews",
        "payroll_import_review_snapshots", ["current_snapshot_id", "organization_id"],
        ["id", "organization_id"], ondelete="RESTRICT",
    )

    op.create_table(
        "payroll_import_review_snapshot_fields",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("source_import_field_id", sa.UUID(), nullable=False),
        sa.Column("source_mapped_field_id", sa.UUID(), nullable=True),
        sa.Column("source_field_id", sa.String(200), nullable=False),
        sa.Column("source_label", sa.String(500), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("source_value_type", sa.String(50), nullable=True),
        sa.Column("effective_canonical_key", sa.String(100), nullable=True),
        sa.Column("section_key", sa.String(50), nullable=True),
        sa.Column("value_type", value_type, nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_decimal", sa.Numeric(18, 2), nullable=True),
        sa.Column("value_integer", sa.Integer(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("provenance", provenance, nullable=False),
        sa.Column("confidence", sa.Numeric(10, 8), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(), nullable=True),
        sa.Column("extraction_source", sa.String(50), nullable=True),
        sa.Column("original_mapping_status", mapping_status, nullable=False),
        sa.Column("review_status", field_status, nullable=False),
        sa.Column("correction_id", sa.UUID(), nullable=True),
        sa.Column("adapter_fingerprint", sa.String(64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            f"effective_canonical_key IS NULL OR effective_canonical_key IN {KEY_CHECK}",
            name="ck_snapshot_field_canonical_key",
        ),
        sa.CheckConstraint(
            "(effective_canonical_key IS NULL AND section_key IS NULL) OR "
            "(effective_canonical_key IS NOT NULL AND section_key IS NOT NULL)",
            name="ck_snapshot_field_canonical_shape",
        ),
        sa.CheckConstraint(
            "(value_type IN ('DECIMAL','DAY_COUNT') AND value_decimal IS NOT NULL "
            "AND value_text IS NULL AND value_integer IS NULL AND value_date IS NULL) OR "
            "(value_type = 'INTEGER' AND value_integer IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_date IS NULL) OR "
            "(value_type = 'DATE' AND value_date IS NOT NULL AND value_text IS NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL) OR "
            "(value_type IN ('TEXT','IDENTIFIER') AND value_text IS NOT NULL "
            "AND value_decimal IS NULL AND value_integer IS NULL AND value_date IS NULL)",
            name="ck_snapshot_field_typed_value",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "review_id", "payroll_import_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.review_id",
             "payroll_import_review_snapshots.payroll_import_id",
             "payroll_import_review_snapshots.organization_id"],
            name="fk_snapshot_field_snapshot_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "source_import_field_id", name="uq_snapshot_field_source"),
    )
    op.create_index(
        "ix_snapshot_field_snapshot", "payroll_import_review_snapshot_fields",
        ["snapshot_id", "source_import_field_id"],
    )

    op.execute("""
        CREATE FUNCTION reject_payroll_review_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'review snapshots are immutable'
                USING ERRCODE = '55000';
        END;
        $$
    """)
    for table_name in (
        "payroll_import_review_snapshots",
        "payroll_import_review_snapshot_fields",
    ):
        op.execute(f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_payroll_review_snapshot_mutation()
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_payroll_import_review_snapshot_fields_immutable ON payroll_import_review_snapshot_fields")
    op.execute("DROP TRIGGER trg_payroll_import_review_snapshots_immutable ON payroll_import_review_snapshots")
    op.execute("DROP FUNCTION reject_payroll_review_snapshot_mutation()")
    op.drop_index("ix_snapshot_field_snapshot", table_name="payroll_import_review_snapshot_fields")
    op.drop_table("payroll_import_review_snapshot_fields")
    op.drop_constraint(
        "fk_import_review_current_snapshot_org", "payroll_import_reviews", type_="foreignkey",
    )
    op.drop_index("ix_review_snapshot_org_import", table_name="payroll_import_review_snapshots")
    op.drop_table("payroll_import_review_snapshots")
    op.drop_index("ix_field_correction_review_source", table_name="payroll_import_field_corrections")
    op.drop_index("ix_field_correction_org_import", table_name="payroll_import_field_corrections")
    op.drop_table("payroll_import_field_corrections")
    op.drop_index("ix_import_review_org_import", table_name="payroll_import_reviews")
    op.drop_table("payroll_import_reviews")
    provenance.drop(op.get_bind(), checkfirst=True)
    field_status.drop(op.get_bind(), checkfirst=True)
    correction_action.drop(op.get_bind(), checkfirst=True)
    review_status.drop(op.get_bind(), checkfirst=True)
