"""add authoritative payroll materialization evidence

Revision ID: b7c2d9e4f610
Revises: a1e5c7d9f246
Create Date: 2026-09-07 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c2d9e4f610"
down_revision: Union[str, Sequence[str], None] = "a1e5c7d9f246"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE payrollsourcetype ADD VALUE IF NOT EXISTS 'DOCUMENT'"
    )
    op.create_unique_constraint(
        "uq_payroll_id_org", "payrolls", ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_payroll_version_materialization_scope", "payroll_versions",
        ["id", "payroll_id", "revision_no"],
    )
    op.create_unique_constraint(
        "uq_import_approval_materialization_scope", "payroll_import_approvals",
        [
            "id", "payroll_import_id", "review_snapshot_id",
            "validation_run_id", "organization_id",
        ],
    )
    op.create_foreign_key(
        "fk_payroll_versions_source_import_id",
        "payroll_versions", "payroll_imports",
        ["source_import_id"], ["id"], ondelete="RESTRICT",
    )

    op.create_table(
        "payroll_import_materializations",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("review_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("validation_run_id", sa.UUID(), nullable=False),
        sa.Column("payroll_id", sa.UUID(), nullable=False),
        sa.Column("payroll_version_id", sa.UUID(), nullable=False),
        sa.Column("payroll_revision_no", sa.Integer(), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("validation_result_checksum", sa.String(64), nullable=False),
        sa.Column("approval_checksum", sa.String(64), nullable=False),
        sa.Column("materialization_checksum", sa.String(64), nullable=False),
        sa.Column("materialization_version", sa.Integer(), nullable=False),
        sa.Column("materialized_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "materialized_at", sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "materialization_version >= 1",
            name="ck_materialization_version_positive",
        ),
        sa.CheckConstraint(
            "payroll_revision_no >= 1",
            name="ck_materialization_revision_positive",
        ),
        sa.CheckConstraint(
            "length(snapshot_checksum) = 64",
            name="ck_materialization_snapshot_checksum",
        ),
        sa.CheckConstraint(
            "length(validation_result_checksum) = 64",
            name="ck_materialization_validation_checksum",
        ),
        sa.CheckConstraint(
            "length(approval_checksum) = 64",
            name="ck_materialization_approval_checksum",
        ),
        sa.CheckConstraint(
            "length(materialization_checksum) = 64",
            name="ck_materialization_checksum",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_materialization_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "approval_id", "payroll_import_id", "review_snapshot_id",
                "validation_run_id", "organization_id",
            ],
            [
                "payroll_import_approvals.id",
                "payroll_import_approvals.payroll_import_id",
                "payroll_import_approvals.review_snapshot_id",
                "payroll_import_approvals.validation_run_id",
                "payroll_import_approvals.organization_id",
            ],
            name="fk_materialization_approval_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_id", "organization_id"],
            ["payrolls.id", "payrolls.organization_id"],
            name="fk_materialization_payroll_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_version_id", "payroll_id", "payroll_revision_no"],
            ["payroll_versions.id", "payroll_versions.payroll_id",
             "payroll_versions.revision_no"],
            name="fk_materialization_version_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["materialized_by_user_id"], ["users.id"],
            name="fk_materialization_actor", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_id", name="uq_materialization_approval"),
        sa.UniqueConstraint(
            "payroll_version_id", name="uq_materialization_payroll_version",
        ),
    )
    op.create_index(
        "ix_materialization_org_import", "payroll_import_materializations",
        ["organization_id", "payroll_import_id", "materialized_at"],
    )

    op.execute("""
        CREATE FUNCTION enforce_payroll_import_materialization() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'payroll import materialization evidence is immutable';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM payroll_import_approvals approval
                 WHERE approval.id = NEW.approval_id
                   AND approval.organization_id = NEW.organization_id
                   AND approval.payroll_import_id = NEW.payroll_import_id
                   AND approval.review_snapshot_id = NEW.review_snapshot_id
                   AND approval.validation_run_id = NEW.validation_run_id
                   AND approval.decision = 'APPROVED'
                   AND approval.snapshot_checksum = NEW.snapshot_checksum
                   AND approval.validation_result_checksum = NEW.validation_result_checksum
                   AND approval.approval_checksum = NEW.approval_checksum
            ) THEN
                RAISE EXCEPTION 'materialization requires exact approved evidence';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM payroll_versions version
                  JOIN payrolls payroll ON payroll.id = version.payroll_id
                 WHERE version.id = NEW.payroll_version_id
                   AND version.payroll_id = NEW.payroll_id
                   AND version.revision_no = NEW.payroll_revision_no
                   AND version.source_import_id = NEW.payroll_import_id
                   AND version.source_checksum = NEW.snapshot_checksum
                   AND version.status = 'ACTIVE'
                   AND version.is_current
                   AND payroll.organization_id = NEW.organization_id
            ) THEN
                RAISE EXCEPTION 'materialization payroll revision does not match evidence';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_payroll_import_materialization_integrity
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_import_materializations
        FOR EACH ROW EXECUTE FUNCTION enforce_payroll_import_materialization()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payroll_import_materialization_integrity "
        "ON payroll_import_materializations"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_payroll_import_materialization()")
    op.drop_index(
        "ix_materialization_org_import",
        table_name="payroll_import_materializations",
    )
    op.drop_table("payroll_import_materializations")
    op.drop_constraint(
        "fk_payroll_versions_source_import_id", "payroll_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_import_approval_materialization_scope", "payroll_import_approvals",
        type_="unique",
    )
    op.drop_constraint(
        "uq_payroll_version_materialization_scope", "payroll_versions",
        type_="unique",
    )
    op.drop_constraint("uq_payroll_id_org", "payrolls", type_="unique")
    # PostgreSQL enum labels cannot be removed safely while authoritative
    # PayrollVersion rows may still reference them. Retain DOCUMENT on downgrade.
