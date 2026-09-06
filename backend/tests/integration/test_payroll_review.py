from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidCanonicalOverrideError,
    InvalidReviewValueError,
    PayrollImportNotFoundError,
    PayrollReviewIncompleteError,
    PayrollReviewVersionConflictError,
)
from app.models.enums import (
    PayrollFieldMappingScope,
    PayrollImportFieldReviewStatus,
    PayrollImportReviewStatus,
    PayrollImportStatus,
    PayrollReviewCorrectionAction,
    PayrollReviewFieldStatus,
)
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_import import (
    PayrollFieldMapping,
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
    PayrollImportMappedField,
)
from app.models.payroll_review import (
    PayrollImportFieldCorrection,
    PayrollImportReviewSnapshot,
    PayrollImportReviewSnapshotField,
)
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.models.user import User
from app.schemas.payroll_import import (
    PayrollReviewCorrectionRequest,
    PayrollReviewFinalizeRequest,
    PayrollReviewRevertRequest,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.canonical_fields import REQUIRED_CANONICAL_FIELDS
from app.services.imports.label_normalization import normalize_source_label
from app.services.imports.payroll_adapter_service import PayrollAdapterService
from app.services.imports.payroll_review_service import PayrollReviewService


def _raw_for(definition) -> str:
    if definition.canonical_key == "employee_identifier":
        return "EMP-42"
    if definition.canonical_key == "period_year":
        return "2026"
    if definition.canonical_key == "period_month":
        return "9"
    if definition.value_type.value == "DAY_COUNT":
        return "30.00" if definition.canonical_key == "paid_days" else "0.00"
    return "1000.00"


def seed_review_import(
    sync: Session, *, problems: dict[str, str] | None = None,
    omit: set[str] | None = None, generic: list[tuple[str, str, str, str]] | None = None,
):
    problems, omit, generic = problems or {}, omit or set(), generic or []
    organization = Organization(
        id=uuid4(), name="Review Company", code=f"REV-{uuid4().hex[:8]}",
        timezone="Europe/Istanbul", is_active=True,
    )
    user_row = User(
        id=uuid4(), organization_id=organization.id,
        email=f"review-{uuid4().hex}@test.invalid", password_hash="unused", is_active=True,
    )
    import_id, document_id = uuid4(), uuid4()
    item = PayrollImport(
        id=import_id, organization_id=organization.id, uploaded_by_user_id=user_row.id,
        status=PayrollImportStatus.REVIEW_REQUIRED, source_type="DOCUMENT_UPLOAD",
        reader_provider="GENERAL_READER", source_document_id=document_id,
        content_sha256=uuid4().hex * 2, reader_table_count=0,
        reader_warnings=[], processing_attempt=1,
    )
    document = PayrollImportDocument(
        id=document_id, organization_id=organization.id, payroll_import_id=import_id,
        file_id=uuid4(), original_filename="review.png", declared_mime_type="image/png",
        detected_mime_type="image/png", size_bytes=10, sha256=item.content_sha256,
        storage_provider="LOCAL", storage_key=f"review/{uuid4().hex}",
    )
    sync.add_all([organization, user_row])
    sync.flush()
    sync.add_all([item, document])
    sync.flush()
    fields = {}
    for definition in REQUIRED_CANONICAL_FIELDS:
        key = definition.canonical_key
        if key in omit:
            continue
        problem = problems.get(key)
        label = f"Review {key} {uuid4().hex}"
        raw = "74.4OO,00" if problem == "parse" else _raw_for(definition)
        field = PayrollImportField(
            id=uuid4(), organization_id=organization.id, payroll_import_id=import_id,
            payroll_import_document_id=document_id, source_field_id=f"source-{key}",
            source_label=label, raw_value=raw, normalized_value=raw,
            value_type=definition.value_type.value.casefold(), confidence=Decimal("0.99"),
            page_number=1, extraction_source="rule",
            review_status=(
                PayrollImportFieldReviewStatus.REVIEW_REQUIRED
                if problem == "review" else PayrollImportFieldReviewStatus.UNREVIEWED
            ),
        )
        sync.add(field)
        sync.flush()
        fields[key] = field
        if problem != "unmapped":
            sync.add(PayrollFieldMapping(
                id=uuid4(), organization_id=organization.id,
                scope=PayrollFieldMappingScope.ORGANIZATION,
                source_field_id=field.source_field_id,
                source_label_normalized=normalize_source_label(label),
                canonical_key=key, section_key=definition.section_key,
                target_value_type=definition.value_type,
                priority=10, version=1, is_active=True,
            ))
            if problem == "ambiguous":
                alternative = next(value for value in REQUIRED_CANONICAL_FIELDS
                                   if value.canonical_key != key)
                sync.add(PayrollFieldMapping(
                    id=uuid4(), organization_id=organization.id,
                    scope=PayrollFieldMappingScope.ORGANIZATION,
                    source_field_id=field.source_field_id,
                    source_label_normalized=normalize_source_label(label),
                    canonical_key=alternative.canonical_key,
                    section_key=alternative.section_key,
                    target_value_type=alternative.value_type,
                    priority=10, version=1, is_active=True,
                ))
    for external_id, label, raw, value_type in generic:
        field = PayrollImportField(
            id=uuid4(), organization_id=organization.id, payroll_import_id=import_id,
            payroll_import_document_id=document_id, source_field_id=external_id,
            source_label=label, raw_value=raw, normalized_value=raw,
            value_type=value_type, confidence=Decimal("0.99"), page_number=1,
            extraction_source="rule", review_status=PayrollImportFieldReviewStatus.UNREVIEWED,
        )
        sync.add(field)
        fields[external_id] = field
    sync.flush()
    user = AuthenticatedUser(
        id=user_row.id, organization_id=organization.id, roles=frozenset(), employee_id=None,
    )
    return user, item, fields


async def mapped_by_source(session: AsyncSession, user, import_id):
    result = await PayrollAdapterService(session).mapped_fields(user, import_id)
    return {item.source_external_field_id: item for item in result.items}


@pytest.mark.asyncio
async def test_typed_corrections_history_revert_and_ownership_are_separate(
    async_db_session: AsyncSession,
):
    user, item, fields = await async_db_session.run_sync(lambda sync: seed_review_import(
        sync, generic=[
            ("generic-text", "Banka", "Eski Banka", "text"),
            ("generic-date", "Belge Tarihi", "01.09.2026", "date"),
        ],
    ))
    await PayrollAdapterService(async_db_session).run(user, item.id)
    review = await PayrollReviewService(async_db_session).start(user, item.id)
    assert review.status == PayrollImportReviewStatus.READY_FOR_SNAPSHOT
    rows = await mapped_by_source(async_db_session, user, item.id)

    original_source = fields["net_pay"].raw_value
    original_adapter = rows["source-net_pay"].typed_value.value
    cases = [
        ("source-net_pay", "74400.00", "net_pay", "DECIMAL", "74400.00"),
        ("source-period_year", "2027", None, "INTEGER", 2027),
        ("source-paid_days", "29.50", None, "DAY_COUNT", "29.50"),
        ("generic-text", "Yeni Banka", None, "TEXT", "Yeni Banka"),
        ("generic-date", "2026-09-02", None, "DATE", "2026-09-02"),
    ]
    version = review.version
    for source_id, value, canonical_key, expected_type, expected_value in cases:
        response = await PayrollReviewService(async_db_session).correct(
            user, item.id, rows[source_id].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=version, canonical_key=canonical_key,
                value=value, reason=f"Verified {source_id}",
            ),
        )
        version += 1
        assert response.version == version
        field = next(value for value in response.fields
                     if value.source.external_field_id == source_id)
        assert field.effective.typed_value.type.value == expected_type
        assert field.effective.typed_value.value == expected_value
        assert field.effective.provenance.value == "REVIEWER_CORRECTION"

    second = await PayrollReviewService(async_db_session).correct(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=version, value="75000.00", reason="Second verification",
        ),
    )
    version += 1
    net = next(value for value in second.fields
               if value.source.external_field_id == "source-net_pay")
    assert [value.revision for value in net.correction_history] == [1, 2]
    assert net.effective.typed_value.value == "75000.00"

    reverted = await PayrollReviewService(async_db_session).revert(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewRevertRequest(
            expected_review_version=version, reason="Use the unchanged adapter observation",
        ),
    )
    net = next(value for value in reverted.fields
               if value.source.external_field_id == "source-net_pay")
    assert [value.action for value in net.correction_history] == [
        PayrollReviewCorrectionAction.APPLY,
        PayrollReviewCorrectionAction.APPLY,
        PayrollReviewCorrectionAction.REVERT,
    ]
    assert net.effective.typed_value.value == original_adapter
    assert net.effective.provenance.value == "ADAPTER"

    def verify(sync: Session):
        source = sync.get(PayrollImportField, fields["net_pay"].id)
        mapped = sync.scalar(select(PayrollImportMappedField).where(
            PayrollImportMappedField.payroll_import_field_id == source.id
        ))
        corrections = sync.scalars(select(PayrollImportFieldCorrection).where(
            PayrollImportFieldCorrection.payroll_import_field_id == source.id
        ).order_by(PayrollImportFieldCorrection.revision)).all()
        return source.raw_value, mapped.value_decimal, corrections

    source_raw, mapped_value, corrections = await async_db_session.run_sync(verify)
    assert source_raw == original_source
    assert format(mapped_value, "f") == original_adapter
    assert len(corrections) == 3
    assert all(value.organization_id == user.organization_id for value in corrections)
    assert all(value.reviewer_user_id == user.id for value in corrections)
    assert all(value.reason for value in corrections)


