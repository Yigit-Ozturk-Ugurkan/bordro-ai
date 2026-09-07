"""Explicit human decisions over exact immutable snapshot/validation evidence."""

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidWarningAcknowledgementError,
    PayrollApprovalAlreadyDecidedError,
    PayrollApprovalContextStaleError,
    PayrollApprovalValidationNotCompletedError,
    PayrollApprovalValidationNotReadyError,
    PayrollApprovalWarningsUnacknowledgedError,
    PayrollImportNotFoundError,
    PayrollReviewSnapshotNotFoundError,
    PayrollValidationRunNotFoundError,
    WarningAlreadyAcknowledgedError,
)
from app.models.enums import (
    PayrollApprovalDecision,
    PayrollApprovalStatus,
    PayrollValidationReadiness,
    PayrollValidationRunStatus,
    PayrollValidationSeverity,
)
from app.models.payroll_approval import (
    PayrollImportApproval,
    PayrollImportValidationAcknowledgement,
)
from app.repositories.payroll_approval_repository import PayrollApprovalRepository
from app.schemas.payroll_approval import (
    PayrollApprovalDecisionRead,
    PayrollApprovalHistoryRead,
    PayrollApprovalStateRead,
    PayrollApprovalWarningSummary,
    PayrollWarningAcknowledgementRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_validation_rules import ValidationFinding
from app.services.imports.payroll_validation_service import PayrollValidationService


class PayrollApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acknowledge_warning(self, user: AuthenticatedUser, import_id: UUID,
                                  run_id: UUID, result_id: UUID,
                                  note: str | None) -> PayrollApprovalStateRead:
        def work(sync):
            repository = PayrollApprovalRepository(sync)
            run, snapshot = self._locked_context(repository, user, import_id, run_id)
            self.verify_context(run, snapshot)
            if repository.decision_for_run(user.organization_id, run_id) is not None:
                raise PayrollApprovalAlreadyDecidedError()
            result = repository.get_result(user.organization_id, run_id, result_id)
            if result is None or result.severity != PayrollValidationSeverity.WARNING:
                raise InvalidWarningAcknowledgementError()
            if repository.acknowledgement_for_result(
                user.organization_id, result_id,
            ) is not None:
                raise WarningAlreadyAcknowledgedError()
            repository.add_acknowledgement(PayrollImportValidationAcknowledgement(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, review_snapshot_id=run.review_snapshot_id,
                validation_run_id=run.id, validation_result_id=result.id,
                acknowledged_by_user_id=user.id, note=note,
                acknowledged_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            ))
            return self._state_for_run(repository, run)
        return await self._commit(work)

    async def approve(self, user: AuthenticatedUser, import_id: UUID,
                      run_id: UUID, note: str | None) -> PayrollApprovalStateRead:
        return await self._decide(
            user, import_id, run_id, PayrollApprovalDecision.APPROVED, note,
        )

    async def reject(self, user: AuthenticatedUser, import_id: UUID,
                     run_id: UUID, reason: str) -> PayrollApprovalStateRead:
        return await self._decide(
            user, import_id, run_id, PayrollApprovalDecision.REJECTED, reason,
        )

    async def _decide(self, user: AuthenticatedUser, import_id: UUID, run_id: UUID,
                      decision: PayrollApprovalDecision,
                      reason: str | None) -> PayrollApprovalStateRead:
        def work(sync):
            repository = PayrollApprovalRepository(sync)
            run, snapshot = self._locked_context(repository, user, import_id, run_id)
            self.verify_context(run, snapshot)
            if repository.decision_for_run(user.organization_id, run_id) is not None:
                raise PayrollApprovalAlreadyDecidedError()

            severities = Counter(result.severity for result in run.results)
            acknowledgements = repository.acknowledgements_for_run(
                user.organization_id, run.id,
            )
            acknowledged_ids = tuple(sorted(
                (row.validation_result_id for row in acknowledgements), key=str,
            ))
            warnings = [result for result in run.results
                        if result.severity == PayrollValidationSeverity.WARNING]
            if decision == PayrollApprovalDecision.APPROVED:
                if (severities[PayrollValidationSeverity.ERROR]
                        or severities[PayrollValidationSeverity.BLOCKING]):
                    raise PayrollApprovalValidationNotReadyError()
                missing = {result.id for result in warnings} - set(acknowledged_ids)
                if missing:
                    raise PayrollApprovalWarningsUnacknowledgedError()

            checksum = self.approval_checksum(
                organization_id=user.organization_id, import_id=import_id,
                snapshot_id=snapshot.id, snapshot_checksum=snapshot.snapshot_checksum,
                validation_run_id=run.id,
                validation_result_checksum=run.result_checksum,
                ruleset_version=run.ruleset_version, decision=decision,
                decision_reason=reason,
                acknowledged_warning_result_ids=acknowledged_ids,
            )
            now = datetime.now(timezone.utc)
            repository.add_decision(PayrollImportApproval(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, review_snapshot_id=snapshot.id,
                validation_run_id=run.id, snapshot_checksum=snapshot.snapshot_checksum,
                validation_result_checksum=run.result_checksum,
                validation_ruleset_version=run.ruleset_version,
                decision=decision, decision_reason=reason,
                acknowledged_warning_result_ids=[str(value) for value in acknowledged_ids],
                approval_checksum=checksum, decided_by_user_id=user.id,
                decided_at=now, created_at=now,
            ))
            return self._state_for_run(repository, run)
        return await self._commit(work)

    async def current(self, user: AuthenticatedUser,
                      import_id: UUID) -> PayrollApprovalStateRead:
        def work(sync):
            repository = PayrollApprovalRepository(sync)
            snapshot_id, run = self.resolve_current_context(
                repository, user, import_id,
            )
            if snapshot_id is None:
                return self._empty_state(import_id)
            if run is None:
                return self._empty_state(import_id, snapshot_id)
            return self._state_for_run(repository, run)
        return await self._session.run_sync(work)

    async def history(self, user: AuthenticatedUser,
                      import_id: UUID) -> PayrollApprovalHistoryRead:
        def work(sync):
            repository = PayrollApprovalRepository(sync)
            self._require_import(repository, user, import_id)
            approvals = repository.list_decisions(user.organization_id, import_id)
            acknowledgements = repository.list_acknowledgements(
                user.organization_id, import_id,
            )
            return PayrollApprovalHistoryRead(
                import_id=import_id, approval_count=len(approvals),
                acknowledgement_count=len(acknowledgements),
                approvals=[self._decision_read(row) for row in approvals],
                acknowledgements=[PayrollWarningAcknowledgementRead.model_validate(row)
                                  for row in acknowledgements],
            )
        return await self._session.run_sync(work)

    async def _commit(self, work):
        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except Exception:
            await self._session.rollback()
            raise

    @classmethod
    def _locked_context(cls, repository, user, import_id, run_id):
        cls._require_import(repository, user, import_id)
        run = repository.get_run(
            user.organization_id, import_id, run_id, for_update=True,
        )
        if run is None:
            raise PayrollValidationRunNotFoundError()
        snapshot = repository.get_snapshot(
            user.organization_id, import_id, run.review_snapshot_id,
        )
        if snapshot is None:
            raise PayrollReviewSnapshotNotFoundError()
        return run, snapshot

    @staticmethod
    def _require_import(repository, user, import_id) -> None:
        if repository.get_import(user.organization_id, import_id) is None:
            raise PayrollImportNotFoundError()

    @classmethod
    def resolve_current_context(cls, repository, user, import_id):
        cls._require_import(repository, user, import_id)
        snapshot_id = repository.current_snapshot_id(user.organization_id, import_id)
        if snapshot_id is None:
            return None, None
        return snapshot_id, repository.latest_run_for_snapshot(
            user.organization_id, import_id, snapshot_id,
        )

    @classmethod
    def verify_context(cls, run, snapshot) -> None:
        if run.status != PayrollValidationRunStatus.COMPLETED:
            raise PayrollApprovalValidationNotCompletedError()
        severities = Counter(result.severity for result in run.results)
        expected_counts = (
            severities[PayrollValidationSeverity.INFO],
            severities[PayrollValidationSeverity.WARNING],
            severities[PayrollValidationSeverity.ERROR],
            severities[PayrollValidationSeverity.BLOCKING],
        )
        stored_counts = (
            run.info_count, run.warning_count, run.error_count, run.blocking_count,
        )
        findings = [ValidationFinding(
            code=result.validation_code, version=result.validation_version,
            category=result.category, severity=result.severity, message=result.message,
            canonical_key=result.canonical_key,
            related_snapshot_field_ids=tuple(result.related_snapshot_field_ids),
            expected_value=result.expected_value, actual_value=result.actual_value,
            details=result.details,
        ) for result in run.results]
        computed_checksum = PayrollValidationService.result_checksum(findings)
        if (run.review_snapshot_id != snapshot.id
                or run.snapshot_checksum != snapshot.snapshot_checksum
                or run.result_checksum is None or len(run.result_checksum) != 64
                or run.result_checksum != computed_checksum
                or stored_counts != expected_counts):
            raise PayrollApprovalContextStaleError()

    @staticmethod
    def approval_checksum(*, organization_id: UUID, import_id: UUID,
                          snapshot_id: UUID, snapshot_checksum: str,
                          validation_run_id: UUID, validation_result_checksum: str,
                          ruleset_version: int, decision: PayrollApprovalDecision,
                          decision_reason: str | None,
                          acknowledged_warning_result_ids: tuple[UUID, ...]) -> str:
        payload = {
            "acknowledged_warning_result_ids": sorted(
                str(value) for value in acknowledged_warning_result_ids
            ),
            "decision": decision.value,
            "decision_reason": decision_reason,
            "organization_id": str(organization_id),
            "payroll_import_id": str(import_id),
            "review_snapshot_id": str(snapshot_id),
            "ruleset_version": ruleset_version,
            "snapshot_checksum": snapshot_checksum,
            "validation_result_checksum": validation_result_checksum,
            "validation_run_id": str(validation_run_id),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _state_for_run(cls, repository, run) -> PayrollApprovalStateRead:
        decision = repository.decision_for_run(run.organization_id, run.id)
        acknowledgements = repository.acknowledgements_for_run(
            run.organization_id, run.id,
        )
        warning_count = sum(
            result.severity == PayrollValidationSeverity.WARNING for result in run.results
        )
        acknowledged_count = len(acknowledgements)
        readiness = None
        if run.status == PayrollValidationRunStatus.COMPLETED:
            readiness = (
                PayrollValidationReadiness.READY_FOR_FUTURE_APPROVAL
                if not any(result.severity in {
                    PayrollValidationSeverity.ERROR,
                    PayrollValidationSeverity.BLOCKING,
                } for result in run.results)
                else PayrollValidationReadiness.NOT_READY
            )
        return PayrollApprovalStateRead(
            import_id=run.payroll_import_id,
            snapshot_id=run.review_snapshot_id, validation_run_id=run.id,
            validation_readiness=readiness,
            approval_status=(PayrollApprovalStatus(decision.decision.value)
                             if decision else PayrollApprovalStatus.NOT_DECIDED),
            decision=cls._decision_read(decision) if decision else None,
            warnings=PayrollApprovalWarningSummary(
                total=warning_count, acknowledged=acknowledged_count,
                remaining=warning_count - acknowledged_count,
            ),
        )

    @staticmethod
    def _empty_state(import_id: UUID, snapshot_id: UUID | None = None):
        return PayrollApprovalStateRead(
            import_id=import_id, snapshot_id=snapshot_id, validation_run_id=None,
            validation_readiness=None,
            approval_status=PayrollApprovalStatus.NOT_DECIDED, decision=None,
            warnings=PayrollApprovalWarningSummary(total=0, acknowledged=0, remaining=0),
        )

    @staticmethod
    def _decision_read(row) -> PayrollApprovalDecisionRead:
        return PayrollApprovalDecisionRead(
            id=row.id, snapshot_id=row.review_snapshot_id,
            validation_run_id=row.validation_run_id,
            snapshot_checksum=row.snapshot_checksum,
            validation_result_checksum=row.validation_result_checksum,
            validation_ruleset_version=row.validation_ruleset_version,
            decision=row.decision, decision_reason=row.decision_reason,
            acknowledged_warning_result_ids=row.acknowledged_warning_result_ids,
            approval_checksum=row.approval_checksum,
            decided_by_user_id=row.decided_by_user_id, decided_at=row.decided_at,
        )


__all__ = ["PayrollApprovalService"]
