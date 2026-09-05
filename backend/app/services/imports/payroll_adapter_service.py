"""Deterministic conversion of generic extraction staging into review-only data."""

from collections import Counter
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import (
    PayrollImportMappingConflictError,
    PayrollImportNotFoundError,
    PayrollMappingConfigurationError,
)
from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollFieldMappingScope,
    PayrollFieldMappingStatus,
    PayrollFieldParseStatus,
    PayrollImportFieldReviewStatus,
    PayrollImportStatus,
)
from app.models.payroll_import import (
    PayrollFieldMapping,
    PayrollImportField,
    PayrollImportMappedField,
    PayrollImportMappingIssue,
)
from app.repositories.payroll_mapping_repository import PayrollMappingRepository
from app.schemas.payroll_import import (
    PayrollImportMappedFieldList,
    PayrollImportMappedFieldRead,
    PayrollImportMappingIssueRead,
    PayrollImportMappingSummary,
    PayrollImportTypedValue,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.canonical_fields import (
    REQUIRED_CANONICAL_FIELDS,
    get_canonical_field,
)
from app.services.imports.label_normalization import normalize_source_label
from app.services.imports.value_parsing import ParsedValue, ValueParseError, parse_typed_value

LOW_CONFIDENCE_THRESHOLD = Decimal("0.80")
_SCOPE_RANK = {
    PayrollFieldMappingScope.SYSTEM: 1,
    PayrollFieldMappingScope.ORGANIZATION: 2,
    PayrollFieldMappingScope.TEMPLATE: 3,
}


class PayrollAdapterService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, user: AuthenticatedUser, import_id: UUID) -> PayrollImportMappingSummary:
        def work(sync: Session) -> PayrollImportMappingSummary:
            repository = PayrollMappingRepository(sync)
            item = repository.get_import_for_update(user.organization_id, import_id)
            if item is None:
                raise PayrollImportNotFoundError()
            if item.status not in {PayrollImportStatus.EXTRACTED, PayrollImportStatus.REVIEW_REQUIRED}:
                raise PayrollImportMappingConflictError()

            rows = [self._adapt_field(repository, item, field) for field in item.fields]
            present_keys = {
                row.canonical_key for row in rows
                if row.mapping_status == PayrollFieldMappingStatus.MAPPED
                and row.parse_status == PayrollFieldParseStatus.PARSED
                and row.review_status != PayrollImportFieldReviewStatus.MISSING
            }
            issues = [PayrollImportMappingIssue(
                organization_id=item.organization_id,
                payroll_import_id=item.id,
                canonical_key=definition.canonical_key,
                section_key=definition.section_key,
                target_value_type=definition.value_type,
                issue_code="REQUIRED_CANONICAL_FIELD_MISSING",
                review_status=PayrollImportFieldReviewStatus.MISSING,
            ) for definition in REQUIRED_CANONICAL_FIELDS
                if definition.canonical_key not in present_keys]
            repository.replace_results(item.organization_id, item.id, rows, issues)
            return self._summary(item.id, rows, issues)

        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except Exception:
            await self._session.rollback()
            raise

    async def mapped_fields(self, user: AuthenticatedUser,
                            import_id: UUID) -> PayrollImportMappedFieldList:
        def work(sync: Session) -> PayrollImportMappedFieldList:
            repository = PayrollMappingRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            rows = repository.list_results(user.organization_id, import_id)
            return PayrollImportMappedFieldList(
                import_id=import_id, count=len(rows), items=[self._read(row) for row in rows]
            )
        return await self._session.run_sync(work)

    async def summary(self, user: AuthenticatedUser,
                      import_id: UUID) -> PayrollImportMappingSummary:
        def work(sync: Session) -> PayrollImportMappingSummary:
            repository = PayrollMappingRepository(sync)
            if repository.get_import(user.organization_id, import_id) is None:
                raise PayrollImportNotFoundError()
            rows = repository.list_results(user.organization_id, import_id)
            issues = repository.list_issues(user.organization_id, import_id)
            return self._summary(import_id, rows, issues)
        return await self._session.run_sync(work)

    def _adapt_field(self, repository: PayrollMappingRepository, item,
                     field: PayrollImportField) -> PayrollImportMappedField:
        normalized = normalize_source_label(field.source_label)
        candidates = repository.candidates(item, field.source_field_id, normalized)
        winners = self._winning_candidates(candidates)
        base = dict(
            organization_id=item.organization_id, payroll_import_id=item.id,
            payroll_import_field_id=field.id, candidate_canonical_keys=sorted({
                candidate.canonical_key for candidate in winners
            }),
        )
        if not winners:
            return PayrollImportMappedField(
                **base, mapping_status=PayrollFieldMappingStatus.UNMAPPED,
                parse_status=PayrollFieldParseStatus.NOT_APPLICABLE,
                review_status=PayrollImportFieldReviewStatus.REVIEW_REQUIRED,
                review_reason_codes=["UNMAPPED_SOURCE_FIELD"],
            )
        if len(winners) != 1:
            return PayrollImportMappedField(
                **base, mapping_status=PayrollFieldMappingStatus.AMBIGUOUS,
                parse_status=PayrollFieldParseStatus.NOT_APPLICABLE,
                review_status=PayrollImportFieldReviewStatus.REVIEW_REQUIRED,
                review_reason_codes=["AMBIGUOUS_MAPPING"],
            )
        mapping = winners[0]
        definition = get_canonical_field(mapping.canonical_key)
        if (mapping.section_key != definition.section_key
                or mapping.target_value_type != definition.value_type
                or not definition.automatic_mapping_allowed):
            raise PayrollMappingConfigurationError()
        raw = field.raw_value if field.raw_value is not None else field.normalized_value
        reasons = self._source_review_reasons(field)
        try:
            parsed = parse_typed_value(raw, definition.value_type)
        except ValueParseError:
            return PayrollImportMappedField(
                **base, canonical_key=definition.canonical_key,
                section_key=definition.section_key, mapping_id=mapping.id,
                mapping_version=mapping.version, target_value_type=definition.value_type,
                mapping_status=PayrollFieldMappingStatus.PARSE_FAILED,
                parse_status=PayrollFieldParseStatus.FAILED,
                review_status=PayrollImportFieldReviewStatus.REVIEW_REQUIRED,
                review_reason_codes=sorted({*reasons, "VALUE_PARSE_FAILED"}),
            )
        values = self._value_columns(parsed)
        return PayrollImportMappedField(
            **base, canonical_key=definition.canonical_key,
            section_key=definition.section_key, mapping_id=mapping.id,
            mapping_version=mapping.version, target_value_type=definition.value_type,
            mapping_status=PayrollFieldMappingStatus.MAPPED,
            parse_status=PayrollFieldParseStatus.PARSED,
            review_status=(
                PayrollImportFieldReviewStatus.MISSING
                if field.review_status == PayrollImportFieldReviewStatus.MISSING
                else (PayrollImportFieldReviewStatus.REVIEW_REQUIRED
                      if reasons else PayrollImportFieldReviewStatus.UNREVIEWED)
            ),
            review_reason_codes=reasons, **values,
        )

    @staticmethod
    def _winning_candidates(candidates: list[PayrollFieldMapping]) -> list[PayrollFieldMapping]:
        if not candidates:
            return []
        rank = max(_SCOPE_RANK[value.scope] for value in candidates)
        scoped = [value for value in candidates if _SCOPE_RANK[value.scope] == rank]
        priority = max(value.priority for value in scoped)
        return sorted(
            [value for value in scoped if value.priority == priority],
            key=lambda value: (value.canonical_key, str(value.id)),
        )

    @staticmethod
    def _source_review_reasons(field: PayrollImportField) -> list[str]:
        reasons = []
        if field.review_status == PayrollImportFieldReviewStatus.MISSING:
            reasons.append("SOURCE_MISSING")
        elif field.review_status == PayrollImportFieldReviewStatus.REVIEW_REQUIRED:
            reasons.append("SOURCE_REVIEW_REQUIRED")
        if field.confidence is not None and field.confidence < LOW_CONFIDENCE_THRESHOLD:
            reasons.append("LOW_CONFIDENCE_SOURCE")
        if field.extraction_source and "llm" in field.extraction_source.casefold():
            reasons.append("LLM_SOURCE")
        return sorted(set(reasons))

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
    def _typed_value(row: PayrollImportMappedField) -> PayrollImportTypedValue | None:
        if row.parse_status != PayrollFieldParseStatus.PARSED or row.target_value_type is None:
            return None
        if row.value_decimal is not None:
            value: str | int = format(row.value_decimal, "f")
        elif row.value_integer is not None:
            value = row.value_integer
        elif row.value_date is not None:
            value = row.value_date.isoformat()
        else:
            value = row.value_text or ""
        return PayrollImportTypedValue(type=row.target_value_type, value=value)

    @classmethod
    def _read(cls, row: PayrollImportMappedField) -> PayrollImportMappedFieldRead:
        source = row.source_field
        return PayrollImportMappedFieldRead(
            id=row.id, source_field_id=source.id,
            source_external_field_id=source.source_field_id,
            source_label=source.source_label, raw_value=source.raw_value,
            canonical_key=row.canonical_key, section_key=row.section_key,
            mapping_id=row.mapping_id, mapping_version=row.mapping_version,
            typed_value=cls._typed_value(row),
            candidate_canonical_keys=row.candidate_canonical_keys,
            mapping_status=row.mapping_status, parse_status=row.parse_status,
            review_status=row.review_status,
            review_reason_codes=row.review_reason_codes,
        )

    @staticmethod
    def _summary(import_id: UUID, rows, issues) -> PayrollImportMappingSummary:
        counts = Counter(row.mapping_status for row in rows)
        review_count = sum(
            row.review_status != PayrollImportFieldReviewStatus.UNREVIEWED for row in rows
        ) + len(issues)
        return PayrollImportMappingSummary(
            import_id=import_id, source_field_count=len(rows),
            mapped_count=counts[PayrollFieldMappingStatus.MAPPED],
            unmapped_count=counts[PayrollFieldMappingStatus.UNMAPPED],
            ambiguous_count=counts[PayrollFieldMappingStatus.AMBIGUOUS],
            parse_failed_count=counts[PayrollFieldMappingStatus.PARSE_FAILED],
            missing_count=len(issues), review_required_count=review_count,
            issues=[PayrollImportMappingIssueRead.model_validate(issue) for issue in issues],
        )


__all__ = ["PayrollAdapterService"]