@pytest.mark.asyncio
async def test_validation_and_optimistic_concurrency_reject_unsafe_changes(
    async_db_session: AsyncSession,
):
    user, item, _ = await async_db_session.run_sync(seed_review_import)
    import_id = item.id
    await PayrollAdapterService(async_db_session).run(user, import_id)
    review = await PayrollReviewService(async_db_session).start(user, import_id)
    rows = await mapped_by_source(async_db_session, user, import_id)

    with pytest.raises(ValidationError):
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version, value="100", reason="   ",
        )
    with pytest.raises(InvalidCanonicalOverrideError):
        await PayrollReviewService(async_db_session).correct(
                user, import_id, rows["source-net_pay"].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=review.version,
                canonical_key="invented_payroll_meaning", value="1.00", reason="Invalid key",
            ),
        )
    with pytest.raises(InvalidReviewValueError):
        await PayrollReviewService(async_db_session).correct(
                user, import_id, rows["source-net_pay"].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=review.version,
                value="not money", reason="Invalid value",
            ),
        )

    first = await PayrollReviewService(async_db_session).correct(
        user, import_id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version, value="1200.00", reason="Reviewer A",
        ),
    )
    assert first.version == review.version + 1
    with pytest.raises(PayrollReviewVersionConflictError):
        await PayrollReviewService(async_db_session).correct(
            user, import_id, rows["source-net_pay"].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=review.version, value="1300.00", reason="Reviewer B",
            ),
        )
    stored = await PayrollReviewService(async_db_session).get(user, import_id)
    assert stored.version == first.version
    net = next(value for value in stored.fields
               if value.source.external_field_id == "source-net_pay")
    assert net.effective.typed_value.value == "1200.00"


