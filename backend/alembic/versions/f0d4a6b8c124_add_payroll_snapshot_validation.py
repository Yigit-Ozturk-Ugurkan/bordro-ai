"""add immutable payroll snapshot validation runs and results

Revision ID: f0d4a6b8c124
Revises: e9c3f5a7b013
Create Date: 2026-09-06 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f0d4a6b8c124"
down_revision: Union[str, Sequence[str], None] = "e9c3f5a7b013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

run_status = postgresql.ENUM(
    "RUNNING", "COMPLETED", "FAILED",
    name="payrollvalidationrunstatus", create_type=False,
)
severity = postgresql.ENUM(
    "INFO", "WARNING", "ERROR", "BLOCKING",
    name="payrollvalidationseverity", create_type=False,
)
category = postgresql.ENUM(
    "STRUCTURAL", "ARITHMETIC", "IDENTITY", "PERIOD",
    "TAX_RECONCILIATION", "DUPLICATE_CONTEXT",
    name="payrollvalidationcategory", create_type=False,
)

KEY_CHECK = (
    "('employee_identifier','period_year','period_month','gross_earnings','sgk_base',"
    "'income_tax_base','stamp_tax_base','employee_sgk','employee_unemployment',"
    "'income_tax','stamp_tax','total_earnings','total_deductions','net_pay','paid_days',"
    "'missing_days','cumulative_income_tax_base')"
)


def upgrade() -> None:
    bind = op.get_bind()
    run_status.create(bind, checkfirst=True)
    severity.create(bind, checkfirst=True)
    category.create(bind, checkfirst=True)

    op.create_table(
        "payroll_import_validation_runs",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("review_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("validation_version", sa.Integer(), nullable=False),
        sa.Column("ruleset_version", sa.Integer(), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("result_checksum", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("info_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("blocking_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("validation_version >= 1", name="ck_validation_run_version_positive"),
        sa.CheckConstraint("ruleset_version >= 1", name="ck_validation_ruleset_version_positive"),
        sa.CheckConstraint(
            "info_count >= 0 AND warning_count >= 0 AND error_count >= 0 AND blocking_count >= 0",
            name="ck_validation_run_counts_non_negative",
        ),
        sa.CheckConstraint("length(snapshot_checksum) = 64", name="ck_validation_run_snapshot_checksum_length"),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND result_checksum IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL AND result_checksum IS NOT NULL "
            "AND length(result_checksum) = 64) OR "
            "(status = 'FAILED' AND completed_at IS NOT NULL)",
            name="ck_validation_run_status_shape",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["review_snapshot_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.organization_id"],
            name="fk_validation_run_snapshot_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_validation_run_import_org", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_snapshot_id", "ruleset_version", name="uq_validation_run_snapshot_ruleset"),
        sa.UniqueConstraint("id", "review_snapshot_id", "organization_id", name="uq_validation_run_identity_scope"),
    )
    op.create_index("ix_validation_run_org_import", "payroll_import_validation_runs", ["organization_id", "payroll_import_id"])
    op.create_index("ix_validation_run_snapshot", "payroll_import_validation_runs", ["review_snapshot_id", "ruleset_version"])

    op.create_table(
        "payroll_import_validation_results",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("validation_run_id", sa.UUID(), nullable=False),
        sa.Column("review_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("result_order", sa.Integer(), nullable=False),
        sa.Column("validation_code", sa.String(100), nullable=False),
        sa.Column("validation_version", sa.Integer(), nullable=False),
        sa.Column("category", category, nullable=False),
        sa.Column("severity", severity, nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("canonical_key", sa.String(100), nullable=True),
        sa.Column("related_snapshot_field_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blocks_future_approval", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("result_order >= 1", name="ck_validation_result_order_positive"),
        sa.CheckConstraint("validation_version >= 1", name="ck_validation_result_version_positive"),
        sa.CheckConstraint(f"canonical_key IS NULL OR canonical_key IN {KEY_CHECK}", name="ck_validation_result_canonical_key"),
        sa.CheckConstraint(
            "(severity IN ('ERROR','BLOCKING') AND blocks_future_approval) OR "
            "(severity IN ('INFO','WARNING') AND NOT blocks_future_approval)",
            name="ck_validation_result_blocking_semantics",
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id", "review_snapshot_id", "organization_id"],
            ["payroll_import_validation_runs.id", "payroll_import_validation_runs.review_snapshot_id", "payroll_import_validation_runs.organization_id"],
            name="fk_validation_result_run_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("validation_run_id", "result_order", name="uq_validation_result_run_order"),
    )
    op.create_index("ix_validation_result_org_run", "payroll_import_validation_results", ["organization_id", "validation_run_id"])
    op.create_index("ix_validation_result_snapshot_code", "payroll_import_validation_results", ["review_snapshot_id", "validation_code"])

    op.execute("""
        CREATE FUNCTION reject_payroll_validation_mutation() RETURNS trigger AS $$
        DECLARE parent_status payrollvalidationrunstatus;
        BEGIN
            IF TG_TABLE_NAME = 'payroll_import_validation_results' THEN
                IF TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION 'payroll validation results are immutable';
                END IF;
                SELECT status INTO parent_status
                FROM payroll_import_validation_runs WHERE id = NEW.validation_run_id;
                IF parent_status <> 'RUNNING' THEN
                    RAISE EXCEPTION 'results cannot be added to a completed validation run';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' OR OLD.status = 'COMPLETED' THEN
                RAISE EXCEPTION 'completed payroll validation data is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_validation_run_immutable
        BEFORE UPDATE OR DELETE ON payroll_import_validation_runs
        FOR EACH ROW EXECUTE FUNCTION reject_payroll_validation_mutation()
    """)
    op.execute("""
        CREATE TRIGGER trg_validation_result_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_import_validation_results
        FOR EACH ROW EXECUTE FUNCTION reject_payroll_validation_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_validation_result_immutable ON payroll_import_validation_results")
    op.execute("DROP TRIGGER IF EXISTS trg_validation_run_immutable ON payroll_import_validation_runs")
    op.execute("DROP FUNCTION IF EXISTS reject_payroll_validation_mutation()")
    op.drop_index("ix_validation_result_snapshot_code", table_name="payroll_import_validation_results")
    op.drop_index("ix_validation_result_org_run", table_name="payroll_import_validation_results")
    op.drop_table("payroll_import_validation_results")
    op.drop_index("ix_validation_run_snapshot", table_name="payroll_import_validation_runs")
    op.drop_index("ix_validation_run_org_import", table_name="payroll_import_validation_runs")
    op.drop_table("payroll_import_validation_runs")
    category.drop(op.get_bind(), checkfirst=True)
    severity.drop(op.get_bind(), checkfirst=True)
    run_status.drop(op.get_bind(), checkfirst=True)
