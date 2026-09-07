"""add immutable payroll import approval decisions and warning acknowledgements

Revision ID: a1e5c7d9f246
Revises: f0d4a6b8c124
Create Date: 2026-09-06 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1e5c7d9f246"
down_revision: Union[str, Sequence[str], None] = "f0d4a6b8c124"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

decision = postgresql.ENUM(
    "APPROVED", "REJECTED", name="payrollapprovaldecision", create_type=False,
)


def upgrade() -> None:
    decision.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payroll_import_validation_acknowledgements",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("review_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("validation_run_id", sa.UUID(), nullable=False),
        sa.Column("validation_result_id", sa.UUID(), nullable=False),
        sa.Column("acknowledged_by_user_id", sa.UUID(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_validation_ack_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id", "review_snapshot_id", "organization_id"],
            ["payroll_import_validation_runs.id", "payroll_import_validation_runs.review_snapshot_id", "payroll_import_validation_runs.organization_id"],
            name="fk_validation_ack_run_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["validation_result_id"], ["payroll_import_validation_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["acknowledged_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("validation_result_id", name="uq_validation_ack_warning_result"),
    )
    op.create_index("ix_validation_ack_org_import", "payroll_import_validation_acknowledgements", ["organization_id", "payroll_import_id"])
    op.create_index("ix_validation_ack_run", "payroll_import_validation_acknowledgements", ["validation_run_id", "validation_result_id"])

    op.create_table(
        "payroll_import_approvals",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("payroll_import_id", sa.UUID(), nullable=False),
        sa.Column("review_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("validation_run_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_checksum", sa.String(64), nullable=False),
        sa.Column("validation_result_checksum", sa.String(64), nullable=False),
        sa.Column("validation_ruleset_version", sa.Integer(), nullable=False),
        sa.Column("decision", decision, nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("acknowledged_warning_result_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approval_checksum", sa.String(64), nullable=False),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("length(snapshot_checksum) = 64", name="ck_import_approval_snapshot_checksum"),
        sa.CheckConstraint("length(validation_result_checksum) = 64", name="ck_import_approval_validation_checksum"),
        sa.CheckConstraint("validation_ruleset_version >= 1", name="ck_import_approval_ruleset_version"),
        sa.CheckConstraint("length(approval_checksum) = 64", name="ck_import_approval_checksum"),
        sa.CheckConstraint("jsonb_typeof(acknowledged_warning_result_ids) = 'array'", name="ck_import_approval_warning_ids_array"),
        sa.CheckConstraint(
            "decision <> 'REJECTED' OR (decision_reason IS NOT NULL AND length(btrim(decision_reason)) > 0)",
            name="ck_import_approval_rejection_reason",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_import_id", "organization_id"],
            ["payroll_imports.id", "payroll_imports.organization_id"],
            name="fk_import_approval_import_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_snapshot_id", "organization_id"],
            ["payroll_import_review_snapshots.id", "payroll_import_review_snapshots.organization_id"],
            name="fk_import_approval_snapshot_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validation_run_id", "review_snapshot_id", "organization_id"],
            ["payroll_import_validation_runs.id", "payroll_import_validation_runs.review_snapshot_id", "payroll_import_validation_runs.organization_id"],
            name="fk_import_approval_validation_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("validation_run_id", name="uq_import_approval_validation_run"),
    )
    op.create_index("ix_import_approval_org_import", "payroll_import_approvals", ["organization_id", "payroll_import_id"])
    op.create_index("ix_import_approval_snapshot", "payroll_import_approvals", ["review_snapshot_id", "validation_run_id"])

    op.execute("""
        CREATE FUNCTION enforce_validation_acknowledgement() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'payroll validation acknowledgements are immutable';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM payroll_import_validation_results result
                JOIN payroll_import_validation_runs run ON run.id = result.validation_run_id
                WHERE result.id = NEW.validation_result_id
                  AND result.validation_run_id = NEW.validation_run_id
                  AND result.review_snapshot_id = NEW.review_snapshot_id
                  AND result.organization_id = NEW.organization_id
                  AND result.severity = 'WARNING'
                  AND run.payroll_import_id = NEW.payroll_import_id
                  AND run.organization_id = NEW.organization_id
            ) THEN
                RAISE EXCEPTION 'acknowledgement target must be a warning in the exact validation run';
            END IF;
            IF EXISTS (
                SELECT 1 FROM payroll_import_approvals
                WHERE validation_run_id = NEW.validation_run_id
            ) THEN
                RAISE EXCEPTION 'a terminal approval decision already exists';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_validation_acknowledgement_integrity
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_import_validation_acknowledgements
        FOR EACH ROW EXECUTE FUNCTION enforce_validation_acknowledgement()
    """)

    op.execute("""
        CREATE FUNCTION enforce_payroll_import_approval() RETURNS trigger AS $$
        DECLARE expected_warning_ids jsonb;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'payroll import approval decisions are immutable';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM payroll_import_validation_runs run
                JOIN payroll_import_review_snapshots snapshot
                  ON snapshot.id = run.review_snapshot_id
                 AND snapshot.organization_id = run.organization_id
                WHERE run.id = NEW.validation_run_id
                  AND run.organization_id = NEW.organization_id
                  AND run.payroll_import_id = NEW.payroll_import_id
                  AND run.review_snapshot_id = NEW.review_snapshot_id
                  AND run.status = 'COMPLETED'
                  AND run.snapshot_checksum = NEW.snapshot_checksum
                  AND snapshot.snapshot_checksum = NEW.snapshot_checksum
                  AND run.result_checksum = NEW.validation_result_checksum
                  AND run.ruleset_version = NEW.validation_ruleset_version
            ) THEN
                RAISE EXCEPTION 'approval context does not match a completed validation run';
            END IF;

            SELECT COALESCE(jsonb_agg(ack.validation_result_id::text ORDER BY ack.validation_result_id::text), '[]'::jsonb)
              INTO expected_warning_ids
              FROM payroll_import_validation_acknowledgements ack
             WHERE ack.validation_run_id = NEW.validation_run_id;
            IF NEW.acknowledged_warning_result_ids <> expected_warning_ids THEN
                RAISE EXCEPTION 'approval warning evidence does not match acknowledgements';
            END IF;

            IF NEW.decision = 'APPROVED' THEN
                IF EXISTS (
                    SELECT 1 FROM payroll_import_validation_results
                    WHERE validation_run_id = NEW.validation_run_id
                      AND severity IN ('ERROR', 'BLOCKING')
                ) THEN
                    RAISE EXCEPTION 'validation errors or blocking results prevent approval';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM payroll_import_validation_results result
                    WHERE result.validation_run_id = NEW.validation_run_id
                      AND result.severity = 'WARNING'
                      AND NOT EXISTS (
                          SELECT 1 FROM payroll_import_validation_acknowledgements ack
                          WHERE ack.validation_result_id = result.id
                      )
                ) THEN
                    RAISE EXCEPTION 'all validation warnings must be acknowledged';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_payroll_import_approval_integrity
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_import_approvals
        FOR EACH ROW EXECUTE FUNCTION enforce_payroll_import_approval()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_payroll_import_approval_integrity ON payroll_import_approvals")
    op.execute("DROP FUNCTION IF EXISTS enforce_payroll_import_approval()")
    op.execute("DROP TRIGGER IF EXISTS trg_validation_acknowledgement_integrity ON payroll_import_validation_acknowledgements")
    op.execute("DROP FUNCTION IF EXISTS enforce_validation_acknowledgement()")
    op.drop_index("ix_import_approval_snapshot", table_name="payroll_import_approvals")
    op.drop_index("ix_import_approval_org_import", table_name="payroll_import_approvals")
    op.drop_table("payroll_import_approvals")
    op.drop_index("ix_validation_ack_run", table_name="payroll_import_validation_acknowledgements")
    op.drop_index("ix_validation_ack_org_import", table_name="payroll_import_validation_acknowledgements")
    op.drop_table("payroll_import_validation_acknowledgements")
    decision.drop(op.get_bind(), checkfirst=True)