@pytest.mark.asyncio
async def test_structural_completeness_requires_resolutions_and_real_sources(
    async_db_session: AsyncSession,
):
    problems = {
        "gross_earnings": "ambiguous",
        "income_tax": "unmapped",
        "net_pay": "parse",
        "stamp_tax": "review",
    }
    user, item, _ = await async_db_session.run_sync(
        lambda sync: seed_review_import(sync, problems=problems)
    )
    import_id = item.id
    await PayrollAdapterService(async_db_session).run(user, import_id)
    service = PayrollReviewService(async_db_session)
    review = await service.start(user, import_id)
    codes = {issue.code for issue in review.issues}
    assert {
        "AMBIGUOUS_MAPPING_UNRESOLVED", "VALUE_PARSE_FAILED_UNRESOLVED",
        "SOURCE_REVIEW_REQUIRED_UNRESOLVED", "REQUIRED_CANONICAL_FIELD_MISSING",
    }.issubset(codes)
    with pytest.raises(PayrollReviewIncompleteError):
        await service.finalize(
            user, import_id, PayrollReviewFinalizeRequest(expected_review_version=review.version)
        )

    rows = await mapped_by_source(async_db_session, user, import_id)
    fixes = [
        ("source-gross_earnings", "gross_earnings", "1000.00"),
        ("source-income_tax", "income_tax", "1000.00"),
        ("source-net_pay", None, "74400.00"),
        ("source-stamp_tax", None, "1000.00"),
    ]
    version = review.version
    for source_id, canonical_key, value in fixes:
        review = await service.correct(
            user, import_id, rows[source_id].id,
            PayrollReviewCorrectionRequest(
                expected_review_version=version, canonical_key=canonical_key,
                value=value, reason="Resolve structural review issue",
            ),
        )
        version = review.version
    assert review.complete
    assert review.status == PayrollImportReviewStatus.READY_FOR_SNAPSHOT

    missing_user, missing_item, _ = await async_db_session.run_sync(
        lambda sync: seed_review_import(sync, omit={"net_pay"})
    )
    missing_import_id = missing_item.id
    await PayrollAdapterService(async_db_session).run(missing_user, missing_import_id)
    missing_review = await service.start(missing_user, missing_import_id)
    assert any(
        issue.code == "REQUIRED_CANONICAL_FIELD_MISSING"
        and issue.canonical_key == "net_pay" for issue in missing_review.issues
    )
    with pytest.raises(PayrollReviewIncompleteError):
        await service.finalize(
            missing_user, missing_import_id,
            PayrollReviewFinalizeRequest(expected_review_version=missing_review.version),
        )


