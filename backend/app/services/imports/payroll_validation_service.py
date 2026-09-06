"""Snapshot-only orchestration for deterministic payroll validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PayrollImportNotFoundError,
    PayrollReviewSnapshotNotFoundError,
    PayrollValidationRulesetUnsupportedError,
    PayrollValidationRunNotFoundError,
)
from app.models.enums import (
    PayrollValidationReadiness,
    PayrollValidationRunStatus,
    PayrollValidationSeverity,
)
from app.models.payroll_validation import (
    PayrollImportValidationResult,
    PayrollImportValidationRun,
)
from app.repositories.payroll_validation_repository import PayrollValidationRepository
from app.schemas.payroll_validation import (
    PayrollValidationResultRead,
    PayrollValidationRunList,
    PayrollValidationRunRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_validation_rules import (
    RULESET_VERSION,
    ValidationContext,
    ValidationFinding,
    execute_rules,
)


class PayrollValidationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def validate_snapshot(
        self, user: AuthenticatedUser, import_id: UUID, snapshot_id: UUID,
        *, ruleset_version: int = RULESET_VERSION,
    ) -> PayrollValidationRunRead:
        if ruleset_version < 1:
            raise PayrollValidationRulesetUnsupportedError()

        def work(sync):
            repository = PayrollValidationRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            snapshot = repository.get_snapshot(user.organization_id, import_id, snapshot_id)
            if snapshot is None:
                raise PayrollReviewSnapshotNotFoundError()
            existing = repository.completed_for_ruleset(
                user.organization_id, snapshot_id, ruleset_version,
            )
            if existing is not None:
                return self._run_read(existing)

            context = ValidationContext(fields=tuple(snapshot.fields))
            identifier = context.scalar("employee_identifier")
            employee_ids = (
                repository.employee_ids(user.organization_id, identifier)
                if isinstance(identifier, str) else ()
            )
            context.matching_employee_ids = employee_ids
            year, month = context.scalar("period_year"), context.scalar("period_month")
            if (len(employee_ids) == 1 and isinstance(year, int) and not isinstance(year, bool)
                    and isinstance(month, int) and not isinstance(month, bool)
                    and 1 <= year <= 9999 and 1 <= month <= 12):
                context.existing_current_payroll_id = repository.current_payroll_id(
                    user.organization_id, employee_ids[0], year, month,
                )

            findings = execute_rules(context)
            counts = Counter(finding.severity for finding in findings)
            now = datetime.now(timezone.utc)
            checksum = self.result_checksum(findings)
            run = PayrollImportValidationRun(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, review_snapshot_id=snapshot_id,
                validation_version=repository.next_validation_version(snapshot_id),
                ruleset_version=ruleset_version,
                status=PayrollValidationRunStatus.RUNNING,
                snapshot_checksum=snapshot.snapshot_checksum,
                result_checksum=None, started_at=now, completed_at=None,
                created_by_user_id=user.id,
                info_count=counts[PayrollValidationSeverity.INFO],
                warning_count=counts[PayrollValidationSeverity.WARNING],
                error_count=counts[PayrollValidationSeverity.ERROR],
                blocking_count=counts[PayrollValidationSeverity.BLOCKING],
                created_at=now,
            )
            results = [self._result_model(run, finding, order, now)
                       for order, finding in enumerate(findings, 1)]
            repository.add(run, results)
            run.result_checksum = checksum
            run.completed_at = now
            run.status = PayrollValidationRunStatus.COMPLETED
            sync.flush()
            return self._run_read(run)

        try:
            response = await self._session.run_sync(work)
            await self._session.commit()
            return response
        except Exception:
            await self._session.rollback()
            raise

    async def list(self, user: AuthenticatedUser, import_id: UUID) -> PayrollValidationRunList:
        def work(sync):
            repository = PayrollValidationRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            rows = repository.list_runs(user.organization_id, import_id)
            return PayrollValidationRunList(
                import_id=import_id, count=len(rows),
                items=[self._run_read(row) for row in rows],
            )
        return await self._session.run_sync(work)

    async def get(self, user: AuthenticatedUser, import_id: UUID,
                  run_id: UUID) -> PayrollValidationRunRead:
        def work(sync):
            repository = PayrollValidationRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            row = repository.get_run(user.organization_id, import_id, run_id)
            if row is None:
                raise PayrollValidationRunNotFoundError()
            return self._run_read(row)
        return await self._session.run_sync(work)

    @staticmethod
    def _result_model(run, finding: ValidationFinding, order: int, now: datetime):
        return PayrollImportValidationResult(
            id=uuid4(), organization_id=run.organization_id,
            validation_run_id=run.id, review_snapshot_id=run.review_snapshot_id,
            result_order=order, validation_code=finding.code,
            validation_version=finding.version, category=finding.category,
            severity=finding.severity, message=finding.message,
            canonical_key=finding.canonical_key,
            related_snapshot_field_ids=[str(value) for value in finding.related_snapshot_field_ids],
            expected_value=finding.expected_value, actual_value=finding.actual_value,
            details=finding.details,
            blocks_future_approval=finding.blocks_future_approval, created_at=now,
        )

    @staticmethod
    def result_checksum(findings: list[ValidationFinding]) -> str:
        payload = [{
            "actual_value": item.actual_value,
            "blocks_future_approval": item.blocks_future_approval,
            "canonical_key": item.canonical_key,
            "category": item.category.value,
            "details": item.details,
            "expected_value": item.expected_value,
            "message": item.message,
            "related_snapshot_field_ids": sorted(str(value) for value in item.related_snapshot_field_ids),
            "severity": item.severity.value,
            "validation_code": item.code,
            "validation_version": item.version,
        } for item in findings]
        payload.sort(key=lambda item: (
            item["validation_code"], item["canonical_key"] or "",
            item["related_snapshot_field_ids"], item["message"],
        ))
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _run_read(cls, row) -> PayrollValidationRunRead:
        readiness = (
            PayrollValidationReadiness.READY_FOR_FUTURE_APPROVAL
            if row.error_count == 0 and row.blocking_count == 0
            else PayrollValidationReadiness.NOT_READY
        )
        return PayrollValidationRunRead(
            id=row.id, import_id=row.payroll_import_id,
            snapshot_id=row.review_snapshot_id,
            validation_version=row.validation_version,
            ruleset_version=row.ruleset_version, status=row.status,
            readiness=readiness, snapshot_checksum=row.snapshot_checksum,
            result_checksum=row.result_checksum, started_at=row.started_at,
            completed_at=row.completed_at, created_by_user_id=row.created_by_user_id,
            info_count=row.info_count, warning_count=row.warning_count,
            error_count=row.error_count, blocking_count=row.blocking_count,
            created_at=row.created_at,
            results=[PayrollValidationResultRead.model_validate(result)
                     for result in row.results],
        )


__all__ = ["PayrollValidationService"]
