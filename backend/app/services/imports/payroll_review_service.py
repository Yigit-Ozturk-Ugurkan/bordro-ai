"""Human review, correction history, effective values, and immutable snapshots."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidCanonicalOverrideError,
    InvalidReviewValueError,
    PayrollImportNotFoundError,
    PayrollReviewFieldNotFoundError,
    PayrollReviewIncompleteError,
    PayrollReviewNotFoundError,
    PayrollReviewSnapshotNotFoundError,
    PayrollReviewStateConflictError,
    PayrollReviewVersionConflictError,
)
from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollFieldMappingStatus,
    PayrollFieldParseStatus,
    PayrollImportFieldReviewStatus,
    PayrollImportReviewStatus,
    PayrollImportStatus,
    PayrollReviewCorrectionAction,
    PayrollReviewFieldStatus,
    PayrollReviewValueProvenance,
)
from app.models.payroll_import import PayrollImportMappedField
from app.models.payroll_review import (
    PayrollImportFieldCorrection,
    PayrollImportReview,
    PayrollImportReviewSnapshot,
    PayrollImportReviewSnapshotField,
)
from app.repositories.payroll_review_repository import PayrollReviewRepository
from app.schemas.payroll_import import (
    PayrollImportReviewRead,
    PayrollReviewAdapterRead,
    PayrollReviewCorrectionRead,
    PayrollReviewCorrectionRequest,
    PayrollReviewEffectiveRead,
    PayrollReviewFieldRead,
    PayrollReviewFinalizeRequest,
    PayrollReviewIssueRead,
    PayrollReviewRevertRequest,
    PayrollReviewSnapshotFieldRead,
    PayrollReviewSnapshotList,
    PayrollReviewSnapshotRead,
    PayrollReviewSnapshotSummary,
    PayrollReviewSourceRead,
    PayrollReviewTypedValue,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.canonical_fields import (
    REQUIRED_CANONICAL_FIELDS,
    get_canonical_field,
)
from app.services.imports.review_checksums import (
    adapter_fingerprint,
    adapter_output_checksum,
    canonical_scalar,
    corrections_checksum,
    sha256_canonical,
    source_staging_checksum,
)
from app.services.imports.value_parsing import ParsedValue, ValueParseError, parse_typed_value


@dataclass(slots=True)
class EffectiveField:
    row: PayrollImportMappedField
    correction: PayrollImportFieldCorrection | None
    history: list[PayrollImportFieldCorrection]
    status: PayrollReviewFieldStatus
    issue_codes: list[str]
    canonical_key: str | None = None
    section_key: str | None = None
    value_type: PayrollCanonicalValueType | None = None
    value_text: str | None = None
    value_decimal: Decimal | None = None
    value_integer: int | None = None
    value_date: date | None = None
    provenance: PayrollReviewValueProvenance | None = None
    fingerprint: str = ""


@dataclass(slots=True)
class ReviewEvaluation:
    fields: list[EffectiveField]
    issues: list[PayrollReviewIssueRead]

    @property
    def complete(self) -> bool:
        return not self.issues


class PayrollReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(self, user: AuthenticatedUser, import_id: UUID) -> PayrollImportReviewRead:
        def work(sync: Session) -> PayrollImportReviewRead:
            repository = PayrollReviewRepository(sync)
            item = repository.get_import(user.organization_id, import_id)
            if item is None:
                raise PayrollImportNotFoundError()
            if item.status not in {PayrollImportStatus.EXTRACTED, PayrollImportStatus.REVIEW_REQUIRED}:
                raise PayrollReviewStateConflictError()
            rows = repository.list_mapped_fields(user.organization_id, import_id)
            if not rows:
                raise PayrollReviewStateConflictError("Run the payroll adapter before review")
            review = repository.get_review_for_update(user.organization_id, import_id)
            if review is None:
                now = datetime.now(timezone.utc)
                review = PayrollImportReview(
                    id=uuid4(), organization_id=user.organization_id,
                    payroll_import_id=import_id,
                    status=PayrollImportReviewStatus.IN_PROGRESS,
                    started_by_user_id=user.id, started_at=now,
                    last_reviewed_by_user_id=user.id, last_reviewed_at=now,
                    adapter_output_checksum=adapter_output_checksum(rows), row_version=1,
                )
                repository.add_review(review)
            corrections = repository.list_corrections(user.organization_id, review.id)
            evaluation = self._evaluate(rows, corrections)
            if review.current_snapshot_id is None:
                review.status = self._open_status(evaluation)
                sync.flush()
            return self._review_read(review, evaluation)

        return await self._commit(work)

    async def get(self, user: AuthenticatedUser, import_id: UUID) -> PayrollImportReviewRead:
        def work(sync: Session) -> PayrollImportReviewRead:
            repository = PayrollReviewRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            review = repository.get_review(user.organization_id, import_id)
            if review is None:
                raise PayrollReviewNotFoundError()
            rows = repository.list_mapped_fields(user.organization_id, import_id)
            corrections = repository.list_corrections(user.organization_id, review.id)
            return self._review_read(review, self._evaluate(rows, corrections))

        return await self._read(work)

    async def correct(
        self, user: AuthenticatedUser, import_id: UUID, mapped_field_id: UUID,
        request: PayrollReviewCorrectionRequest,
    ) -> PayrollImportReviewRead:
        def work(sync: Session) -> PayrollImportReviewRead:
            repository = PayrollReviewRepository(sync)
            review = self._locked_review(repository, user, import_id, request.expected_review_version)
            row = repository.get_mapped_field(user.organization_id, import_id, mapped_field_id)
            if row is None:
                raise PayrollReviewFieldNotFoundError()
            if not self._has_source_observation(row):
                raise InvalidReviewValueError(
                    "A correction must be bound to a real source observation"
                )
            definition = None
            if request.canonical_key is not None:
                try:
                    definition = get_canonical_field(request.canonical_key)
                except ValueError:
                    raise InvalidCanonicalOverrideError() from None
            elif row.canonical_key is not None:
                definition = get_canonical_field(row.canonical_key)
            elif row.mapping_status == PayrollFieldMappingStatus.UNMAPPED:
                value_type = self._generic_value_type(row.source_field.value_type)
                if value_type is None:
                    raise InvalidCanonicalOverrideError(
                        "Select a registered canonical key for this source field"
                    )
            else:
                raise InvalidCanonicalOverrideError(
                    "An ambiguous mapping requires an explicit registered canonical key"
                )

            target_type = definition.value_type if definition else value_type
            try:
                parsed = parse_typed_value(request.value, target_type)
            except ValueParseError:
                raise InvalidReviewValueError() from None

            history = repository.list_corrections(user.organization_id, review.id)
            previous = self._latest_for_source(history).get(row.payroll_import_field_id)
            correction = PayrollImportFieldCorrection(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, review_id=review.id,
                payroll_import_field_id=row.payroll_import_field_id,
                source_mapped_field_id=row.id,
                revision=repository.next_correction_revision(
                    review.id, row.payroll_import_field_id,
                ),
                action=PayrollReviewCorrectionAction.APPLY,
                supersedes_correction_id=previous.id if previous else None,
                reviewer_user_id=user.id, reason=request.reason,
                adapter_fingerprint=adapter_fingerprint(row),
                original_mapping_status=row.mapping_status,
                original_canonical_key=row.canonical_key,
                original_value_type=row.target_value_type,
                **self._prefixed_value_columns(row, "original_"),
                override_canonical_key=definition.canonical_key if definition else None,
                section_key=definition.section_key if definition else None,
                value_type=target_type,
                **self._value_columns(parsed),
            )
            repository.add_correction(correction)
            self._touch_review(review, user)
            rows = repository.list_mapped_fields(user.organization_id, import_id)
            history.append(correction)
            evaluation = self._evaluate(rows, history)
            review.status = self._open_status(evaluation)
            sync.flush()
            return self._review_read(review, evaluation)

        return await self._commit(work)

    async def revert(
        self, user: AuthenticatedUser, import_id: UUID, mapped_field_id: UUID,
        request: PayrollReviewRevertRequest,
    ) -> PayrollImportReviewRead:
        def work(sync: Session) -> PayrollImportReviewRead:
            repository = PayrollReviewRepository(sync)
            review = self._locked_review(repository, user, import_id, request.expected_review_version)
            row = repository.get_mapped_field(user.organization_id, import_id, mapped_field_id)
            if row is None:
                raise PayrollReviewFieldNotFoundError()
            history = repository.list_corrections(user.organization_id, review.id)
            previous = self._latest_for_source(history).get(row.payroll_import_field_id)
            if previous is None or previous.action == PayrollReviewCorrectionAction.REVERT:
                raise PayrollReviewStateConflictError("The field has no active correction")
            correction = PayrollImportFieldCorrection(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, review_id=review.id,
                payroll_import_field_id=row.payroll_import_field_id,
                source_mapped_field_id=row.id,
                revision=repository.next_correction_revision(
                    review.id, row.payroll_import_field_id,
                ),
                action=PayrollReviewCorrectionAction.REVERT,
                supersedes_correction_id=previous.id,
                reviewer_user_id=user.id, reason=request.reason,
                adapter_fingerprint=adapter_fingerprint(row),
                original_mapping_status=row.mapping_status,
                original_canonical_key=row.canonical_key,
                original_value_type=row.target_value_type,
                **self._prefixed_value_columns(row, "original_"),
            )
            repository.add_correction(correction)
            self._touch_review(review, user)
            rows = repository.list_mapped_fields(user.organization_id, import_id)
            history.append(correction)
            evaluation = self._evaluate(rows, history)
            review.status = self._open_status(evaluation)
            sync.flush()
            return self._review_read(review, evaluation)

        return await self._commit(work)

    async def finalize(
        self, user: AuthenticatedUser, import_id: UUID,
        request: PayrollReviewFinalizeRequest,
    ) -> PayrollReviewSnapshotRead:
        def work(sync: Session) -> PayrollReviewSnapshotRead:
            repository = PayrollReviewRepository(sync)
            review = self._locked_review(repository, user, import_id, request.expected_review_version)
            rows = repository.list_mapped_fields(user.organization_id, import_id)
            corrections = repository.list_corrections(user.organization_id, review.id)
            evaluation = self._evaluate(rows, corrections)
            if not evaluation.complete:
                raise PayrollReviewIncompleteError()

            content = [self._snapshot_content(field) for field in evaluation.fields]
            content.sort(key=lambda value: value["source_import_field_id"])
            checksum = sha256_canonical(content)
            latest = repository.latest_snapshot(user.organization_id, review.id)
            if latest is not None and latest.snapshot_checksum == checksum:
                review.current_snapshot_id = latest.id
                review.status = PayrollImportReviewStatus.SNAPSHOTTED
                sync.flush()
                return self._snapshot_read(latest)

            snapshot = PayrollImportReviewSnapshot(
                id=uuid4(), organization_id=user.organization_id,
                payroll_import_id=import_id, review_id=review.id,
                snapshot_version=repository.next_snapshot_version(review.id),
                created_by_user_id=user.id,
                source_staging_checksum=source_staging_checksum(rows),
                adapter_output_checksum=adapter_output_checksum(rows),
                review_corrections_checksum=corrections_checksum(corrections),
                snapshot_checksum=checksum,
                field_count=len(evaluation.fields), issue_count=0,
            )
            snapshot_fields = [self._snapshot_model(snapshot, field) for field in evaluation.fields]
            repository.add_snapshot(snapshot, snapshot_fields)
            review.current_snapshot_id = snapshot.id
            review.status = PayrollImportReviewStatus.SNAPSHOTTED
            self._touch_review(review, user)
            sync.flush()
            snapshot.fields = snapshot_fields
            return self._snapshot_read(snapshot)

        return await self._commit(work)

    async def snapshots(
        self, user: AuthenticatedUser, import_id: UUID,
    ) -> PayrollReviewSnapshotList:
        def work(sync: Session) -> PayrollReviewSnapshotList:
            repository = PayrollReviewRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            rows = repository.list_snapshots(user.organization_id, import_id)
            return PayrollReviewSnapshotList(
                import_id=import_id, count=len(rows),
                items=[self._snapshot_summary(row) for row in rows],
            )

        return await self._read(work)

    async def snapshot(
        self, user: AuthenticatedUser, import_id: UUID, snapshot_id: UUID,
    ) -> PayrollReviewSnapshotRead:
        def work(sync: Session) -> PayrollReviewSnapshotRead:
            repository = PayrollReviewRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            snapshot = repository.get_review_snapshot(
                user.organization_id, import_id, snapshot_id,
            )
            if snapshot is None:
                raise PayrollReviewSnapshotNotFoundError()
            return self._snapshot_read(snapshot)

        return await self._read(work)

    async def _commit(self, work):
        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except Exception:
            await self._session.rollback()
            raise

    async def _read(self, work):
        return await self._session.run_sync(work)

    @staticmethod
    def _locked_review(repository, user, import_id, expected_version):
        if repository.get_import(user.organization_id, import_id) is None:
            raise PayrollImportNotFoundError()
        review = repository.get_review_for_update(user.organization_id, import_id)
        if review is None:
            raise PayrollReviewNotFoundError()
        if review.row_version != expected_version:
            raise PayrollReviewVersionConflictError()
        return review

    @staticmethod
    def _touch_review(review: PayrollImportReview, user: AuthenticatedUser) -> None:
        review.row_version += 1
        review.last_reviewed_by_user_id = user.id
        review.last_reviewed_at = datetime.now(timezone.utc)

    @staticmethod
    def _open_status(evaluation: ReviewEvaluation) -> PayrollImportReviewStatus:
        return (
            PayrollImportReviewStatus.READY_FOR_SNAPSHOT
            if evaluation.complete else PayrollImportReviewStatus.IN_PROGRESS
        )

    @staticmethod
    def _has_source_observation(row: PayrollImportMappedField) -> bool:
        source = row.source_field
        return any(value is not None and str(value).strip() for value in (
            source.raw_value, source.normalized_value, source.source_text,
        ))

    @staticmethod
    def _generic_value_type(value_type: str | None) -> PayrollCanonicalValueType | None:
        if value_type is None:
            return PayrollCanonicalValueType.TEXT
        aliases = {
            "date": PayrollCanonicalValueType.DATE,
            "decimal": PayrollCanonicalValueType.DECIMAL,
            "money": PayrollCanonicalValueType.DECIMAL,
            "number": PayrollCanonicalValueType.DECIMAL,
            "integer": PayrollCanonicalValueType.INTEGER,
            "int": PayrollCanonicalValueType.INTEGER,
            "day_count": PayrollCanonicalValueType.DAY_COUNT,
            "text": PayrollCanonicalValueType.TEXT,
            "string": PayrollCanonicalValueType.TEXT,
            "identifier": PayrollCanonicalValueType.IDENTIFIER,
        }
        return aliases.get(value_type.strip().casefold())

    @classmethod
    def _evaluate(
        cls, rows: list[PayrollImportMappedField],
        corrections: list[PayrollImportFieldCorrection],
    ) -> ReviewEvaluation:
        histories: dict[UUID, list[PayrollImportFieldCorrection]] = {}
        for correction in corrections:
            histories.setdefault(correction.payroll_import_field_id, []).append(correction)
        effective = [cls._resolve(row, histories.get(row.payroll_import_field_id, [])) for row in rows]
        issues = [
            PayrollReviewIssueRead(
                code=code, source_field_id=field.row.payroll_import_field_id,
                canonical_key=field.canonical_key,
            )
            for field in effective for code in field.issue_codes
        ]
        resolved_keys = [
            field.canonical_key for field in effective
            if field.status == PayrollReviewFieldStatus.RESOLVED and field.canonical_key
        ]
        counts = Counter(resolved_keys)
        for key, count in sorted(counts.items()):
            if count > 1:
                issues.append(PayrollReviewIssueRead(
                    code="DUPLICATE_CANONICAL_FIELD", canonical_key=key,
                ))
        for definition in REQUIRED_CANONICAL_FIELDS:
            if counts[definition.canonical_key] == 0:
                issues.append(PayrollReviewIssueRead(
                    code="REQUIRED_CANONICAL_FIELD_MISSING",
                    canonical_key=definition.canonical_key,
                ))
        return ReviewEvaluation(fields=effective, issues=issues)

    @classmethod
    def _resolve(
        cls, row: PayrollImportMappedField,
        history: list[PayrollImportFieldCorrection],
    ) -> EffectiveField:
        fingerprint = adapter_fingerprint(row)
        latest = history[-1] if history else None
        if latest is not None and latest.action == PayrollReviewCorrectionAction.APPLY:
            if latest.adapter_fingerprint != fingerprint:
                return EffectiveField(
                    row=row, correction=latest, history=history,
                    status=PayrollReviewFieldStatus.STALE,
                    issue_codes=["CORRECTION_STALE"], fingerprint=fingerprint,
                )
            return EffectiveField(
                row=row, correction=latest, history=history,
                status=PayrollReviewFieldStatus.RESOLVED, issue_codes=[],
                canonical_key=latest.override_canonical_key,
                section_key=latest.section_key, value_type=latest.value_type,
                value_text=latest.value_text, value_decimal=latest.value_decimal,
                value_integer=latest.value_integer, value_date=latest.value_date,
                provenance=PayrollReviewValueProvenance.REVIEWER_CORRECTION,
                fingerprint=fingerprint,
            )

        source = row.source_field
        if (row.mapping_status == PayrollFieldMappingStatus.MAPPED
                and row.parse_status == PayrollFieldParseStatus.PARSED
                and row.review_status == PayrollImportFieldReviewStatus.UNREVIEWED
                and source.review_status == PayrollImportFieldReviewStatus.UNREVIEWED):
            return EffectiveField(
                row=row, correction=None, history=history,
                status=PayrollReviewFieldStatus.RESOLVED, issue_codes=[],
                canonical_key=row.canonical_key, section_key=row.section_key,
                value_type=row.target_value_type, value_text=row.value_text,
                value_decimal=row.value_decimal, value_integer=row.value_integer,
                value_date=row.value_date, provenance=PayrollReviewValueProvenance.ADAPTER,
                fingerprint=fingerprint,
            )
        if (row.mapping_status == PayrollFieldMappingStatus.UNMAPPED
                and source.review_status == PayrollImportFieldReviewStatus.UNREVIEWED):
            generic_value = source.raw_value or source.normalized_value or source.source_text
            if generic_value is not None and generic_value.strip():
                return EffectiveField(
                    row=row, correction=None, history=history,
                    status=PayrollReviewFieldStatus.RESOLVED, issue_codes=[],
                    value_type=PayrollCanonicalValueType.TEXT,
                    value_text=generic_value,
                    provenance=PayrollReviewValueProvenance.ADAPTER,
                    fingerprint=fingerprint,
                )
            code = "GENERIC_VALUE_MISSING"
        elif row.mapping_status == PayrollFieldMappingStatus.AMBIGUOUS:
            code = "AMBIGUOUS_MAPPING_UNRESOLVED"
        elif row.mapping_status == PayrollFieldMappingStatus.PARSE_FAILED:
            code = "VALUE_PARSE_FAILED_UNRESOLVED"
        elif source.review_status == PayrollImportFieldReviewStatus.MISSING:
            code = "SOURCE_MISSING_UNRESOLVED"
        else:
            code = "SOURCE_REVIEW_REQUIRED_UNRESOLVED"
        return EffectiveField(
            row=row, correction=None, history=history,
            status=PayrollReviewFieldStatus.PENDING,
            issue_codes=[code], fingerprint=fingerprint,
        )

    @staticmethod
    def _latest_for_source(rows):
        latest = {}
        for row in rows:
            current = latest.get(row.payroll_import_field_id)
            if current is None or row.revision > current.revision:
                latest[row.payroll_import_field_id] = row
        return latest

    @staticmethod
    def _value_columns(parsed: ParsedValue) -> dict:
        if isinstance(parsed.value, Decimal):
            return {"value_decimal": parsed.value}
        if isinstance(parsed.value, int):
            return {"value_integer": parsed.value}
        if isinstance(parsed.value, date):
            return {"value_date": parsed.value}
        return {"value_text": parsed.value}

    @staticmethod
    def _prefixed_value_columns(row, prefix: str) -> dict:
        return {
            f"{prefix}value_text": row.value_text,
            f"{prefix}value_decimal": row.value_decimal,
            f"{prefix}value_integer": row.value_integer,
            f"{prefix}value_date": row.value_date,
        }

    @staticmethod
    def _typed(
        value_type, value_text, value_decimal, value_integer, value_date,
    ) -> PayrollReviewTypedValue | None:
        if value_type is None:
            return None
        if value_decimal is not None:
            value = format(value_decimal, "f")
        elif value_integer is not None:
            value = value_integer
        elif value_date is not None:
            value = value_date.isoformat()
        elif value_text is not None:
            value = value_text
        else:
            return None
        return PayrollReviewTypedValue(type=value_type, value=value)

    @classmethod
    def _review_read(cls, review, evaluation) -> PayrollImportReviewRead:
        return PayrollImportReviewRead(
            id=review.id, import_id=review.payroll_import_id,
            status=review.status, version=review.row_version,
            started_by_user_id=review.started_by_user_id, started_at=review.started_at,
            last_reviewed_by_user_id=review.last_reviewed_by_user_id,
            last_reviewed_at=review.last_reviewed_at,
            current_snapshot_id=review.current_snapshot_id,
            complete=evaluation.complete, issues=evaluation.issues,
            fields=[cls._field_read(field) for field in evaluation.fields],
        )

    @classmethod
    def _field_read(cls, field: EffectiveField) -> PayrollReviewFieldRead:
        row, source = field.row, field.row.source_field
        return PayrollReviewFieldRead(
            source=PayrollReviewSourceRead(
                field_id=source.id, external_field_id=source.source_field_id,
                label=source.source_label, source_text=source.source_text,
                raw_value=source.raw_value, normalized_value=source.normalized_value,
                source_value_type=source.value_type,
                confidence=format(source.confidence, "f") if source.confidence is not None else None,
                page_number=source.page_number, bbox=source.bbox,
                extraction_source=source.extraction_source,
                staging_review_status=source.review_status,
            ),
            adapter=PayrollReviewAdapterRead(
                mapped_field_id=row.id, canonical_key=row.canonical_key,
                section_key=row.section_key, mapping_status=row.mapping_status,
                parse_status=row.parse_status,
                typed_value=cls._typed(
                    row.target_value_type, row.value_text, row.value_decimal,
                    row.value_integer, row.value_date,
                ),
                candidate_canonical_keys=row.candidate_canonical_keys,
                review_status=row.review_status,
                review_reason_codes=row.review_reason_codes,
                fingerprint=field.fingerprint,
            ),
            correction=(cls._correction_read(field.correction, field.fingerprint)
                        if field.correction else None),
            correction_history=[cls._correction_read(value, field.fingerprint)
                                for value in field.history],
            effective=PayrollReviewEffectiveRead(
                canonical_key=field.canonical_key, section_key=field.section_key,
                typed_value=cls._typed(
                    field.value_type, field.value_text, field.value_decimal,
                    field.value_integer, field.value_date,
                ),
                provenance=field.provenance,
            ),
            review_status=field.status, issue_codes=field.issue_codes,
        )

    @classmethod
    def _correction_read(cls, row, fingerprint) -> PayrollReviewCorrectionRead:
        return PayrollReviewCorrectionRead(
            id=row.id, revision=row.revision, action=row.action,
            canonical_key=row.override_canonical_key,
            typed_value=cls._typed(
                row.value_type, row.value_text, row.value_decimal,
                row.value_integer, row.value_date,
            ),
            reviewer_user_id=row.reviewer_user_id, reason=row.reason,
            created_at=row.created_at,
            is_stale=(
                row.action == PayrollReviewCorrectionAction.APPLY
                and row.adapter_fingerprint != fingerprint
            ),
        )

    @classmethod
    def _snapshot_content(cls, field: EffectiveField) -> dict:
        source = field.row.source_field
        return {
            "adapter_fingerprint": field.fingerprint,
            "bbox": [canonical_scalar(value) for value in source.bbox] if source.bbox else None,
            "confidence": canonical_scalar(source.confidence),
            "effective_canonical_key": field.canonical_key,
            "extraction_source": source.extraction_source,
            "original_mapping_status": canonical_scalar(field.row.mapping_status),
            "page_number": source.page_number,
            "provenance": canonical_scalar(field.provenance),
            "raw_value": source.raw_value,
            "review_status": canonical_scalar(field.status),
            "section_key": field.section_key,
            "source_field_id": source.source_field_id,
            "source_import_field_id": str(source.id),
            "source_label": source.source_label,
            "source_text": source.source_text,
            "source_value_type": source.value_type,
            "value_date": canonical_scalar(field.value_date),
            "value_decimal": canonical_scalar(field.value_decimal),
            "value_integer": field.value_integer,
            "value_text": field.value_text,
            "value_type": canonical_scalar(field.value_type),
        }

    @classmethod
    def _snapshot_model(cls, snapshot, field) -> PayrollImportReviewSnapshotField:
        source = field.row.source_field
        return PayrollImportReviewSnapshotField(
            id=uuid4(), organization_id=snapshot.organization_id,
            payroll_import_id=snapshot.payroll_import_id, review_id=snapshot.review_id,
            snapshot_id=snapshot.id, source_import_field_id=source.id,
            source_mapped_field_id=field.row.id,
            source_field_id=source.source_field_id, source_label=source.source_label,
            source_text=source.source_text, raw_value=source.raw_value,
            source_value_type=source.value_type,
            effective_canonical_key=field.canonical_key, section_key=field.section_key,
            value_type=field.value_type, value_text=field.value_text,
            value_decimal=field.value_decimal, value_integer=field.value_integer,
            value_date=field.value_date, provenance=field.provenance,
            confidence=source.confidence, page_number=source.page_number,
            bbox=source.bbox, extraction_source=source.extraction_source,
            original_mapping_status=field.row.mapping_status,
            review_status=field.status,
            correction_id=field.correction.id if field.correction else None,
            adapter_fingerprint=field.fingerprint,
        )

    @classmethod
    def _snapshot_field_read(cls, row) -> PayrollReviewSnapshotFieldRead:
        return PayrollReviewSnapshotFieldRead(
            id=row.id, source_import_field_id=row.source_import_field_id,
            source_mapped_field_id=row.source_mapped_field_id,
            source_field_id=row.source_field_id, source_label=row.source_label,
            source_text=row.source_text, raw_value=row.raw_value,
            source_value_type=row.source_value_type,
            effective_canonical_key=row.effective_canonical_key,
            section_key=row.section_key,
            typed_value=cls._typed(
                row.value_type, row.value_text, row.value_decimal,
                row.value_integer, row.value_date,
            ),
            provenance=row.provenance,
            confidence=format(row.confidence, "f") if row.confidence is not None else None,
            page_number=row.page_number, bbox=row.bbox,
            extraction_source=row.extraction_source,
            original_mapping_status=row.original_mapping_status,
            review_status=row.review_status, correction_id=row.correction_id,
            adapter_fingerprint=row.adapter_fingerprint,
        )

    @staticmethod
    def _snapshot_summary(row) -> PayrollReviewSnapshotSummary:
        return PayrollReviewSnapshotSummary(
            id=row.id, import_id=row.payroll_import_id, review_id=row.review_id,
            snapshot_version=row.snapshot_version,
            created_by_user_id=row.created_by_user_id, created_at=row.created_at,
            source_staging_checksum=row.source_staging_checksum,
            adapter_output_checksum=row.adapter_output_checksum,
            review_corrections_checksum=row.review_corrections_checksum,
            snapshot_checksum=row.snapshot_checksum,
            field_count=row.field_count, issue_count=row.issue_count,
        )

    @classmethod
    def _snapshot_read(cls, row) -> PayrollReviewSnapshotRead:
        return PayrollReviewSnapshotRead(
            **cls._snapshot_summary(row).model_dump(),
            fields=[cls._snapshot_field_read(field) for field in row.fields],
        )


__all__ = ["PayrollReviewService"]