@pytest.mark.asyncio
async def test_adapter_rerun_preserves_compatible_correction_and_marks_changed_one_stale(
    async_db_session: AsyncSession,
):
    user, item, fields = await async_db_session.run_sync(seed_review_import)
    adapter = PayrollAdapterService(async_db_session)
    await adapter.run(user, item.id)
    review = await PayrollReviewService(async_db_session).start(user, item.id)
    rows = await mapped_by_source(async_db_session, user, item.id)
    corrected = await PayrollReviewService(async_db_session).correct(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version, value="1250.00", reason="OCR correction",
        ),
    )
    await adapter.run(user, item.id)
    compatible = await PayrollReviewService(async_db_session).get(user, item.id)
    assert compatible.version == corrected.version
    net = next(value for value in compatible.fields
               if value.source.external_field_id == "source-net_pay")
    assert net.effective.typed_value.value == "1250.00"
    assert not net.correction.is_stale

    def mutate_source(sync: Session):
        source = sync.get(PayrollImportField, fields["net_pay"].id)
        source.raw_value = "1300.00"
        source.normalized_value = "1300.00"
        sync.flush()

    await async_db_session.run_sync(mutate_source)
    await adapter.run(user, item.id)
    stale = await PayrollReviewService(async_db_session).get(user, item.id)
    assert stale.version == compatible.version + 1
    net = next(value for value in stale.fields
               if value.source.external_field_id == "source-net_pay")
    assert net.review_status == PayrollReviewFieldStatus.STALE
    assert net.correction.is_stale
    assert net.effective.typed_value is None
    assert stale.status == PayrollImportReviewStatus.IN_PROGRESS
    with pytest.raises(PayrollReviewIncompleteError):
        await PayrollReviewService(async_db_session).finalize(
            user, item.id,
            PayrollReviewFinalizeRequest(expected_review_version=stale.version),
        )
    count = await async_db_session.scalar(select(func.count()).select_from(
        PayrollImportFieldCorrection
    ).where(PayrollImportFieldCorrection.review_id == stale.id))
    assert count == 1


