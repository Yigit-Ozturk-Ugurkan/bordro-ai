"""add deterministic payroll detail mapping and reviewed materialization

Revision ID: a2b4c6d8e010
Revises: f1a7c3e9b205
Create Date: 2026-09-08 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a2b4c6d8e010"
down_revision: Union[str, Sequence[str], None] = "f1a7c3e9b205"
branch_labels = None
depends_on = None

detail_type = postgresql.ENUM(
    "EARNING", "DEDUCTION", "ABSENCE", "UNMAPPED",
    name="payrolldetailtype", create_type=False,
)
mapping_status = postgresql.ENUM(
    "MAPPED", "UNMAPPED", "AMBIGUOUS", "PARSE_FAILED",
    name="payrolldetailmappingstatus", create_type=False,
)
review_status = postgresql.ENUM(
    "IN_PROGRESS", "READY_FOR_SNAPSHOT", "SNAPSHOTTED",
    name="payrolldetailreviewstatus", create_type=False,
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    detail_type.create(op.get_bind(), checkfirst=True)
    mapping_status.create(op.get_bind(), checkfirst=True)
    review_status.create(op.get_bind(), checkfirst=True)
    op.create_unique_constraint(
        "uq_payroll_import_table_row_table_org", "payroll_import_table_rows",
        ["id", "table_id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_import_approval_detail_scope", "payroll_import_approvals",
        ["id", "organization_id", "payroll_import_id"],
    )
    op.create_unique_constraint(
        "uq_materialization_detail_scope", "payroll_import_materializations",
        ["id", "organization_id", "payroll_import_id", "payroll_id",
         "payroll_version_id"],
    )

    op.create_table(
        "payroll_detail_mappings",
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("scope", postgresql.ENUM(
            "SYSTEM", "ORGANIZATION", "TEMPLATE", name="payrollfieldmappingscope",
            create_type=False,
        ), nullable=False),
        sa.Column("template_external_id", sa.String(100), nullable=True),
        sa.Column("source_label_normalized", sa.String(500), nullable=False),
        sa.Column("label_column_id", sa.String(200), nullable=False),
        sa.Column("amount_column_id", sa.String(200), nullable=True),
        sa.Column("quantity_column_id", sa.String(200), nullable=True),
        sa.Column("rate_column_id", sa.String(200), nullable=True),
        sa.Column("detail_type", detail_type, nullable=False),
        sa.Column("canonical_code", sa.String(100), nullable=False),
        sa.Column("canonical_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("target_values", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("priority >= 0", name="ck_detail_mapping_priority"),
        sa.CheckConstraint("version >= 1", name="ck_detail_mapping_version"),
        sa.CheckConstraint(
            "(scope = 'SYSTEM' AND organization_id IS NULL AND template_external_id IS NULL) OR "
            "(scope = 'ORGANIZATION' AND organization_id IS NOT NULL AND template_external_id IS NULL) OR "
            "(scope = 'TEMPLATE' AND organization_id IS NOT NULL AND template_external_id IS NOT NULL)",
            name="ck_detail_mapping_scope_shape",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_detail_mapping_match", "payroll_detail_mappings",
        ["organization_id", "source_label_normalized", "is_active"],
    )

    op.create_table(
        "payroll_import_mapped_details",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("source_table_id", sa.UUID(), nullable=False),
        sa.Column("source_row_id", sa.UUID(), nullable=False),
        sa.Column("source_table_index", sa.Integer(), nullable=False),
        sa.Column("source_row_index", sa.Integer(), nullable=False),
        sa.Column("mapping_id", sa.UUID(), nullable=True),
        sa.Column("mapping_version", sa.Integer(), nullable=True),
        sa.Column("source_label", sa.Text(), nullable=True),
        sa.Column("source_values", postgresql.JSONB(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("detail_type", detail_type, nullable=False),
        sa.Column("canonical_code", sa.String(100), nullable=True),
        sa.Column("canonical_name", sa.String(200), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 2), nullable=True),
        sa.Column("rate", sa.Numeric(9, 6), nullable=True),
        sa.Column("target_values", postgresql.JSONB(), nullable=False),
        sa.Column("mapping_status", mapping_status, nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(source_checksum) = 64",
                           name="ck_mapped_detail_source_checksum"),
        sa.CheckConstraint("source_table_index >= 0",
                           name="ck_mapped_detail_table_index"),
        sa.CheckConstraint("source_row_index >= 0",
                           name="ck_mapped_detail_row_index"),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_mapped_detail_import_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_table_id", "organization_id"],
            ["payroll_import_tables.id", "payroll_import_tables.organization_id"],
            name="fk_mapped_detail_table_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id", "source_table_id", "organization_id"],
            ["payroll_import_table_rows.id", "payroll_import_table_rows.table_id",
             "payroll_import_table_rows.organization_id"],
            name="fk_mapped_detail_row_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["mapping_id"], ["payroll_detail_mappings.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_row_id", name="uq_mapped_detail_source_row"),
        sa.UniqueConstraint("id", "organization_id",
                            name="uq_mapped_detail_id_org"),
    )
    op.create_index(
        "ix_mapped_detail_org_import", "payroll_import_mapped_details",
        ["organization_id", "payroll_import_id"],
    )

    op.create_table(
        "payroll_import_detail_reviews",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("status", review_status, nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("mapping_checksum", sa.String(64), nullable=False),
        sa.Column("current_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("row_version >= 1",
                           name="ck_detail_review_row_version"),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_detail_review_import_org", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_import_id", name="uq_detail_review_import"),
    )

    op.create_table(
        "payroll_import_detail_corrections",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("mapped_detail_id", sa.UUID(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("detail_type", detail_type, nullable=False),
        sa.Column("canonical_code", sa.String(100), nullable=True),
        sa.Column("canonical_name", sa.String(200), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 2), nullable=True),
        sa.Column("rate", sa.Numeric(9, 6), nullable=True),
        sa.Column("target_values", postgresql.JSONB(), nullable=False),
        sa.Column("ignored", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("revision >= 1",
                           name="ck_detail_correction_revision"),
        sa.CheckConstraint("length(source_checksum) = 64",
                           name="ck_detail_correction_source_checksum"),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_detail_correction_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapped_detail_id", "organization_id"],
            ["payroll_import_mapped_details.id",
             "payroll_import_mapped_details.organization_id"],
            name="fk_detail_correction_mapped_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mapped_detail_id", "revision",
                            name="uq_detail_correction_revision"),
        sa.UniqueConstraint("id", "organization_id", "payroll_import_id",
                            name="uq_detail_correction_scope"),
    )
    op.create_index(
        "ix_detail_correction_import", "payroll_import_detail_corrections",
        ["organization_id", "payroll_import_id"],
    )

    op.create_table(
        "payroll_import_detail_snapshots",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("mapping_checksum", sa.String(64), nullable=False),
        sa.Column("corrections_checksum", sa.String(64), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("finalized_by_user_id", sa.UUID(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_detail_snapshot_revision"),
        sa.CheckConstraint("row_count >= 0", name="ck_detail_snapshot_row_count"),
        sa.CheckConstraint("length(snapshot_checksum) = 64",
                           name="ck_detail_snapshot_checksum"),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_detail_snapshot_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["finalized_by_user_id"], ["users.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_import_id", "revision",
                            name="uq_detail_snapshot_revision"),
        sa.UniqueConstraint("id", "organization_id", "payroll_import_id",
                            name="uq_detail_snapshot_scope"),
    )
    op.create_index(
        "ix_detail_snapshot_import", "payroll_import_detail_snapshots",
        ["organization_id", "payroll_import_id", "revision"],
    )
    op.create_foreign_key(
        "fk_detail_review_current_snapshot_scope", "payroll_import_detail_reviews",
        "payroll_import_detail_snapshots",
        ["current_snapshot_id", "organization_id", "payroll_import_id"],
        ["id", "organization_id", "payroll_import_id"], ondelete="RESTRICT",
    )
    op.create_table(
        "payroll_import_detail_snapshot_rows",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("source_table_id", sa.UUID(), nullable=False),
        sa.Column("source_row_id", sa.UUID(), nullable=False),
        sa.Column("correction_id", sa.UUID(), nullable=False),
        sa.Column("row_order", sa.Integer(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("detail_type", detail_type, nullable=False),
        sa.Column("canonical_code", sa.String(100), nullable=True),
        sa.Column("canonical_name", sa.String(200), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 2), nullable=True),
        sa.Column("rate", sa.Numeric(9, 6), nullable=True),
        sa.Column("target_values", postgresql.JSONB(), nullable=False),
        sa.Column("ignored", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("row_order >= 0",
                           name="ck_detail_snapshot_row_order"),
        sa.CheckConstraint("length(source_checksum) = 64",
                           name="ck_detail_snapshot_row_source_checksum"),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "organization_id", "payroll_import_id"],
            ["payroll_import_detail_snapshots.id",
             "payroll_import_detail_snapshots.organization_id",
             "payroll_import_detail_snapshots.payroll_import_id"],
            name="fk_detail_snapshot_row_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id", "source_table_id", "organization_id"],
            ["payroll_import_table_rows.id", "payroll_import_table_rows.table_id",
             "payroll_import_table_rows.organization_id"],
            name="fk_detail_snapshot_row_source_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_table_id", "organization_id"],
            ["payroll_import_tables.id", "payroll_import_tables.organization_id"],
            name="fk_detail_snapshot_row_table_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["correction_id", "organization_id", "payroll_import_id"],
            ["payroll_import_detail_corrections.id",
             "payroll_import_detail_corrections.organization_id",
             "payroll_import_detail_corrections.payroll_import_id"],
            name="fk_detail_snapshot_row_correction_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"],
            name="fk_detail_snapshot_row_reviewer", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "source_row_id",
                            name="uq_detail_snapshot_source_row"),
        sa.UniqueConstraint("id", "organization_id",
                            name="uq_detail_snapshot_row_id_org"),
    )
    op.add_column("payroll_import_approvals",
                  sa.Column("detail_snapshot_id", sa.UUID(), nullable=True))
    op.add_column("payroll_import_approvals",
                  sa.Column("detail_snapshot_checksum", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_import_approval_detail_snapshot_scope", "payroll_import_approvals",
        "payroll_import_detail_snapshots",
        ["detail_snapshot_id", "organization_id", "payroll_import_id"],
        ["id", "organization_id", "payroll_import_id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_import_approval_detail_snapshot_complete", "payroll_import_approvals",
        "(detail_snapshot_id IS NULL) = (detail_snapshot_checksum IS NULL)",
    )
    op.create_check_constraint(
        "ck_import_approval_detail_snapshot_checksum", "payroll_import_approvals",
        "detail_snapshot_checksum IS NULL OR length(detail_snapshot_checksum) = 64",
    )

    op.create_table(
        "payroll_import_detail_materializations",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("detail_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("payroll_materialization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_id", sa.UUID(), nullable=False),
        sa.Column("payroll_version_id", sa.UUID(), nullable=False),
        sa.Column("materialization_checksum", sa.String(64), nullable=False),
        sa.Column("earning_count", sa.Integer(), nullable=False),
        sa.Column("deduction_count", sa.Integer(), nullable=False),
        sa.Column("absence_count", sa.Integer(), nullable=False),
        sa.Column("materialized_by_user_id", sa.UUID(), nullable=False),
        sa.Column("materialized_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("length(materialization_checksum) = 64",
                           name="ck_detail_materialization_checksum"),
        sa.CheckConstraint(
            "earning_count >= 0 AND deduction_count >= 0 AND absence_count >= 0",
            name="ck_detail_materialization_counts",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_detail_materialization_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["detail_snapshot_id", "organization_id", "payroll_import_id"],
            ["payroll_import_detail_snapshots.id",
             "payroll_import_detail_snapshots.organization_id",
             "payroll_import_detail_snapshots.payroll_import_id"],
            name="fk_detail_materialization_snapshot_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id", "organization_id", "payroll_import_id"],
            ["payroll_import_approvals.id", "payroll_import_approvals.organization_id",
             "payroll_import_approvals.payroll_import_id"],
            name="fk_detail_materialization_approval_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_materialization_id", "organization_id", "payroll_import_id",
             "payroll_id", "payroll_version_id"],
            ["payroll_import_materializations.id",
             "payroll_import_materializations.organization_id",
             "payroll_import_materializations.payroll_import_id",
             "payroll_import_materializations.payroll_id",
             "payroll_import_materializations.payroll_version_id"],
            name="fk_detail_materialization_payroll_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["materialized_by_user_id"], ["users.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_materialization_id",
                            name="uq_detail_materialization_payroll"),
        sa.UniqueConstraint("id", "organization_id", "payroll_version_id",
                            name="uq_detail_materialization_target_scope"),
    )

    for table, kind in (
        ("payroll_earnings", "earning"),
        ("payroll_deductions", "deduction"),
        ("payroll_absences", "absence"),
    ):
        for column in (
            "organization_id", "source_import_id", "source_table_id",
            "source_row_id", "detail_snapshot_row_id", "detail_materialization_id",
        ):
            op.add_column(table, sa.Column(column, sa.UUID(), nullable=True))
        op.create_foreign_key(
            f"fk_payroll_{kind}_source_import_org", table, "payroll_imports",
            ["source_import_id", "organization_id"], ["id", "organization_id"],
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            f"fk_payroll_{kind}_source_table_org", table, "payroll_import_tables",
            ["source_table_id", "organization_id"], ["id", "organization_id"],
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            f"fk_payroll_{kind}_source_row_org", table,
            "payroll_import_table_rows",
            ["source_row_id", "source_table_id", "organization_id"],
            ["id", "table_id", "organization_id"],
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            f"fk_payroll_{kind}_snapshot_row_org", table,
            "payroll_import_detail_snapshot_rows",
            ["detail_snapshot_row_id", "organization_id"],
            ["id", "organization_id"], ondelete="RESTRICT",
        )
        op.create_foreign_key(
            f"fk_payroll_{kind}_detail_materialization_scope", table,
            "payroll_import_detail_materializations",
            ["detail_materialization_id", "organization_id",
             "payroll_version_id"],
            ["id", "organization_id", "payroll_version_id"],
            ondelete="RESTRICT",
        )
        op.create_unique_constraint(
            f"uq_payroll_{kind}_snapshot_row", table,
            ["detail_snapshot_row_id"],
        )
        op.create_check_constraint(
            f"ck_payroll_{kind}_provenance_complete", table,
            "(detail_materialization_id IS NULL AND detail_snapshot_row_id IS NULL "
            "AND source_import_id IS NULL AND source_table_id IS NULL "
            "AND source_row_id IS NULL AND organization_id IS NULL) OR "
            "(detail_materialization_id IS NOT NULL AND detail_snapshot_row_id IS NOT NULL "
            "AND source_import_id IS NOT NULL AND source_table_id IS NOT NULL "
            "AND source_row_id IS NOT NULL AND organization_id IS NOT NULL)",
        )

    op.execute("""
        CREATE FUNCTION reject_payroll_detail_review_evidence_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'payroll detail review evidence is immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in (
        "payroll_import_detail_corrections",
        "payroll_import_detail_snapshots",
        "payroll_import_detail_snapshot_rows",
        "payroll_import_detail_materializations",
    ):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION
                reject_payroll_detail_review_evidence_mutation()
        """)
    op.execute("""
        CREATE FUNCTION reject_materialized_payroll_detail_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.detail_materialization_id IS NOT NULL THEN
                RAISE EXCEPTION 'materialized payroll detail is immutable';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("payroll_earnings", "payroll_deductions", "payroll_absences"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_materialized_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_materialized_payroll_detail_mutation()
        """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM payroll_detail_mappings)
               OR EXISTS (SELECT 1 FROM payroll_import_mapped_details)
               OR EXISTS (SELECT 1 FROM payroll_import_detail_reviews)
               OR EXISTS (SELECT 1 FROM payroll_import_detail_corrections)
               OR EXISTS (SELECT 1 FROM payroll_import_detail_snapshots)
               OR EXISTS (SELECT 1 FROM payroll_import_detail_materializations)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade while payroll detail mapping evidence exists';
            END IF;
        END $$
    """)
    for table in ("payroll_earnings", "payroll_deductions", "payroll_absences"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_materialized_immutable ON {table}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_materialized_payroll_detail_mutation()")
    for table, kind in (
        ("payroll_earnings", "earning"),
        ("payroll_deductions", "deduction"),
        ("payroll_absences", "absence"),
    ):
        op.drop_constraint(f"ck_payroll_{kind}_provenance_complete", table,
                           type_="check")
        op.drop_constraint(f"uq_payroll_{kind}_snapshot_row", table,
                           type_="unique")
        for constraint in (
            f"fk_payroll_{kind}_detail_materialization_scope",
            f"fk_payroll_{kind}_snapshot_row_org",
            f"fk_payroll_{kind}_source_row_org",
            f"fk_payroll_{kind}_source_table_org",
            f"fk_payroll_{kind}_source_import_org",
        ):
            op.drop_constraint(constraint, table, type_="foreignkey")
        for column in (
            "detail_materialization_id", "detail_snapshot_row_id",
            "source_row_id", "source_table_id", "source_import_id",
            "organization_id",
        ):
            op.drop_column(table, column)
    for table in (
        "payroll_import_detail_materializations",
        "payroll_import_detail_snapshot_rows",
        "payroll_import_detail_snapshots",
        "payroll_import_detail_corrections",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_payroll_detail_review_evidence_mutation()")
    op.drop_table("payroll_import_detail_materializations")
    op.drop_constraint("fk_import_approval_detail_snapshot_scope",
                       "payroll_import_approvals", type_="foreignkey")
    op.drop_constraint("ck_import_approval_detail_snapshot_checksum",
                       "payroll_import_approvals", type_="check")
    op.drop_constraint("ck_import_approval_detail_snapshot_complete",
                       "payroll_import_approvals", type_="check")
    op.drop_column("payroll_import_approvals", "detail_snapshot_checksum")
    op.drop_column("payroll_import_approvals", "detail_snapshot_id")
    op.drop_table("payroll_import_detail_snapshot_rows")
    op.drop_constraint("fk_detail_review_current_snapshot_scope",
                       "payroll_import_detail_reviews", type_="foreignkey")
    op.drop_index("ix_detail_snapshot_import",
                  table_name="payroll_import_detail_snapshots")
    op.drop_table("payroll_import_detail_snapshots")
    op.drop_index("ix_detail_correction_import",
                  table_name="payroll_import_detail_corrections")
    op.drop_table("payroll_import_detail_corrections")
    op.drop_table("payroll_import_detail_reviews")
    op.drop_index("ix_mapped_detail_org_import",
                  table_name="payroll_import_mapped_details")
    op.drop_table("payroll_import_mapped_details")
    op.drop_index("ix_detail_mapping_match", table_name="payroll_detail_mappings")
    op.drop_table("payroll_detail_mappings")
    op.drop_constraint("uq_materialization_detail_scope",
                       "payroll_import_materializations", type_="unique")
    op.drop_constraint("uq_import_approval_detail_scope",
                       "payroll_import_approvals", type_="unique")
    op.drop_constraint("uq_payroll_import_table_row_table_org",
                       "payroll_import_table_rows", type_="unique")
    review_status.drop(op.get_bind(), checkfirst=True)
    mapping_status.drop(op.get_bind(), checkfirst=True)
    detail_type.drop(op.get_bind(), checkfirst=True)
