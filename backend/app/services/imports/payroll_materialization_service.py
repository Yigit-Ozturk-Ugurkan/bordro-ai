"""Atomic copy of exact approved snapshot facts into authoritative payroll history."""

import hashlib
import hmac
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PayrollApprovalContextStaleError,
    PayrollImportNotFoundError,
    PayrollMaterializationContextStaleError,
    PayrollMaterializationFieldTypeInvalidError,
    PayrollMaterializationIdentityInvalidError,
    PayrollMaterializationIntegrityFailedError,
    PayrollMaterializationNotApprovedError,
    PayrollMaterializationPeriodInvalidError,
    PayrollMaterializationRequiredFieldMissingError,
    PayrollMaterializationStateConflictError,
)
from app.models.enums import (
    CalculationMode,
    PayrollApprovalDecision,
    PayrollCanonicalValueType,
    PayrollSourceType,
    PayrollValidationRunStatus,
    PayrollValidationSeverity,
    PayrollVersionStatus,
)
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_materialization import PayrollImportMaterialization
from app.repositories.payroll_approval_repository import PayrollApprovalRepository
from app.repositories.payroll_materialization_repository import (
    PayrollMaterializationRepository,
)
from app.schemas.payroll_materialization import (
    PayrollMaterializationRead,
    PayrollMaterializationStateRead,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.payroll_approval_service import PayrollApprovalService


MATERIALIZATION_VERSION = 1

# Exact canonical-to-authoritative mapping. Generic/unmapped fields and tax-context
# fields are intentionally absent.
PAYROLL_VERSION_FIELD_SPECS = {
    "gross_earnings": ("gross_earnings", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "sgk_base": ("sgk_base", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "income_tax_base": ("income_tax_base", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "stamp_tax_base": ("stamp_tax_base", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "employee_sgk": ("employee_sgk", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "employee_unemployment": (
        "employee_unemployment", PayrollCanonicalValueType.DECIMAL, 18, 2,
    ),
    "income_tax": ("income_tax", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "stamp_tax": ("stamp_tax", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "total_earnings": ("total_earnings", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "total_deductions": (
        "total_deductions", PayrollCanonicalValueType.DECIMAL, 18, 2,
    ),
    "net_pay": ("net_pay", PayrollCanonicalValueType.DECIMAL, 18, 2),
    "paid_days": ("paid_days", PayrollCanonicalValueType.DAY_COUNT, 5, 2),
    "missing_days": ("missing_days", PayrollCanonicalValueType.DAY_COUNT, 5, 2),
}


class PayrollMaterializationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def materialize(
        self, user: AuthenticatedUser, import_id: UUID, approval_id: UUID,
    ) -> PayrollMaterializationRead:
        def work(sync):
            approval_repository = PayrollApprovalRepository(sync)
            repository = PayrollMaterializationRepository(sync)
            if approval_repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()

            approval = repository.get_approval_for_update(
                user.organization_id, import_id, approval_id,
            )
            if approval is None:
                raise PayrollMaterializationNotApprovedError()

            existing = repository.for_approval(user.organization_id, approval.id)
            if existing is not None:
                return self._read(repository, existing)

            snapshot, run = self._verify_approved_evidence(
                approval_repository, user, import_id, approval,
            )
            employee_no, year, month, values = self._extract_authoritative_values(
                snapshot.fields,
            )

            # The employee lock also serializes the no-Payroll-yet case, which a
            # SELECT FOR UPDATE on the absent payroll row cannot protect.
            employee = repository.employee_for_update(
                user.organization_id, employee_no,
            )
            if employee is None:
                raise PayrollMaterializationIdentityInvalidError()

            payroll = repository.payroll_for_update(
                user.organization_id, employee.id, year, month,
            )
            if payroll is None:
                payroll = Payroll(
                    id=uuid4(), organization_id=user.organization_id,
                    employee_id=employee.id, period_year=year, period_month=month,
                )
                repository.add_payroll(payroll)

            current = repository.current_version_for_update(payroll.id)
            revision = repository.next_revision(payroll.id)
            if current is not None:
                current.is_current = False
                if current.status == PayrollVersionStatus.ACTIVE:
                    current.status = PayrollVersionStatus.SUPERSEDED
                sync.flush()

            now = datetime.now(timezone.utc)
            version = PayrollVersion(
                id=uuid4(), payroll_id=payroll.id, revision_no=revision,
                status=PayrollVersionStatus.ACTIVE,
                source_type=PayrollSourceType.DOCUMENT,
                currency="TRY", calculation_mode=CalculationMode.IMPORTED,
                calculation_version="PAYROLL_MATERIALIZATION_V1",
                rule_set_id=None, source_import_id=import_id,
                source_checksum=snapshot.snapshot_checksum,
                is_current=True, published_at=now,
                **values,
            )
            repository.add_version(version)

            checksum = self.materialization_checksum(
                organization_id=user.organization_id, import_id=import_id,
                approval_id=approval.id, approval_checksum=approval.approval_checksum,
                snapshot_id=snapshot.id, snapshot_checksum=snapshot.snapshot_checksum,
                validation_run_id=run.id,
                validation_result_checksum=run.result_checksum,
                payroll_id=payroll.id, payroll_version_id=version.id,
                revision_no=revision,
            )
            materialization = PayrollImportMaterialization(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, approval_id=approval.id,
                review_snapshot_id=snapshot.id, validation_run_id=run.id,
                payroll_id=payroll.id, payroll_version_id=version.id,
                payroll_revision_no=revision,
                snapshot_checksum=snapshot.snapshot_checksum,
                validation_result_checksum=run.result_checksum,
                approval_checksum=approval.approval_checksum,
                materialization_checksum=checksum,
                materialization_version=MATERIALIZATION_VERSION,
                materialized_by_user_id=user.id,
                materialized_at=now, created_at=now,
            )
            repository.add_materialization(materialization)
            return self._read(repository, materialization)

        return await self._commit(work)

    async def current(
        self, user: AuthenticatedUser, import_id: UUID,
    ) -> PayrollMaterializationStateRead:
        def work(sync):
            approval_repository = PayrollApprovalRepository(sync)
            repository = PayrollMaterializationRepository(sync)
            snapshot_id, run = PayrollApprovalService.resolve_current_context(
                approval_repository, user, import_id,
            )
            if snapshot_id is None or run is None:
                return self._empty_state(import_id)
            approval = approval_repository.decision_for_run(
                user.organization_id, run.id,
            )
            if approval is None or approval.decision != PayrollApprovalDecision.APPROVED:
                return self._empty_state(import_id)
            materialization = repository.for_approval(
                user.organization_id, approval.id,
            )
            if materialization is None:
                return self._empty_state(import_id)
            return PayrollMaterializationStateRead(
                import_id=import_id, materialized=True,
                materialization=self._read(repository, materialization),
            )

        return await self._session.run_sync(work)

    async def _commit(self, work):
        try:
            response = await self._session.run_sync(work)
            await self._session.commit()
            return response
        except IntegrityError as exc:
            await self._session.rollback()
            raise PayrollMaterializationIntegrityFailedError() from exc
        except Exception:
            await self._session.rollback()
            raise

    @classmethod
    def _verify_approved_evidence(
        cls, repository, user, import_id, approval,
    ):
        if approval.decision != PayrollApprovalDecision.APPROVED:
            raise PayrollMaterializationNotApprovedError()

        current_snapshot_id, run = PayrollApprovalService.resolve_current_context(
            repository, user, import_id,
        )
        if (current_snapshot_id != approval.review_snapshot_id or run is None
                or run.id != approval.validation_run_id):
            raise PayrollMaterializationContextStaleError()
        snapshot = repository.get_snapshot(
            user.organization_id, import_id, approval.review_snapshot_id,
        )
        if snapshot is None:
            raise PayrollMaterializationContextStaleError()

        try:
            PayrollApprovalService.verify_context(run, snapshot)
        except PayrollApprovalContextStaleError as exc:
            raise PayrollMaterializationIntegrityFailedError() from exc

        if (run.status != PayrollValidationRunStatus.COMPLETED
                or approval.snapshot_checksum != snapshot.snapshot_checksum
                or approval.validation_result_checksum != run.result_checksum
                or approval.validation_ruleset_version != run.ruleset_version
                or snapshot.field_count != len(snapshot.fields)
                or snapshot.issue_count != 0):
            raise PayrollMaterializationIntegrityFailedError()

        acknowledgements = repository.acknowledgements_for_run(
            user.organization_id, run.id,
        )
        acknowledged_ids = tuple(sorted(
            (row.validation_result_id for row in acknowledgements), key=str,
        ))
        try:
            stored_acknowledged_ids = tuple(sorted(
                (UUID(str(value)) for value in approval.acknowledged_warning_result_ids),
                key=str,
            ))
        except (TypeError, ValueError) as exc:
            raise PayrollMaterializationIntegrityFailedError() from exc
        severities = Counter(row.severity for row in run.results)
        warning_ids = {
            row.id for row in run.results
            if row.severity == PayrollValidationSeverity.WARNING
        }
        if (stored_acknowledged_ids != acknowledged_ids
                or warning_ids != set(acknowledged_ids)
                or severities[PayrollValidationSeverity.ERROR]
                or severities[PayrollValidationSeverity.BLOCKING]):
            raise PayrollMaterializationIntegrityFailedError()

        expected_approval_checksum = PayrollApprovalService.approval_checksum(
            organization_id=user.organization_id, import_id=import_id,
            snapshot_id=snapshot.id, snapshot_checksum=snapshot.snapshot_checksum,
            validation_run_id=run.id,
            validation_result_checksum=run.result_checksum,
            ruleset_version=run.ruleset_version, decision=approval.decision,
            decision_reason=approval.decision_reason,
            acknowledged_warning_result_ids=acknowledged_ids,
        )
        if not hmac.compare_digest(
            approval.approval_checksum, expected_approval_checksum,
        ):
            raise PayrollMaterializationIntegrityFailedError()
        return snapshot, run

    @classmethod
    def _extract_authoritative_values(cls, fields):
        by_key = {}
        required_keys = {
            "employee_identifier", "period_year", "period_month",
            *PAYROLL_VERSION_FIELD_SPECS,
        }
        for key in required_keys:
            rows = [row for row in fields if row.effective_canonical_key == key]
            if not rows:
                raise PayrollMaterializationRequiredFieldMissingError(
                    f"Required authoritative field '{key}' is missing",
                )
            if len(rows) != 1:
                raise PayrollMaterializationStateConflictError(
                    f"Authoritative field '{key}' is duplicated",
                )
            by_key[key] = rows[0]

        identity = by_key["employee_identifier"]
        if (identity.value_type != PayrollCanonicalValueType.IDENTIFIER
                or not isinstance(identity.value_text, str)
                or not identity.value_text.strip()):
            raise PayrollMaterializationIdentityInvalidError()

        year_row, month_row = by_key["period_year"], by_key["period_month"]
        if (year_row.value_type != PayrollCanonicalValueType.INTEGER
                or month_row.value_type != PayrollCanonicalValueType.INTEGER
                or not isinstance(year_row.value_integer, int)
                or isinstance(year_row.value_integer, bool)
                or not isinstance(month_row.value_integer, int)
                or isinstance(month_row.value_integer, bool)
                or not 1 <= year_row.value_integer <= 9999
                or not 1 <= month_row.value_integer <= 12):
            raise PayrollMaterializationPeriodInvalidError()

        values = {}
        for key, (attribute, expected_type, precision, scale) in (
            PAYROLL_VERSION_FIELD_SPECS.items()
        ):
            row = by_key[key]
            if row.value_type != expected_type:
                raise PayrollMaterializationFieldTypeInvalidError(
                    f"Authoritative field '{key}' must be {expected_type.value}",
                )
            values[attribute] = cls._exact_decimal(
                key, row.value_decimal, precision, scale,
            )
        return identity.value_text, year_row.value_integer, month_row.value_integer, values

    @staticmethod
    def _exact_decimal(key: str, value, precision: int, scale: int) -> Decimal:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise PayrollMaterializationFieldTypeInvalidError(
                f"Authoritative field '{key}' is not a finite Decimal",
            )
        quantum = Decimal(1).scaleb(-scale)
        try:
            quantized = value.quantize(quantum)
        except InvalidOperation as exc:
            raise PayrollMaterializationFieldTypeInvalidError() from exc
        if value != quantized or abs(value) >= Decimal(10) ** (precision - scale):
            raise PayrollMaterializationFieldTypeInvalidError(
                f"Authoritative field '{key}' exceeds NUMERIC({precision},{scale})",
            )
        return value

    @staticmethod
    def materialization_checksum(
        *, organization_id: UUID, import_id: UUID,
        approval_id: UUID, approval_checksum: str,
        snapshot_id: UUID, snapshot_checksum: str,
        validation_run_id: UUID, validation_result_checksum: str,
        payroll_id: UUID, payroll_version_id: UUID, revision_no: int,
    ) -> str:
        payload = {
            "approval_checksum": approval_checksum,
            "approval_id": str(approval_id),
            "organization_id": str(organization_id),
            "payroll_id": str(payroll_id),
            "payroll_import_id": str(import_id),
            "payroll_version_id": str(payroll_version_id),
            "review_snapshot_id": str(snapshot_id),
            "revision_no": revision_no,
            "snapshot_checksum": snapshot_checksum,
            "validation_result_checksum": validation_result_checksum,
            "validation_run_id": str(validation_run_id),
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _read(repository, row) -> PayrollMaterializationRead:
        payroll = repository.get_payroll(row.organization_id, row.payroll_id)
        version = repository.get_version(row.payroll_id, row.payroll_version_id)
        if payroll is None or version is None:
            raise PayrollMaterializationIntegrityFailedError()
        return PayrollMaterializationRead(
            id=row.id, import_id=row.payroll_import_id,
            approval_id=row.approval_id, snapshot_id=row.review_snapshot_id,
            validation_run_id=row.validation_run_id,
            payroll_id=row.payroll_id, payroll_version_id=row.payroll_version_id,
            revision_no=row.payroll_revision_no, version_status=version.status,
            employee_id=payroll.employee_id, period_year=payroll.period_year,
            period_month=payroll.period_month,
            materialization_version=row.materialization_version,
            materialization_checksum=row.materialization_checksum,
            materialized_by_user_id=row.materialized_by_user_id,
            materialized_at=row.materialized_at,
        )

    @staticmethod
    def _empty_state(import_id: UUID) -> PayrollMaterializationStateRead:
        return PayrollMaterializationStateRead(
            import_id=import_id, materialized=False, materialization=None,
        )


__all__ = [
    "MATERIALIZATION_VERSION", "PAYROLL_VERSION_FIELD_SPECS",
    "PayrollMaterializationService",
]