@pytest.mark.asyncio
async def test_snapshot_versioning_checksum_generic_fields_immutability_and_no_side_effects(
    async_db_session: AsyncSession,
):
    tracked = [Payroll, PayrollVersion, PayrollEarning, PayrollDeduction,
               PayrollAbsence, TaxCalculationRun, TaxCumulativeRecord]

    def seed(sync: Session):
        user, item, _ = seed_review_import(sync, generic=[
            ("sgk-registration", "SGK Sicil No", "123456", "identifier"),
            ("bank", "Banka", "Bordro Bank", "text"),
        ])
        counts = {model: sync.scalar(select(func.count()).select_from(model)) for model in tracked}
        return user, item, counts

    user, item, before = await async_db_session.run_sync(seed)
    await PayrollAdapterService(async_db_session).run(user, item.id)
    service = PayrollReviewService(async_db_session)
    review = await service.start(user, item.id)
    first = await service.finalize(
        user, item.id, PayrollReviewFinalizeRequest(expected_review_version=review.version)
    )
    assert first.snapshot_version == 1
    assert first.snapshot_checksum == sha256_repeatable(first)
    assert first.issue_count == 0
    assert any(field.effective_canonical_key is None and field.source_field_id == "bank"
               for field in first.fields)
    assert any(field.source_field_id == "sgk-registration" for field in first.fields)
    net_first = next(field for field in first.fields
                     if field.effective_canonical_key == "net_pay")
    assert net_first.typed_value.value == "1000.00"

    unchanged = await service.finalize(
        user, item.id, PayrollReviewFinalizeRequest(expected_review_version=review.version + 1)
    )
    assert unchanged.id == first.id
    assert (await service.snapshots(user, item.id)).count == 1

    await PayrollAdapterService(async_db_session).run(user, item.id)
    after_rerun = await service.snapshot(user, item.id, first.id)
    assert after_rerun.snapshot_checksum == first.snapshot_checksum
    assert after_rerun.fields == first.fields

    rows = await mapped_by_source(async_db_session, user, item.id)
    changed_review = await service.correct(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewCorrectionRequest(
            expected_review_version=review.version + 1,
            value="1100.10", reason="Verified corrected net pay",
        ),
    )
    second = await service.finalize(
        user, item.id,
        PayrollReviewFinalizeRequest(expected_review_version=changed_review.version),
    )
    assert second.snapshot_version == 2
    assert second.id != first.id
    old = await service.snapshot(user, item.id, first.id)
    assert old.snapshot_checksum == first.snapshot_checksum
    assert next(field for field in old.fields
                if field.effective_canonical_key == "net_pay").typed_value.value == "1000.00"
    assert next(field for field in second.fields
                if field.effective_canonical_key == "net_pay").typed_value.value == "1100.10"

    reverted_review = await service.revert(
        user, item.id, rows["source-net_pay"].id,
        PayrollReviewRevertRequest(
            expected_review_version=changed_review.version + 1,
            reason="Return to the current adapter value",
        ),
    )
    third = await service.finalize(
        user, item.id,
        PayrollReviewFinalizeRequest(expected_review_version=reverted_review.version),
    )
    assert third.snapshot_version == 3
    assert third.id not in {first.id, second.id}
    assert third.snapshot_checksum == first.snapshot_checksum

    def counts(sync: Session):
        return {model: sync.scalar(select(func.count()).select_from(model)) for model in tracked}

    assert await async_db_session.run_sync(counts) == before

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="review snapshots are immutable"):
        await async_db_session.execute(update(PayrollImportReviewSnapshot).where(
            PayrollImportReviewSnapshot.id == first.id
        ).values(field_count=999))
        await async_db_session.flush()
    await nested.rollback()

    nested = await async_db_session.begin_nested()
    with pytest.raises(DBAPIError, match="review snapshots are immutable"):
        await async_db_session.execute(update(PayrollImportReviewSnapshotField).where(
            PayrollImportReviewSnapshotField.snapshot_id == first.id
        ).values(value_text="tampered"))
        await async_db_session.flush()
    await nested.rollback()


def sha256_repeatable(snapshot) -> str:
    """Recompute the documented content checksum without snapshot/row IDs."""
    from app.services.imports.review_checksums import sha256_canonical

    payload = []
    for field in snapshot.fields:
        typed = field.typed_value
        payload.append({
            "adapter_fingerprint": field.adapter_fingerprint,
            "bbox": field.bbox,
            "confidence": field.confidence,
            "effective_canonical_key": field.effective_canonical_key,
            "extraction_source": field.extraction_source,
            "original_mapping_status": field.original_mapping_status.value,
            "page_number": field.page_number,
            "provenance": field.provenance.value,
            "raw_value": field.raw_value,
            "review_status": field.review_status.value,
            "section_key": field.section_key,
            "source_field_id": field.source_field_id,
            "source_import_field_id": str(field.source_import_field_id),
            "source_label": field.source_label,
            "source_text": field.source_text,
            "source_value_type": field.source_value_type,
            "value_date": typed.value if typed.type.value == "DATE" else None,
            "value_decimal": typed.value if typed.type.value in {"DECIMAL", "DAY_COUNT"} else None,
            "value_integer": typed.value if typed.type.value == "INTEGER" else None,
            "value_text": typed.value if typed.type.value in {"TEXT", "IDENTIFIER"} else None,
            "value_type": typed.type.value,
        })
    payload.sort(key=lambda value: value["source_import_field_id"])
    return sha256_canonical(payload)


@pytest.mark.asyncio
async def test_review_service_is_tenant_scoped(async_db_session: AsyncSession):
    owner, item, _ = await async_db_session.run_sync(seed_review_import)
    outsider, _, _ = await async_db_session.run_sync(seed_review_import)
    await PayrollAdapterService(async_db_session).run(owner, item.id)
    await PayrollReviewService(async_db_session).start(owner, item.id)
    with pytest.raises(PayrollImportNotFoundError):
        await PayrollReviewService(async_db_session).get(outsider, item.id)
    with pytest.raises(PayrollImportNotFoundError):
        await PayrollReviewService(async_db_session).snapshots(outsider, item.id)
